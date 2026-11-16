"""RODADA 22 (2026-11-17, autorizada): derivacao de Program Derived Address (PDA) do Solana, SO
STDLIB (sha256 + aritmetica de inteiros -- nenhuma dependencia nova). Usado por
`chain_adapter.excluded_accounts` para computar a bonding-curve do pump.fun (RODADA 22, item 1:
nos 19 snapshots novos da Rodada 21, contas_excluidas_pool_curva=0 em todos e em 12/19 o 1o holder
era o proprio endereco do pool -- a exclusao so cobria o PROGRAMA do launchpad/AMM, nunca a conta
ESPECIFICA do pool/curva deste token).

Algoritmo (`create_program_address`/`find_program_address`) EXATAMENTE como o runtime do Solana
especifica: sha256(seeds... + program_id + b"ProgramDerivedAddress"); o resultado so e um PDA
valido se NAO for um ponto valido da curva Ed25519 (garantia do protocolo: PDA nunca pode ser uma
chave publica de verdade, pra nunca ser falsificavel por assinatura) -- senao incrementa o bump
seed (255 -> 0) e tenta de novo. `is_on_curve` usa a mesma checagem de decodificacao de ponto
comprimido Ed25519 (RFC 8032) que toda implementacao de referencia usa.

VALIDADO nesta sessao contra dado real (nunca so contra vetor de teste memorizado): computada a
Associated Token Account (`ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL`, seeds=[wallet, Token
Program, mint]) para um par (wallet, mint) observado agora via `getTokenAccountsByOwner` contra
api.mainnet-beta.solana.com -- o endereco computado bateu exatamente com o endereco real on-chain
(`22iBCoc79WvQvaGvAiPkVmBWfhYVWzdsvbPJRnhGzFNK`). RODADA 22, condicao 1 do operador: o MESMO
algoritmo tambem bateu, de novo contra dado real (`getTransaction`/jsonParsed), com a bonding-curve
de 4 mints pump.fun reais (seeds=['bonding-curve', mint], programa pump.fun) -- 1 deles Token-2022
(`create_v2`), descartando a hipotese de precisar de um seed 'bonding-curve-v2' separado -- ver
`test_solana_pda.BondingCurveSeedFixtureTests`."""

from __future__ import annotations

import hashlib

from .carteiras_pro import base58_decode

_ALFABETO_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# constantes do campo primo do Ed25519 (RFC 8032) -- sqrt(-1) mod p usado na checagem de ponto
# valido (p ≡ 5 mod 8, entao sqrt tem exatamente 2 candidatos; testa os 2).
_P = 2**255 - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


class PdaNaoEncontradoError(RuntimeError):
    """Nenhum bump seed (255..0) produziu um PDA valido -- nunca deveria acontecer na pratica
    (probabilidade ~2^-256 por bump), mas falha explicita em vez de devolver um endereco incerto."""


def base58_encode(dados: bytes) -> str:
    """Inverso de `carteiras_pro.base58_decode` -- mesmo alfabeto, pura stdlib."""
    zeros = len(dados) - len(dados.lstrip(b"\x00"))
    num = int.from_bytes(dados, "big")
    texto = ""
    while num > 0:
        num, resto = divmod(num, 58)
        texto = _ALFABETO_B58[resto] + texto
    return "1" * zeros + texto


def _esta_na_curva(ponto32: bytes) -> bool:
    """Decodificacao de ponto comprimido Ed25519 (RFC 8032): verdadeiro sse os 32 bytes
    representam um ponto valido da curva -- usado so pra decidir se um hash candidato PODE ser
    usado como chave publica de verdade (se sim, NUNCA e um PDA valido)."""
    if len(ponto32) != 32:
        return False
    y = int.from_bytes(ponto32, "little") & ((1 << 255) - 1)
    if y >= _P:
        return False
    u = (y * y - 1) % _P
    v = (_D * y * y + 1) % _P
    if v == 0:
        return False
    xx = (u * pow(v, _P - 2, _P)) % _P
    x0 = pow(xx, (_P + 3) // 8, _P)
    if (x0 * x0 - xx) % _P == 0:
        return True
    x1 = (x0 * _SQRT_M1) % _P
    return (x1 * x1 - xx) % _P == 0


def create_program_address(seeds: list[bytes], program_id: bytes) -> bytes:
    """Levanta `ValueError` se o hash resultante for um ponto valido da curva (seeds/bump
    incorretos para um PDA) -- MESMA semantica do `create_program_address` do runtime Solana."""
    buf = b"".join(seeds) + program_id + b"ProgramDerivedAddress"
    h = hashlib.sha256(buf).digest()
    if _esta_na_curva(h):
        raise ValueError("resultado esta na curva -- nao e um PDA valido")
    return h


def find_program_address(seeds: list[bytes], program_id_b58: str) -> str:
    """PDA determinístico para `seeds`/`program_id_b58` -- devolve o ENDERECO (base58), MESMA
    convencao do `findProgramAddressSync` dos SDKs oficiais (bump seed de 255 a 0, primeiro que
    produzir um resultado fora da curva)."""
    program_id = base58_decode(program_id_b58)
    for bump in range(255, -1, -1):
        try:
            endereco = create_program_address(seeds + [bytes([bump])], program_id)
        except ValueError:
            continue
        return base58_encode(endereco)
    raise PdaNaoEncontradoError(f"nenhum PDA valido para seeds={seeds!r} program={program_id_b58}")
