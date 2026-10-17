"""Linhagem on-chain de um token: qual launchpad o criou e qual pool nasceu da graduacao.

Somente leitura (RPC padrao). Usado no Passo 0 para conferir os exemplos do operador e, na Parte A,
para validar a enumeracao de migracoes por launchpad. Programas identificados pelos logs da transacao
(`Program <id> invoke [n]` e `Program log: Instruction: <Nome>`), nunca por palpite: se a transacao nao
mostra o programa, o resultado e "desconhecido".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .solana_rpc import SIGNATURES_PAGE_SIZE, RpcError, SolanaRpc, anchor_at_or_after

# programas conhecidos (conferidos nas transacoes reais dos exemplos; ver relatorio do Passo 0)
PROGRAMS = {
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": "pump.fun (curva)",
    "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA": "PumpSwap (AMM)",
    "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN": "Meteora DBC (curva)",
    "cpamdpZCGKUy5JxQXB4dcpGPiikHawvSWAd6mEn1sGG": "Meteora DAMM v2",
    "Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EQVn5UaB": "Meteora DAMM v1",
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo": "Meteora DLMM",
    "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj": "Raydium LaunchLab (curva)",
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "Raydium AMM v4",
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C": "Raydium CPMM",
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK": "Raydium CLMM",
}
LAUNCHPADS = {
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": "pumpfun",
    "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN": "meteora_dbc",
    "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj": "raydium_launchlab",
}

_INVOKE = re.compile(r"^Program (\w{32,44}) invoke \[(\d+)\]")
_INSTRUCTION = re.compile(r"^Program log: Instruction: (\w+)")


@dataclass
class TxSummary:
    signature: str
    block_time: Optional[int]
    slot: Optional[int]
    ok: bool
    programs: list[str] = field(default_factory=list)          # na ordem do 1o invoke
    top_level: list[str] = field(default_factory=list)          # invoke [1]
    instructions: list[tuple[str, str]] = field(default_factory=list)  # (programa, instrucao) na ordem dos logs
    signer: Optional[str] = None

    @property
    def launchpad(self) -> Optional[str]:
        for program in self.programs:
            if program in LAUNCHPADS:
                return LAUNCHPADS[program]
        return None

    def describe(self) -> str:
        names = [f"{PROGRAMS.get(p, p[:8])}:{ix}" for p, ix in self.instructions]
        return ", ".join(names) or "(sem instrucao nos logs)"


def summarize_tx(signature: str, tx: Optional[dict]) -> Optional[TxSummary]:
    if not tx:
        return None
    meta = tx.get("meta") or {}
    logs = meta.get("logMessages") or []
    stack: list[str] = []
    programs: list[str] = []
    top: list[str] = []
    instructions: list[tuple[str, str]] = []
    for line in logs:
        m = _INVOKE.match(line)
        if m:
            program, depth = m.group(1), int(m.group(2))
            del stack[depth - 1:]
            stack.append(program)
            if program not in programs:
                programs.append(program)
            if depth == 1:
                top.append(program)
            continue
        m = _INSTRUCTION.match(line)
        if m and stack:
            instructions.append((stack[-1], m.group(1)))
            continue
        if line.startswith("Program ") and (line.endswith(" success") or " failed" in line) and stack:
            stack.pop()
    keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    signer = None
    for key in keys:
        if isinstance(key, dict) and key.get("signer"):
            signer = key.get("pubkey")
            break
    return TxSummary(
        signature=signature,
        block_time=tx.get("blockTime"),
        slot=tx.get("slot"),
        ok=meta.get("err") is None,
        programs=programs,
        top_level=top,
        instructions=instructions,
        signer=signer,
    )


def top_level_instruction_names(tx: Optional[dict]) -> list[Optional[str]]:
    """Nome logado ('Program log: Instruction: X') de cada instrucao de NIVEL 1 (invoke [1]), na MESMA ordem
    de `tx.transaction.message.instructions` -- `None` quando o programa nao loga nome nenhum. Existe porque
    uma transacao pode chamar o MESMO programa em mais de uma instrucao de nivel 1 (ex.: um bot que compra e
    migra no mesmo envio) -- casar so pelo `programId` pega a 1a por acaso, nao necessariamente a certa
    (achado real: DBC com `InitializeVirtualPoolWithSplToken` + `Swap2` + `MigrationDammV2` na mesma tx;
    pump.fun com `BuyV2` + `MigrateV2`). Mesma mecanica de pilha de `summarize_tx`, so que marcando a QUAL
    instrucao de nivel 1 cada nome pertence."""
    if not tx:
        return []
    logs = (tx.get("meta") or {}).get("logMessages") or []
    depth = 0
    names: list[Optional[str]] = []
    for line in logs:
        m = _INVOKE.match(line)
        if m:
            depth = int(m.group(2))
            if depth == 1:
                names.append(None)
            continue
        if depth == 1:
            m = _INSTRUCTION.match(line)
            if m and names and names[-1] is None:
                names[-1] = m.group(1)
                continue
        if line.startswith("Program ") and (line.endswith(" success") or " failed" in line):
            depth = max(depth - 1, 0)
    return names


def oldest_signature(rpc: SolanaRpc, address: str, before: Optional[str], max_pages: int = 300) -> tuple[Optional[dict], int, bool]:
    """Pagina `getSignaturesForAddress` para tras a partir de `before` ate acabar.

    Devolve (linha mais antiga, quantas assinaturas viu, completo?). `completo=False` se bateu no teto de
    paginas (o "mais antigo" entao NAO e a criacao — o chamador deve tratar como desconhecido).
    """
    seen = 0
    oldest: Optional[dict] = None
    cursor = before
    for _ in range(max_pages):
        rows = rpc.signatures(address, before=cursor, limit=SIGNATURES_PAGE_SIZE)
        if not rows:
            return oldest, seen, True
        seen += len(rows)
        oldest = rows[-1]
        if len(rows) < SIGNATURES_PAGE_SIZE:
            return oldest, seen, True
        cursor = rows[-1]["signature"]
    return oldest, seen, False


def creation_time(rpc: SolanaRpc, mint: str, before_signature: str, max_pages: int = 30) -> tuple[Optional[int], int, bool]:
    """Criacao do token = blockTime da transacao BEM-SUCEDIDA mais antiga do mint, paginando para tras a partir da
    migracao (todo negocio na curva referencia o mint, entao o custo e ~1 pagina por mil negocios da curva).

    Devolve (blockTime ou None, assinaturas vistas, completo). Bateu no teto de paginas = criacao DESCONHECIDA (o
    chamador trata como falta de dado explicita, nunca como "criado no inicio da ultima pagina")."""
    cursor: Optional[str] = before_signature
    oldest_ok: Optional[int] = None
    seen = 0
    for _ in range(max_pages):
        rows = rpc.signatures(mint, before=cursor, limit=SIGNATURES_PAGE_SIZE)
        if not rows:
            return oldest_ok, seen, True
        seen += len(rows)
        for row in rows:                       # do mais novo para o mais velho
            if row.get("err") is None and row.get("blockTime") is not None:
                oldest_ok = int(row["blockTime"])
        if len(rows) < SIGNATURES_PAGE_SIZE:
            return oldest_ok, seen, True
        cursor = rows[-1]["signature"]
    return None, seen, False


@dataclass
class AccountOrigin:
    address: str
    anchor_time: int
    signatures_seen: int
    complete: bool
    first: Optional[TxSummary]
    error: str = ""


def account_origin(rpc: SolanaRpc, address: str, anchor_time: int, max_pages: int = 300) -> AccountOrigin:
    """Primeira transacao de uma conta (token ou pool), paginando para tras de uma ancora em `anchor_time`."""
    try:
        anchor, _slot, _bt = anchor_at_or_after(rpc, anchor_time)
        row, seen, complete = oldest_signature(rpc, address, anchor, max_pages=max_pages)
        if row is None:
            return AccountOrigin(address, anchor_time, seen, complete, None, "nenhuma assinatura antes da ancora")
        first = summarize_tx(row["signature"], rpc.transaction(row["signature"]))
        return AccountOrigin(address, anchor_time, seen, complete, first)
    except (RpcError, RuntimeError) as exc:
        return AccountOrigin(address, anchor_time, 0, False, None, f"{type(exc).__name__}: {exc}")


def to_jsonable(origin: AccountOrigin) -> dict[str, Any]:
    first = origin.first
    return {
        "address": origin.address,
        "anchor_time": origin.anchor_time,
        "signatures_seen": origin.signatures_seen,
        "complete": origin.complete,
        "error": origin.error,
        "first": None
        if first is None
        else {
            "signature": first.signature,
            "block_time": first.block_time,
            "slot": first.slot,
            "ok": first.ok,
            "signer": first.signer,
            "launchpad": first.launchpad,
            "programs": [PROGRAMS.get(p, p) for p in first.programs],
            "instructions": first.describe(),
        },
    }
