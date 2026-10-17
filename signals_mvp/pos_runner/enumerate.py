"""Enumeracao SEM VIES das graduacoes dos 3 launchpads numa janela de calendario (Parte A).

Metodo (ancora sem Helius, copiado do H2 — ver `solana_rpc.py`): para cada conta-chave do launchpad, acha uma
assinatura ancora no FIM da janela e pagina `getSignaturesForAddress` para tras ate passar do INICIO. Cada
transacao bem-sucedida da janela e confirmada pelos logs (programa + instrucao de migracao) e os enderecos
(mint, cotacao, pool) saem das posicoes de conta da instrucao de migracao — conferidas nos 5 exemplos:

| launchpad | conta-chave (so aparece em migracoes) | instrucao | posicoes (mint, cotacao, pool) |
|---|---|---|---|
| pump.fun | autoridade de migracao `39azUYF...` (a mesma do H2) | `Migrate`/`MigrateV2` | 2, 3, 10 |
| Raydium LaunchLab | migrador `RAYpQbFN...` (53/60 tx = `MigrateToCpswap`) | `MigrateToCpswap` | 1, 2, 5 |
| Meteora DBC | config DAMM v2 `A8gMrEPJ...` (pool_creator_authority = autoridade da DBC) | `MigrationDammV2` | 13, 14, 4 |

Limitacoes declaradas: a DBC tem outras configs de DAMM v2 (uma por faixa de fee) e a migracao para DAMM v1;
a LaunchLab pode migrar para o AMM v4 (`MigrateToAmm`). Contas-chave a mais entram em `extra_accounts` depois
de conferidas; o relatorio de cobertura diz quais foram usadas. Graduacao que nao bate com o layout conhecido
fica registrada como `nao_resolvida` (nunca descartada em silencio).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional

from .lineage import summarize_tx, top_level_instruction_names
from .solana_rpc import SIGNATURES_PAGE_SIZE, RpcError, SolanaRpc, anchor_at_or_after


@dataclass(frozen=True)
class LaunchpadSpec:
    name: str
    program: str
    accounts: tuple[str, ...]
    layouts: dict[str, tuple[int, int, int]]     # instrucao -> (idx mint, idx cotacao, idx pool) na instrucao do launchpad
    # EMENDA 2026-10-16 (achado real: o indice fixo de pool nao e estavel entre variantes de instrucao -- "Migrate"
    # legado (27/25 contas) e "MigrateV2" (29 contas) tem o pool em posicoes DIFERENTES, 9 ou 10, mas SEMPRE
    # imediatamente depois do programa da AMM de destino na lista de contas). Quando setado, o pool vem de
    # `accounts[accounts.index(pool_after_program) + 1]` em vez do indice fixo de `layouts` -- mais robusto a
    # variantes de instrucao ainda nao vistas, nunca um palpite de posicao.
    pool_after_program: Optional[str] = None


LAUNCHPADS: dict[str, LaunchpadSpec] = {
    "pumpfun": LaunchpadSpec(
        "pumpfun", "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
        ("39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg",),
        {"Migrate": (2, 3, 10), "MigrateV2": (2, 3, 10)},
        pool_after_program="pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
    ),
    "raydium_launchlab": LaunchpadSpec(
        "raydium_launchlab", "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",
        ("RAYpQbFNq9i3mu6cKpTKKRwwHFDeK5AuZz8xvxUrCgw",),
        {"MigrateToCpswap": (1, 2, 5)},
    ),
    "meteora_dbc": LaunchpadSpec(
        "meteora_dbc", "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN",
        ("A8gMrEPJkacWkcb3DGwtJwTe16HktSEfvwtuDh2MCtck",),
        {"MigrationDammV2": (13, 14, 4)},
    ),
}


@dataclass
class Graduation:
    launchpad: str
    signature: str
    block_time: int
    slot: Optional[int]
    instruction: str
    mint: Optional[str]
    quote_mint: Optional[str]
    pool: Optional[str]
    status: str = "ok"            # ok | nao_resolvida


@dataclass
class WindowResult:
    launchpad: str
    window_start: int
    window_end: int
    graduations: list[Graduation] = field(default_factory=list)
    signatures_seen: int = 0
    tx_fetched: int = 0
    skipped_err: int = 0
    not_migration: int = 0
    nao_resolvida: int = 0   # contagem EXPLICITA de graduacoes rejeitadas pelo filtro defensivo; nunca pool morto
    accounts: tuple[str, ...] = ()
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["graduations"] = [asdict(g) for g in self.graduations]
        return d


def _launchpad_instruction(tx: dict, spec: LaunchpadSpec) -> tuple[Optional[str], Optional[list[str]]]:
    """(nome da instrucao de migracao, contas da instrucao de nivel 1 do programa do launchpad). Casa a
    instrucao certa pelo NOME logado (`top_level_instruction_names`), nunca so pelo `programId` -- uma
    transacao pode chamar o MESMO programa em mais de uma instrucao de nivel 1 (ex.: comprar e migrar no
    mesmo envio); pegar "a 1a que casa o programId" pode pegar a instrucao ERRADA e ler contas de outro
    layout (achado real em producao: DBC com Init+Swap+Migracao, pump.fun com Buy+Migracao na mesma tx)."""
    summary = summarize_tx("", tx)
    if summary is None or not summary.ok:
        return None, None
    names = [ix for prog, ix in summary.instructions if prog == spec.program and ix in spec.layouts]
    if not names:
        return None, None
    top_names = top_level_instruction_names(tx)
    top_instrs = ((tx.get("transaction") or {}).get("message") or {}).get("instructions") or []
    for i, ix in enumerate(top_instrs):
        name = top_names[i] if i < len(top_names) else None
        if ix.get("programId") == spec.program and name in spec.layouts and isinstance(ix.get("accounts"), list):
            return name, ix["accounts"]
    # migracao chamada por outro programa (CPI): procura nas instrucoes internas (mesma limitacao de sempre:
    # casa so por tamanho de contas, nao por nome -- nao foi achado nenhum caso real do bug aqui ainda)
    need = max(spec.layouts[names[0]]) + 1
    for inner in ((tx.get("meta") or {}).get("innerInstructions") or []):
        for ix in inner.get("instructions") or []:
            if ix.get("programId") == spec.program and isinstance(ix.get("accounts"), list) and len(ix["accounts"]) >= need:
                return names[0], ix["accounts"]
    return names[0], None


# EMENDA 2026-10-16 (filtro defensivo, pos achado em producao de pool/mint lixo): enderecos nativos/de sistema
# nunca sao o mint ou o pool de uma graduacao real (podem ser a COTACAO legitimamente, ex. SOL/USDC/USDT --
# por isso nao entram aqui). Pega qualquer resto de leitura errada que o casamento por nome nao evitou.
KNOWN_NATIVE_OR_PROGRAM = frozenset({
    "So11111111111111111111111111111111111111112",   # SOL (mint nativo)
    "11111111111111111111111111111111",               # System Program
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",     # SPL Token Program
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",     # Token-2022 Program
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",    # Associated Token Program
    "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s",     # Metadata Program
    "Sysvar1nstructions1111111111111111111111111",     # Sysvar Instructions
    "SysvarRent111111111111111111111111111111111",     # Rent Sysvar
    "ComputeBudget111111111111111111111111111111",     # Compute Budget Program
})


def _mint_seen_in_balances(tx: dict, mint: Optional[str]) -> bool:
    """Checagem de consistencia INDEPENDENTE do layout de contas (EMENDA 2026-10-16, "falhar fechado"): o mint
    extraido precisa aparecer em `postTokenBalances`/`preTokenBalances` (saldo de token que a tx realmente
    moveu) -- sem chamada de RPC nova (os dados ja vieram no `getTransaction`). Nunca confia so na posicao fixa
    de conta; se o mint nao teve NENHUM saldo tocado nesta tx, ele nao e o mint real da migracao."""
    if not mint:
        return False
    meta = tx.get("meta") or {}
    seen = {b.get("mint") for b in (meta.get("postTokenBalances") or [])}
    seen |= {b.get("mint") for b in (meta.get("preTokenBalances") or [])}
    return mint in seen


def resolve_graduation(tx: dict, spec: LaunchpadSpec, signature: str) -> Optional[Graduation]:
    name, accounts = _launchpad_instruction(tx, spec)
    if name is None:
        return None
    idx = spec.layouts[name]
    g = Graduation(spec.name, signature, int(tx.get("blockTime") or 0), tx.get("slot"), name, None, None, None)
    if accounts is None or max(idx[:2]) >= len(accounts):
        g.status = "nao_resolvida"
        return g
    pool = accounts[idx[2]] if idx[2] < len(accounts) else None
    if spec.pool_after_program:
        # posicao fixa de pool NAO e estavel entre variantes de instrucao (achado real: "Migrate" legado tem o
        # pool numa posicao diferente de "MigrateV2") -- acha dinamicamente pelo programa da AMM de destino,
        # sempre o proximo da lista de contas, nunca um indice fixo.
        try:
            pool = accounts[accounts.index(spec.pool_after_program) + 1]
        except (ValueError, IndexError):
            g.status = "nao_resolvida"
            return g
    if pool is None:
        g.status = "nao_resolvida"
        return g
    g.mint, g.quote_mint, g.pool = accounts[idx[0]], accounts[idx[1]], pool
    if (g.pool in KNOWN_NATIVE_OR_PROGRAM or g.mint in KNOWN_NATIVE_OR_PROGRAM
            or g.pool == g.mint or g.pool == g.quote_mint or not _mint_seen_in_balances(tx, g.mint)):
        g.status, g.mint, g.quote_mint, g.pool = "nao_resolvida", None, None, None
        return g
    return g


def enumerate_window(
    rpc: SolanaRpc,
    spec: LaunchpadSpec,
    window_start: int,
    window_end: int,
    extra_accounts: Iterable[str] = (),
    max_pages: int = 200,
) -> WindowResult:
    accounts = tuple(spec.accounts) + tuple(extra_accounts)
    res = WindowResult(spec.name, window_start, window_end, accounts=accounts)
    try:
        anchor, _slot, _bt = anchor_at_or_after(rpc, window_end)
    except (RpcError, RuntimeError) as exc:
        res.error = f"ancora: {exc}"
        return res
    seen_sigs: set[str] = set()
    pools: set[str] = set()
    for account in accounts:
        before = anchor
        for _ in range(max_pages):
            try:
                rows = rpc.signatures(account, before=before, limit=SIGNATURES_PAGE_SIZE)
            except RpcError as exc:
                res.error = f"assinaturas {account[:8]}: {exc}"
                return res
            if not rows:
                break
            res.signatures_seen += len(rows)
            reached_start = False
            for row in rows:
                bt = row.get("blockTime")
                if bt is None:
                    continue
                if bt < window_start:
                    reached_start = True
                    break
                if bt >= window_end:
                    continue
                if row.get("err") is not None:
                    res.skipped_err += 1
                    continue
                sig = row["signature"]
                if sig in seen_sigs:
                    continue
                seen_sigs.add(sig)
                try:
                    tx = rpc.call("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])
                except RpcError as exc:
                    res.error = f"transacao {sig[:10]}: {exc}"
                    return res
                res.tx_fetched += 1
                grad = resolve_graduation(tx, spec, sig) if tx else None
                if grad is None:
                    res.not_migration += 1
                    continue
                if grad.status == "nao_resolvida":
                    res.nao_resolvida += 1
                if grad.pool and grad.pool in pools:
                    continue
                if grad.pool:
                    pools.add(grad.pool)
                res.graduations.append(grad)
            if reached_start or len(rows) < SIGNATURES_PAGE_SIZE:
                break
            before = rows[-1]["signature"]
        else:
            res.error = f"teto de paginas em {account[:8]}"
    if not res.error:
        try:
            _verify_pools_exist_on_chain(rpc, res)
        except RpcError as exc:
            res.error = f"verificacao de pool on-chain: {exc}"
            return res
    res.graduations.sort(key=lambda g: (g.block_time, g.signature))
    return res


# QuickNode no plano "discover" (free) recusa `getMultipleAccounts` com mais de 5 chaves (HTTP 413, codigo
# -32615) -- medido em produção 2026-10-17. 5 e conservador o bastante para qualquer plano/provedor.
GET_MULTIPLE_ACCOUNTS_BATCH = 5


def _verify_pools_exist_on_chain(rpc: SolanaRpc, res: WindowResult) -> None:
    """Checagem de consistencia INDEPENDENTE do layout de contas (EMENDA 2026-10-16/17, "falhar fechado"): todo
    pool resolvido precisa EXISTIR on-chain (`getAccountInfo`, em lote via `getMultipleAccounts` -- poucas
    chamadas extra por janela, nunca uma por graduacao). Pool que nao existe vira `nao_resolvida` (nunca pool
    morto: nunca entra em stage1/stage2/detector). Falha de rede nesta checagem NUNCA aceita a graduacao sem
    verificar (falhar fechado): sobe como `RpcError`, a janela inteira vira `erro` e e retomada depois, igual a
    qualquer outra falha de RPC nesta funcao."""
    ok = [g for g in res.graduations if g.status == "ok" and g.pool]
    if not ok:
        return
    for i in range(0, len(ok), GET_MULTIPLE_ACCOUNTS_BATCH):
        batch = ok[i:i + GET_MULTIPLE_ACCOUNTS_BATCH]
        values = rpc.call("getMultipleAccounts", [[g.pool for g in batch], {"encoding": "base64"}])
        accounts = (values or {}).get("value") or []
        for g, acc in zip(batch, accounts):
            if acc is None:
                g.status, g.mint, g.quote_mint, g.pool = "nao_resolvida", None, None, None
                res.nao_resolvida += 1


def validate_with_examples(rpc: SolanaRpc, examples: Iterable[Any], margin_s: int = 120) -> list[dict[str, Any]]:
    """Gate de sistema 1 da Parte A: a enumeracao precisa achar a graduacao de cada exemplo na janela dele."""
    out = []
    for ex in examples:
        spec = LAUNCHPADS[ex.launchpad]
        res = enumerate_window(rpc, spec, ex.grad_ts - margin_s, ex.grad_ts + margin_s)
        match = [g for g in res.graduations if g.pool == ex.pool and g.mint == ex.mint]
        out.append({
            "exemplo": ex.key,
            "launchpad": ex.launchpad,
            "achou": bool(match),
            "assinatura": match[0].signature if match else None,
            "instrucao": match[0].instruction if match else None,
            "cotacao": match[0].quote_mint if match else None,
            "graduacoes_na_janela": len(res.graduations),
            "assinaturas_vistas": res.signatures_seen,
            "erro": res.error,
        })
    return out
