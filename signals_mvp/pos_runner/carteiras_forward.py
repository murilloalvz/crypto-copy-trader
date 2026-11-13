"""PEDIDO 2026-11-10 (autorizado, rodada 15, Parte 4): trava por hash do pre-registro
`docs/pos-runner-v3/PREREGISTRO_CARTEIRAS_FORWARD_2026-11-10.md` -- MESMO padrao de
`saida_fiel.garantir_saida_fiel_registrada`/`horizonte_fixo.garantir_emenda_registrada`: a 1a chamada
registra o hash atual em `meta`; chamadas seguintes recusam (`PreregistroAlteradoError`) se o texto
em disco mudou depois do registro -- pre-registro IMUTAVEL, mudar = emenda datada nova."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..util import short_hash

PREREGISTRO_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "pos-runner-v3" / "PREREGISTRO_CARTEIRAS_FORWARD_2026-11-10.md"
)
META_KEY_HASH = "carteiras_forward_preregistro_hash"


class PreregistroAlteradoError(RuntimeError):
    """O texto do pre-registro em disco nao bate com o hash registrado -- recusa, nunca reescreve
    em silencio."""


def hash_do_preregistro(path: Path = PREREGISTRO_PATH) -> str:
    return short_hash(path.read_text(encoding="utf-8"))


def garantir_carteiras_forward_registrada(storage: Any, path: Path = PREREGISTRO_PATH) -> str:
    atual = hash_do_preregistro(path)
    registrado = storage.get_meta(META_KEY_HASH)
    if registrado is None:
        storage.set_meta(META_KEY_HASH, atual)
        return atual
    if registrado != atual:
        raise PreregistroAlteradoError(
            f"docs/pos-runner-v3/PREREGISTRO_CARTEIRAS_FORWARD_2026-11-10.md mudou depois de "
            f"registrado (registrado {registrado}, atual {atual}) -- abra uma nova emenda datada, "
            "nunca reescreva o pre-registro em silencio."
        )
    return atual
