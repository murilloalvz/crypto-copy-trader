"""Corte de seguranca: transforma o registro cru da GoPlus (+ token info do GeckoTerminal) em veredito.

Veredito do conjunto: 'falhou' | 'ok' | 'parcial' | 'sem_dado'.
  * qualquer item reprovado          -> 'falhou' (corte binario; o motivo vai pro descartados.csv)
  * todos os itens obrigatorios ok   -> 'ok'
  * alguns ok, outros sem dado       -> 'parcial'
  * nenhum verificado                -> 'sem_dado'
"Sem dado" NUNCA vira "ok". O que fazer com 'parcial'/'sem_dado' e politica do config
(seguranca.sem_dado_acao), decidida no engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .http import ApiError
from .models import PoolSnap, TokenInfo
from .util import to_float

OK, FAIL, NODATA, NA = "ok", "fail", "nodata", "na"

EVM_REQUIRED = ("honeypot", "taxas", "open_source", "lp", "top10")
SOLANA_REQUIRED = ("mint_authority", "freeze_authority")


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    value: Any = None
    source: str = "goplus"


@dataclass
class SecurityResult:
    status: str
    checks: list[Check] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    top10_pct: Optional[float] = None
    description: str = ""
    note: str = ""

    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL]

    def nodata(self) -> list[Check]:
        return [c for c in self.checks if c.status == NODATA]

    def failure_reason(self) -> str:
        return "; ".join(f"{c.name}: {c.detail}" if c.detail else c.name for c in self.failures())

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "top10_pct": self.top10_pct,
            "warnings": self.warnings,
            "note": self.note,
            "checks": [
                {"name": c.name, "status": c.status, "detail": c.detail, "source": c.source}
                for c in self.checks
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SecurityResult":
        return cls(
            status=data.get("status", "sem_dado"),
            checks=[Check(c["name"], c["status"], c.get("detail", ""), None, c.get("source", "goplus")) for c in data.get("checks", [])],
            warnings=list(data.get("warnings", [])),
            top10_pct=data.get("top10_pct"),
            note=data.get("note", ""),
        )


def _is_one(record: dict, key: str) -> bool:
    return str(record.get(key, "")).strip() == "1"


def _pct_from_fraction(value: Any) -> Optional[float]:
    number = to_float(value)
    return None if number is None else number * 100.0


# ---------------------------------------------------------------------------
# EVM
# ---------------------------------------------------------------------------


def compute_top10(record: dict, snap: PoolSnap, evm_cfg: dict) -> tuple[Optional[float], str]:
    """Top 10 holders SEM pool/par/curva/queima. Devolve (pct, motivo_se_invalido)."""
    holders = record.get("holders")
    holder_count = to_float(record.get("holder_count"))
    min_count = evm_cfg["holders_min_contagem"]
    if not isinstance(holders, list) or not holders:
        return None, "GoPlus sem lista de holders"
    if holder_count is None or holder_count < min_count:
        return None, f"holder_count={holder_count:.0f} < {min_count} (lista incompleta/atrasada)" if holder_count is not None else "sem holder_count"
    ignored_addr = {a.lower() for a in evm_cfg["enderecos_ignorar_top10"]}
    ignored_addr.add(snap.pool.lower())
    for dex in record.get("dex") or []:
        if isinstance(dex, dict) and dex.get("pair"):
            ignored_addr.add(str(dex["pair"]).lower())
    ignored_tags = [t.lower() for t in evm_cfg["tags_ignorar_top10"]]
    shares: list[float] = []
    for holder in holders:
        if not isinstance(holder, dict):
            continue
        address = str(holder.get("address", "")).lower()
        tag = str(holder.get("tag", "")).lower()
        if address in ignored_addr or any(t and t in tag for t in ignored_tags):
            continue
        pct = _pct_from_fraction(holder.get("percent"))
        if pct is not None:
            shares.append(pct)
    shares.sort(reverse=True)
    return sum(shares[:10]), ""


def _evm_checks(record: Optional[dict], snap: PoolSnap, sec: dict) -> tuple[list[Check], list[str], Optional[float]]:
    evm = sec["evm"]
    checks: list[Check] = []
    warnings: list[str] = []
    stub = record is None or str(record.get("is_honeypot", "")).strip() == ""
    if stub:
        why = "GoPlus sem registro" if record is None else "registro vazio da GoPlus (sem analise)"
        return [Check(name, NODATA, why) for name in EVM_REQUIRED], warnings, None

    # honeypot
    if _is_one(record, "is_honeypot"):
        checks.append(Check("honeypot", FAIL, "honeypot"))
    else:
        checks.append(Check("honeypot", OK))

    # taxas
    buy_tax, sell_tax = _pct_from_fraction(record.get("buy_tax")), _pct_from_fraction(record.get("sell_tax"))
    limit = sec["taxa_max_pct"]
    if buy_tax is None or sell_tax is None:
        checks.append(Check("taxas", NODATA, "taxa de compra/venda nao informada"))
    elif max(buy_tax, sell_tax) > limit:
        checks.append(Check("taxas", FAIL, f"compra {buy_tax:.1f}% / venda {sell_tax:.1f}% > {limit:g}%", value=(buy_tax, sell_tax)))
    else:
        checks.append(Check("taxas", OK, value=(buy_tax, sell_tax)))

    # codigo aberto
    open_source = str(record.get("is_open_source", "")).strip()
    if open_source == "":
        checks.append(Check("open_source", NODATA, "is_open_source nao informado"))
    elif open_source == "1":
        checks.append(Check("open_source", OK))
    elif evm["exigir_open_source"]:
        checks.append(Check("open_source", FAIL, "contrato nao verificado"))
    else:
        checks.append(Check("open_source", OK, "nao verificado (permitido)"))
        warnings.append("contrato nao verificado")

    # LP travada/queimada (so pool AMM v2)
    if snap.dex not in set(evm["lp_aplicar_em_dex"]):
        checks.append(Check("lp", NA, f"nao se aplica a {snap.dex or 'dex desconhecida'}"))
    else:
        lp_holders = record.get("lp_holders")
        if not isinstance(lp_holders, list) or not lp_holders:
            checks.append(Check("lp", NODATA, "sem lp_holders"))
        else:
            locked = 0.0
            for holder in lp_holders:
                if isinstance(holder, dict) and str(holder.get("is_locked", "")).strip() == "1":
                    locked += _pct_from_fraction(holder.get("percent")) or 0.0
            need = evm["lp_min_travada_queimada_pct"]
            if locked < need:
                checks.append(Check("lp", FAIL, f"LP travada/queimada {locked:.0f}% < {need:g}%", value=locked))
            else:
                checks.append(Check("lp", OK, value=locked))

    # top10
    top10, why = compute_top10(record, snap, evm)
    if top10 is None:
        checks.append(Check("top10", NODATA, why))
    elif top10 > sec["top10_max_pct"]:
        checks.append(Check("top10", FAIL, f"top10 {top10:.1f}% > {sec['top10_max_pct']:g}%", value=top10))
    else:
        checks.append(Check("top10", OK, value=top10))

    # itens que so reprovam/avisam quando o dado existe
    for flag in evm["flags_bloqueantes"]:
        if _is_one(record, flag):
            checks.append(Check(f"flag:{flag}", FAIL, flag))
    for flag in evm["flags_aviso"]:
        if _is_one(record, flag):
            warnings.append(flag)
    owner = str(record.get("owner_address", "") or "").strip().lower()
    burned = {a.lower() for a in evm["enderecos_ignorar_top10"]}
    if owner and owner not in burned:
        if evm["exigir_owner_renunciado"]:
            checks.append(Check("owner", FAIL, "owner nao renunciado"))
        else:
            warnings.append("owner ativo")
    if _is_one(record, "is_mintable"):
        if evm["bloquear_mintable"]:
            checks.append(Check("mintable", FAIL, "token mintavel"))
        else:
            warnings.append("mintavel")
    return checks, warnings, top10


# ---------------------------------------------------------------------------
# Solana
# ---------------------------------------------------------------------------


def _authority_state(node: Any) -> Optional[bool]:
    """GoPlus Solana: {'status': '0'|'1', 'authority': [...]}. True = autoridade existe (ruim)."""
    if isinstance(node, dict):
        status = str(node.get("status", "")).strip()
        if status in ("0", "1"):
            return status == "1"
    return None


def _gt_authority_state(value: Optional[str]) -> Optional[bool]:
    if value == "no":
        return False
    if value == "yes":
        return True
    return None


def _solana_checks(record: Optional[dict], sec: dict, info: Optional[TokenInfo]) -> tuple[list[Check], list[str], str]:
    use_gt = sec["solana"]["usar_gt_para_mint_freeze"]
    checks: list[Check] = []
    warnings: list[str] = []
    description = ""
    rec = record or {}
    if isinstance(rec.get("metadata"), dict):
        description = str(rec["metadata"].get("description") or "")

    for name, key, gt_value in (
        ("mint_authority", "mintable", getattr(info, "mint_authority", None)),
        ("freeze_authority", "freezable", getattr(info, "freeze_authority", None)),
    ):
        goplus_state = _authority_state(rec.get(key)) if record else None
        gt_state = _gt_authority_state(gt_value) if (use_gt and info is not None) else None
        label = "mint" if name == "mint_authority" else "freeze"
        if goplus_state or gt_state:  # qualquer fonte dizendo que existe = reprova (fail-closed)
            who = "GoPlus" if goplus_state else "GeckoTerminal"
            checks.append(Check(name, FAIL, f"{label} authority ativa ({who})", source="goplus" if goplus_state else "gt"))
        elif goplus_state is False:
            checks.append(Check(name, OK, source="goplus"))
        elif gt_state is False:
            checks.append(Check(name, OK, "verificado so pelo GeckoTerminal", source="gt"))
        else:
            why = "GoPlus sem dado" if record is None else f"{key} ausente no registro"
            checks.append(Check(name, NODATA, why))

    if record is not None:
        for key in ("closable", "balance_mutable_authority"):
            if _authority_state(rec.get(key)):
                checks.append(Check(f"flag:{key}", FAIL, f"{key} ativo"))
        if str(rec.get("non_transferable", "")).strip() == "1":
            checks.append(Check("flag:non_transferable", FAIL, "token nao transferivel"))
        if str(rec.get("default_account_state", "")).strip() == "2":
            checks.append(Check("flag:default_account_state", FAIL, "contas novas nascem congeladas"))
        if rec.get("transfer_hook"):
            checks.append(Check("flag:transfer_hook", FAIL, "transfer hook presente"))
        if isinstance(rec.get("transfer_fee"), dict) and rec["transfer_fee"]:
            checks.append(Check("flag:transfer_fee", FAIL, "taxa de transferencia (Token-2022)"))
        if _authority_state(rec.get("metadata_mutable")):
            warnings.append("metadata mutavel")
    return checks, warnings, description


# ---------------------------------------------------------------------------
# agregacao
# ---------------------------------------------------------------------------


def aggregate(checks: list[Check], required: tuple[str, ...]) -> str:
    if any(c.status == FAIL for c in checks):
        return "falhou"
    relevant = [c for c in checks if c.name in required and c.status != NA]
    ok = sum(1 for c in relevant if c.status == OK)
    nodata = sum(1 for c in relevant if c.status == NODATA)
    if nodata == 0 and ok > 0:
        return "ok"
    if ok == 0:
        return "sem_dado"
    return "parcial"


def evaluate(
    platform: str,
    record: Optional[dict],
    snap: PoolSnap,
    sec_cfg: dict,
    token_info: Optional[TokenInfo] = None,
    goplus_error: Optional[ApiError] = None,
) -> SecurityResult:
    """Veredito de seguranca de um token. `record` None = a GoPlus nao tem dado (ou a chamada falhou)."""
    if platform == "solana":
        checks, warnings, description = _solana_checks(record, sec_cfg, token_info)
        required = SOLANA_REQUIRED
        top10 = None
        # top10 na Solana: sem fonte confiavel na v0 (vira RPC na v1). Fica explicito, mas nao obrigatorio.
        checks.append(Check("top10", NODATA, "sem fonte confiavel na Solana (v0)"))
    else:
        checks, warnings, top10 = _evm_checks(record, snap, sec_cfg)
        required = EVM_REQUIRED
        description = ""
    status = aggregate(checks, required)
    note = ""
    if goplus_error is not None and record is None:
        note = f"goplus_erro:{goplus_error.kind}"
    if any(c.source == "gt" and c.status == OK for c in checks):
        note = (note + " " if note else "") + "mint/freeze verificados so pelo GeckoTerminal"
    return SecurityResult(
        status=status, checks=checks, warnings=warnings, top10_pct=top10, description=description, note=note
    )
