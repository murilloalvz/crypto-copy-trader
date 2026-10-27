"""PEDIDO 2026-10-27 (H8, PLANO_ANALISE_PREREGISTRADO.md): lista FIXA e IMUTAVEL de carteiras "pro"
fornecida pelo operador (signals_mvp/dados/carteiras_pro_papodefi.json) -- NUNCA baixada da internet,
nunca contem chave privada (so endereco publico/trackedWalletAddress). Valida (JSON, cada endereco
decodifica de base58 para 32 bytes, deduplica), trava sha256 + `lista_versao` em `meta` na 1a
validacao (mudar o arquivo depois disso e uma LISTA NOVA -- `LISTA_VERSAO_ATUAL` incrementada --
nunca uma edicao silenciosa do mesmo arquivo). `alertsOn`/`emoji` sao ignorados (so
trackedWalletAddress/name importam aqui).

Agrupa por PESSOA (heuristica deterministica, `grupo_de` -- ver INTERPRETACOES.md para a
justificativa e exemplos) porque varias carteiras da lista sao da MESMA pessoa (dani1-6, aloh1-9,
etc.) -- qualquer hipotese futura baseada nesta lista (H8 e qualquer H9 derivada) precisa reportar
`n_pessoas_pro` (grupos distintos) ALEM de `n_carteiras_pro` (enderecos distintos), nunca so o 2o,
que infla a contagem real de "quantas pessoas distintas" estao presentes.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LISTA_PATH = Path(__file__).resolve().parents[1] / "dados" / "carteiras_pro_papodefi.json"
GRUPOS_CSV_PATH = Path(__file__).resolve().parents[1] / "dados" / "carteiras_grupos.csv"

META_KEY_SHA256 = "carteiras_pro_sha256"
META_KEY_VERSAO = "carteiras_pro_versao"
META_KEY_N_CARTEIRAS = "carteiras_pro_n_carteiras"
META_KEY_N_PESSOAS = "carteiras_pro_n_pessoas"
META_KEY_GRUPOS_SHA256 = "carteiras_grupos_sha256"
LISTA_VERSAO_ATUAL = 1

_ALFABETO_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
# heuristica de agrupamento (determinada, sem IA/fuzzy matching -- mesma ordem sempre):
# 1. minusculas; 2. remove estas palavras (substring, em qualquer posicao -- cobre tanto "gake side"
# quanto "CupMain" concatenado); 3. remove sufixo numerico final (_N ou digito simples, com ou sem
# separador); 4. remove QUALQUER caractere que nao seja letra/digito (espaco/underscore/pontuacao
# remanescente) -- assim "jack duval" e "jackduval_2" caem no MESMO grupo.
_PALAVRAS_REMOVIVEIS = ("side", "main", "fomo", "new", "multi", "wallet")


class ListaAlteradaError(RuntimeError):
    """O arquivo da lista de carteiras (ou o CSV de grupos) mudou depois de registrado -- a lista
    e IMUTAVEL; uma lista nova precisa de `LISTA_VERSAO_ATUAL` incrementada, nunca uma edicao
    silenciosa do mesmo arquivo/registro."""


def base58_decode(texto: str) -> bytes:
    """Decodificador base58 puro (so stdlib, sem dependencia nova -- mesmo alfabeto do Bitcoin/
    Solana, 58 caracteres sem 0/O/I/l). Levanta ValueError se `texto` tiver qualquer caractere fora
    do alfabeto (`str.index` -- comportamento padrao, nunca silencioso)."""
    num = 0
    for char in texto:
        num = num * 58 + _ALFABETO_B58.index(char)
    corpo = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    zeros = len(texto) - len(texto.lstrip("1"))  # '1' em base58 = byte 0x00 (zero a esquerda)
    return b"\x00" * zeros + corpo


@dataclass(frozen=True)
class EntradaInvalida:
    trackedWalletAddress: str
    name: str
    motivo: str


@dataclass(frozen=True)
class ValidacaoLista:
    arquivo: Path
    sha256: str
    n_entradas: int
    n_validas: int
    n_unicas: int
    invalidas: list[EntradaInvalida] = field(default_factory=list)
    duplicadas: list[str] = field(default_factory=list)      # enderecos que apareceram mais de 1x
    enderecos_unicos: list[str] = field(default_factory=list)


def carregar_entradas(path: Path = LISTA_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def validar_lista(path: Path = LISTA_PATH) -> ValidacaoLista:
    """JSON valido (o `json.loads` abaixo levanta se nao for); cada endereco decodifica de base58
    para EXATAMENTE 32 bytes (pubkey Solana); deduplica por endereco. `alertsOn`/`emoji` nunca lidos
    aqui (ignorados pelo pedido)."""
    texto = path.read_text(encoding="utf-8")
    sha = hashlib.sha256(texto.encode("utf-8")).hexdigest()
    entradas = json.loads(texto)
    vistos: set[str] = set()
    invalidas: list[EntradaInvalida] = []
    duplicadas: list[str] = []
    unicos: list[str] = []
    for item in entradas:
        endereco = item.get("trackedWalletAddress", "")
        nome = item.get("name", "")
        try:
            decodificado = base58_decode(endereco)
        except ValueError:
            invalidas.append(EntradaInvalida(endereco, nome, "caractere fora do alfabeto base58"))
            continue
        if len(decodificado) != 32:
            invalidas.append(EntradaInvalida(
                endereco, nome, f"decodifica para {len(decodificado)} bytes (esperado 32)"))
            continue
        if endereco in vistos:
            duplicadas.append(endereco)
            continue
        vistos.add(endereco)
        unicos.append(endereco)
    return ValidacaoLista(
        arquivo=path, sha256=sha, n_entradas=len(entradas), n_validas=len(entradas) - len(invalidas),
        n_unicas=len(unicos), invalidas=invalidas, duplicadas=duplicadas, enderecos_unicos=unicos,
    )


def grupo_de(nome: str) -> str:
    s = nome.lower()
    for palavra in _PALAVRAS_REMOVIVEIS:
        s = s.replace(palavra, "")
    s = re.sub(r"[\s_]*\d+\s*$", "", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s or re.sub(r"[^a-z0-9]", "", nome.lower())


def gerar_grupos(path: Path = LISTA_PATH) -> list[tuple[str, str, str]]:
    """[(endereco, nome, grupo), ...] -- 1 linha por endereco VALIDO e UNICO (mesmo filtro de
    `validar_lista`, reaplicado aqui a partir do arquivo para nao depender de estado compartilhado)."""
    entradas = carregar_entradas(path)
    vistos: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for item in entradas:
        endereco = item.get("trackedWalletAddress", "")
        nome = item.get("name", "")
        try:
            if len(base58_decode(endereco)) != 32:
                continue
        except ValueError:
            continue
        if endereco in vistos:
            continue
        vistos.add(endereco)
        out.append((endereco, nome, grupo_de(nome)))
    return out


def escrever_csv_grupos(linhas: list[tuple[str, str, str]], dest: Path = GRUPOS_CSV_PATH) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["endereco", "nome", "grupo"])
        for linha in linhas:
            writer.writerow(linha)
    return hashlib.sha256(dest.read_bytes()).hexdigest()


def contar_pessoas(linhas: list[tuple[str, str, str]]) -> int:
    return len({grupo for _end, _nome, grupo in linhas})


def grupos_com_mais_de_uma_carteira(linhas: list[tuple[str, str, str]]) -> list[tuple[str, int]]:
    contagem: dict[str, int] = {}
    for _end, _nome, grupo in linhas:
        contagem[grupo] = contagem.get(grupo, 0) + 1
    return sorted(((g, n) for g, n in contagem.items() if n > 1), key=lambda t: (-t[1], t[0]))


def garantir_lista_registrada(storage: Any, path: Path = LISTA_PATH,
                              grupos_csv: Path = GRUPOS_CSV_PATH) -> ValidacaoLista:
    """1a chamada valida, gera `carteiras_grupos.csv` e registra sha256/versao/contagens em `meta`;
    chamadas seguintes recusam (`ListaAlteradaError`) se o arquivo da lista OU do CSV de grupos
    mudou depois do registro -- lista IMUTAVEL (mudar = nova versao, decisao do operador)."""
    val = validar_lista(path)
    registrado = storage.get_meta(META_KEY_SHA256)
    if registrado is None:
        linhas = gerar_grupos(path)
        sha_csv = escrever_csv_grupos(linhas, grupos_csv)
        storage.set_meta(META_KEY_SHA256, val.sha256)
        storage.set_meta(META_KEY_VERSAO, str(LISTA_VERSAO_ATUAL))
        storage.set_meta(META_KEY_N_CARTEIRAS, str(val.n_unicas))
        storage.set_meta(META_KEY_N_PESSOAS, str(contar_pessoas(linhas)))
        storage.set_meta(META_KEY_GRUPOS_SHA256, sha_csv)
        return val
    if registrado != val.sha256:
        raise ListaAlteradaError(
            f"{path} mudou depois de registrado (registrado {registrado}, atual {val.sha256}) -- "
            "a lista de carteiras pro e IMUTAVEL. Uma lista nova precisa de lista_versao incrementada."
        )
    if grupos_csv.exists():
        sha_csv_atual = hashlib.sha256(grupos_csv.read_bytes()).hexdigest()
        sha_csv_registrado = storage.get_meta(META_KEY_GRUPOS_SHA256)
        if sha_csv_registrado is not None and sha_csv_registrado != sha_csv_atual:
            raise ListaAlteradaError(
                f"{grupos_csv} mudou depois de registrado -- o agrupamento e IMUTAVEL junto da lista."
            )
    return val
