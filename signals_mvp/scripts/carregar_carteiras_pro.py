"""PEDIDO 2026-10-27 (H8): valida a lista FIXA de carteiras "pro" (signals_mvp/dados/
carteiras_pro_papodefi.json, fornecida pelo operador -- NUNCA baixada da internet), gera
`carteiras_grupos.csv` (agrupamento por pessoa) e registra sha256+lista_versao+contagens em `meta`
na 1a execucao. Lista IMUTAVEL: execucoes seguintes so CONFEREM (recusam se o arquivo mudou --
`carteiras_pro.ListaAlteradaError`), nunca re-registram por conta propria.

Uso (na VM, dentro do diretorio do bot):
    python -m signals_mvp.scripts.carregar_carteiras_pro --db dados/estado.sqlite
"""

from __future__ import annotations

import argparse
import dataclasses
from pathlib import Path
from typing import Optional

from ..config import make_paths
from ..pos_runner import carteiras_pro as cp
from ..storage import Storage


def _abrir_storage_no_arquivo(db_path: Path) -> Storage:
    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    return Storage(paths)


def executar(db_path: Path) -> str:
    storage = _abrir_storage_no_arquivo(db_path)
    try:
        val = cp.garantir_lista_registrada(storage)
        linhas = cp.gerar_grupos()
        n_pessoas = cp.contar_pessoas(linhas)
        grupos_multi = cp.grupos_com_mais_de_uma_carteira(linhas)
        linhas_saida = [
            f"arquivo: {val.arquivo}",
            f"sha256: {val.sha256}",
            f"lista_versao: {storage.get_meta(cp.META_KEY_VERSAO)}",
            f"entradas no JSON: {val.n_entradas} | validas: {val.n_validas} | unicas: {val.n_unicas}",
        ]
        if val.n_unicas != 121:
            linhas_saida.append(f"⚠️ esperado ~121, obtido {val.n_unicas} -- diferenca de {val.n_unicas - 121:+d}")
        if val.invalidas:
            linhas_saida.append(f"invalidas ({len(val.invalidas)}): " +
                                "; ".join(f"{i.trackedWalletAddress} ({i.name}): {i.motivo}" for i in val.invalidas))
        if val.duplicadas:
            linhas_saida.append(f"duplicadas ({len(val.duplicadas)}): {', '.join(val.duplicadas)}")
        linhas_saida.append(f"carteiras_grupos.csv: {cp.GRUPOS_CSV_PATH} (sha256 {storage.get_meta(cp.META_KEY_GRUPOS_SHA256)})")
        linhas_saida.append(f"n_carteiras_pro: {val.n_unicas} | n_pessoas_pro: {n_pessoas}")
        linhas_saida.append(f"grupos com mais de 1 carteira ({len(grupos_multi)}):")
        for grupo, n in grupos_multi:
            linhas_saida.append(f"  {grupo}: {n}")
        return "\n".join(linhas_saida)
    finally:
        storage.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Valida/registra a lista de carteiras pro (H8).")
    parser.add_argument("--db", required=True, help="caminho do estado.sqlite (produção ou cópia)")
    args = parser.parse_args(argv)
    print(executar(Path(args.db)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
