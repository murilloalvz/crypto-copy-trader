import json
from dataclasses import asdict, dataclass

from src.database import connection
from src.strategy_versions import WAVE_STRATEGY_VERSION
from src.wallet_confirmation_placebo import (
    ConfirmationPolicy,
    WalletCohort,
    validate_cohort_design,
)


DEFAULT_MATCHING_METHOD_VERSION = "wallet_placebo_matching_v1_preperiod"
DEFAULT_CONTEXT_SCOPE = "wave_opportunity_v1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS wallet_confirmation_studies (
    study_key TEXT PRIMARY KEY,
    spec_json TEXT NOT NULL,
    frozen_at INTEGER NOT NULL,
    preperiod_cutoff INTEGER NOT NULL,
    starts_at INTEGER NOT NULL,
    ends_at INTEGER,
    context_scope TEXT NOT NULL,
    matching_method_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'FROZEN',
    activated_at INTEGER,
    closed_at INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wallet_confirmation_studies_status
ON wallet_confirmation_studies(status, starts_at);

CREATE TABLE IF NOT EXISTS wallet_confirmation_study_cohorts (
    study_key TEXT NOT NULL,
    cohort_name TEXT NOT NULL,
    cohort_role TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (study_key, cohort_name, wallet_address),
    FOREIGN KEY (study_key) REFERENCES wallet_confirmation_studies(study_key)
);

CREATE INDEX IF NOT EXISTS idx_wallet_confirmation_study_wallet
ON wallet_confirmation_study_cohorts(wallet_address, study_key);
"""


@dataclass(frozen=True)
class ConfirmationStudySpec:
    """Immutable pre-registration for one prospective confirmation/placebo study."""

    study_key: str
    frozen_at: int
    preperiod_cutoff: int
    starts_at: int
    ends_at: int | None
    target: WalletCohort
    placebos: tuple[WalletCohort, ...]
    policy: ConfirmationPolicy
    horizons_minutes: tuple[int, ...]
    context_scope: str = DEFAULT_CONTEXT_SCOPE
    matching_method_version: str = DEFAULT_MATCHING_METHOD_VERSION
    wave_strategy_version: str = WAVE_STRATEGY_VERSION
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.study_key.strip():
            raise ValueError("study_key cannot be empty")
        if min(self.frozen_at, self.preperiod_cutoff, self.starts_at) < 0:
            raise ValueError("study timestamps must be non-negative")
        if self.preperiod_cutoff > self.frozen_at:
            raise ValueError("preperiod_cutoff cannot be after frozen_at")
        if self.frozen_at > self.starts_at:
            raise ValueError("study must be frozen no later than starts_at")
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be later than starts_at")
        if self.context_scope != DEFAULT_CONTEXT_SCOPE:
            raise ValueError("unsupported context_scope for v1")
        if not self.matching_method_version.strip():
            raise ValueError("matching_method_version cannot be empty")
        if not self.wave_strategy_version.strip():
            raise ValueError("wave_strategy_version cannot be empty")
        horizons = tuple(int(value) for value in self.horizons_minutes)
        if not horizons or any(value <= 0 for value in horizons):
            raise ValueError("horizons_minutes must contain positive values")
        if len(set(horizons)) != len(horizons):
            raise ValueError("horizons_minutes must be unique")

        validate_cohort_design(self.target, self.placebos)
        all_cohorts = (self.target, *self.placebos)
        if any(self.policy.min_unique_buy_wallets > len(item.addresses) for item in all_cohorts):
            raise ValueError(
                "confirmation threshold cannot exceed wallet count in any cohort"
            )


@dataclass(frozen=True)
class StoredConfirmationStudy:
    spec: ConfirmationStudySpec
    status: str
    activated_at: int | None
    closed_at: int | None


@dataclass(frozen=True)
class StudyRegistrationResult:
    study_key: str
    created: bool
    status: str


def ensure_confirmation_study_schema() -> None:
    with connection() as conn:
        conn.executescript(_SCHEMA)


def _canonical_spec_json(spec: ConfirmationStudySpec) -> str:
    return json.dumps(
        asdict(spec),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _cohort_from_dict(payload: dict) -> WalletCohort:
    return WalletCohort(
        name=str(payload["name"]),
        addresses=tuple(str(value) for value in payload["addresses"]),
        role=str(payload["role"]),
    )


def _spec_from_json(raw: str) -> ConfirmationStudySpec:
    payload = json.loads(raw)
    return ConfirmationStudySpec(
        study_key=str(payload["study_key"]),
        frozen_at=int(payload["frozen_at"]),
        preperiod_cutoff=int(payload["preperiod_cutoff"]),
        starts_at=int(payload["starts_at"]),
        ends_at=(None if payload.get("ends_at") is None else int(payload["ends_at"])),
        target=_cohort_from_dict(payload["target"]),
        placebos=tuple(_cohort_from_dict(item) for item in payload["placebos"]),
        policy=ConfirmationPolicy(**payload["policy"]),
        horizons_minutes=tuple(int(value) for value in payload["horizons_minutes"]),
        context_scope=str(payload["context_scope"]),
        matching_method_version=str(payload["matching_method_version"]),
        wave_strategy_version=str(
            payload.get("wave_strategy_version") or WAVE_STRATEGY_VERSION
        ),
        notes=str(payload.get("notes") or ""),
    )


def register_confirmation_study(
    spec: ConfirmationStudySpec,
) -> StudyRegistrationResult:
    """Persist a frozen study spec; an existing key can never be silently rewritten."""

    ensure_confirmation_study_schema()
    canonical = _canonical_spec_json(spec)
    with connection() as conn:
        existing = conn.execute(
            "SELECT spec_json, status FROM wallet_confirmation_studies WHERE study_key=?",
            (spec.study_key,),
        ).fetchone()
        if existing is not None:
            if str(existing["spec_json"]) != canonical:
                raise ValueError("study_key already exists with a different frozen spec")
            return StudyRegistrationResult(
                study_key=spec.study_key,
                created=False,
                status=str(existing["status"]),
            )

        conn.execute(
            """INSERT INTO wallet_confirmation_studies(
                study_key, spec_json, frozen_at, preperiod_cutoff, starts_at, ends_at,
                context_scope, matching_method_version, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'FROZEN')""",
            (
                spec.study_key,
                canonical,
                spec.frozen_at,
                spec.preperiod_cutoff,
                spec.starts_at,
                spec.ends_at,
                spec.context_scope,
                spec.matching_method_version,
            ),
        )
        cohort_rows = []
        for cohort in (spec.target, *spec.placebos):
            cohort_rows.extend(
                (spec.study_key, cohort.name, cohort.role, address)
                for address in cohort.addresses
            )
        conn.executemany(
            """INSERT INTO wallet_confirmation_study_cohorts(
                study_key, cohort_name, cohort_role, wallet_address
            ) VALUES (?, ?, ?, ?)""",
            cohort_rows,
        )
    return StudyRegistrationResult(spec.study_key, True, "FROZEN")


def load_confirmation_study(study_key: str) -> StoredConfirmationStudy | None:
    ensure_confirmation_study_schema()
    with connection() as conn:
        row = conn.execute(
            """SELECT spec_json, status, activated_at, closed_at
            FROM wallet_confirmation_studies WHERE study_key=?""",
            (study_key,),
        ).fetchone()
    if row is None:
        return None
    return StoredConfirmationStudy(
        spec=_spec_from_json(str(row["spec_json"])),
        status=str(row["status"]),
        activated_at=(
            None if row["activated_at"] is None else int(row["activated_at"])
        ),
        closed_at=None if row["closed_at"] is None else int(row["closed_at"]),
    )


def activate_confirmation_study(study_key: str, *, now: int) -> bool:
    """Activate only after the frozen start boundary; never mutate the spec itself."""

    if now < 0:
        raise ValueError("now must be non-negative")
    ensure_confirmation_study_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT starts_at, ends_at, status FROM wallet_confirmation_studies WHERE study_key=?",
            (study_key,),
        ).fetchone()
        if row is None:
            raise ValueError("unknown study_key")
        status = str(row["status"])
        if status == "ACTIVE":
            return False
        if status != "FROZEN":
            raise ValueError(f"cannot activate study from status {status}")
        if now < int(row["starts_at"]):
            raise ValueError("cannot activate before frozen starts_at")
        if row["ends_at"] is not None and now >= int(row["ends_at"]):
            raise ValueError("cannot activate after study ends_at")
        cursor = conn.execute(
            """UPDATE wallet_confirmation_studies
            SET status='ACTIVE', activated_at=?
            WHERE study_key=? AND status='FROZEN'""",
            (now, study_key),
        )
    return bool(cursor.rowcount)


def close_confirmation_study(study_key: str, *, now: int) -> bool:
    if now < 0:
        raise ValueError("now must be non-negative")
    ensure_confirmation_study_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT starts_at, status FROM wallet_confirmation_studies WHERE study_key=?",
            (study_key,),
        ).fetchone()
        if row is None:
            raise ValueError("unknown study_key")
        status = str(row["status"])
        if status == "CLOSED":
            return False
        if status != "ACTIVE":
            raise ValueError(f"cannot close study from status {status}")
        if now < int(row["starts_at"]):
            raise ValueError("closed_at cannot precede starts_at")
        cursor = conn.execute(
            """UPDATE wallet_confirmation_studies
            SET status='CLOSED', closed_at=?
            WHERE study_key=? AND status='ACTIVE'""",
            (now, study_key),
        )
    return bool(cursor.rowcount)
