"""Narrativa: casamento de nome/ticker/descricao com as palavras-chave do meta.txt.

meta.txt (editado pelo operador):
    ROTULO: palavra1, palavra2
    palavra_solta            # grupo com o proprio nome
A versao (`versao_meta`) e o hash do conteudo normalizado: comentario/espaco nao muda a versao.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .config import read_text_robust
from .util import short_hash

_CAMEL_1 = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_CAMEL_2 = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_words(text: str) -> list[str]:
    """'DogeAI Agent' -> ['doge', 'ai', 'agent'] (separa camelCase, tira acento, minusculas)."""
    if not text:
        return []
    text = _strip_accents(text)
    text = _CAMEL_2.sub(" ", _CAMEL_1.sub(" ", text))
    return [w.casefold() for w in _WORD.findall(text)]


def _is_cjk(text: str) -> bool:
    return any("⺀" <= ch <= "鿿" or "가" <= ch <= "힯" or "぀" <= ch <= "ヿ" for ch in text)


@dataclass(frozen=True)
class MetaSet:
    groups: dict  # rotulo (maiusculo) -> tupla de palavras-chave normalizadas (cada uma = tupla de palavras)
    version: str

    @property
    def empty(self) -> bool:
        return not self.groups


EMPTY_META = MetaSet(groups={}, version="vazio")


def parse_meta(text: str) -> MetaSet:
    groups: dict[str, list[tuple[str, ...]]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            label, _, rest = line.partition(":")
            label = label.strip().upper()
            keywords = [k for k in rest.split(",")]
        else:
            label = line.strip().upper()
            keywords = [line]
        parsed = []
        for keyword in keywords:
            words = tuple(normalize_words(keyword))
            if words:
                parsed.append(words)
        if label and parsed:
            bucket = groups.setdefault(label, [])
            for kw in parsed:
                if kw not in bucket:
                    bucket.append(kw)
    frozen = {label: tuple(sorted(kws)) for label, kws in sorted(groups.items())}
    if not frozen:
        return EMPTY_META
    version = short_hash({label: [" ".join(k) for k in kws] for label, kws in frozen.items()})
    return MetaSet(groups=frozen, version=version)


def load_meta(path: Path) -> MetaSet:
    """Arquivo ausente => meta vazio (o score fica sem narrativa), nunca erro."""
    try:
        return parse_meta(read_text_robust(path))
    except OSError:
        return EMPTY_META


@dataclass
class NarrativeMatch:
    name_hits: list = field(default_factory=list)   # [(rotulo, palavra)] no nome/ticker
    desc_hits: list = field(default_factory=list)   # [(rotulo, palavra)] so na descricao
    description_known: bool = False

    @property
    def labels(self) -> list[str]:
        seen: list[str] = []
        for label, _ in self.name_hits + self.desc_hits:
            if label not in seen:
                seen.append(label)
        return seen

    @property
    def label_text(self) -> str:
        return "+".join(self.labels)


def _keyword_in(words: list[str], compact: str, keyword: tuple[str, ...], substring_min_len: int) -> bool:
    joined = "".join(keyword)
    if len(keyword) > 1:  # expressao: sequencia contigua de palavras
        n = len(keyword)
        return any(tuple(words[i : i + n]) == keyword for i in range(len(words) - n + 1))
    word = keyword[0]
    if word in words:
        return True
    if _is_cjk(word):
        return word in compact
    return len(joined) >= substring_min_len and joined in compact


def match_meta(meta: MetaSet, name: str, symbol: str, description: str, substring_min_len: int = 4) -> NarrativeMatch:
    """Casa o meta com nome, ticker e descricao. Nome e ticker sao avaliados SEPARADOS: juntar os dois
    poderia fabricar uma expressao que nao existe em nenhum (nome 'Good' + ticker 'Boy' => 'good boy')."""
    result = NarrativeMatch(description_known=bool(description and description.strip()))
    if meta.empty:
        return result
    name_fields = []
    for text in (name, symbol):
        words = normalize_words(text)
        if words:
            name_fields.append((words, "".join(words)))
    desc_words = normalize_words(description or "")
    desc_compact = "".join(desc_words)
    for label, keywords in meta.groups.items():
        for keyword in keywords:
            label_kw = (label, " ".join(keyword))
            if any(_keyword_in(words, compact, keyword, substring_min_len) for words, compact in name_fields):
                result.name_hits.append(label_kw)
            elif desc_words and _keyword_in(desc_words, desc_compact, keyword, substring_min_len):
                result.desc_hits.append(label_kw)
    return result
