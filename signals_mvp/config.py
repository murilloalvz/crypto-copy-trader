"""Carga, validacao e versionamento (hash) do config.yaml.

Regra de disciplina de dados: `versao_config` = hash do conteudo EFETIVO do YAML
(comentarios e espacos nao contam). Mudou numero/lista/chave => nova versao.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .util import get_path, short_hash

PACKAGE_DIR = Path(__file__).resolve().parent


class ConfigError(Exception):
    """Config invalida. A mensagem lista todos os problemas de uma vez."""


# ---------------------------------------------------------------------------
# caminhos
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Paths:
    base: Path
    config: Path
    meta: Path
    env: Path
    dados: Path
    logs: Path
    db: Path
    sinais_csv: Path
    descartados_csv: Path
    trades_csv: Path
    detalhe_csv: Path
    pos_runner_csv: Path
    pos_runner_detalhe_csv: Path
    pos_runner_banca_csv: Path
    pos_runner_v1_csv: Path
    pos_runner_v1_filtrados_csv: Path
    heartbeat: Path
    stop_flag: Path
    pid_file: Path
    config_versions: Path


def make_paths(base: Path | None = None) -> Paths:
    """Todos os arquivos do bot ficam dentro da pasta signals_mvp/ (ou de `base`, nos testes)."""
    if base is None:
        env_home = os.environ.get("SIGNALS_MVP_HOME")  # usado pelo supervisor/testes para apontar outra pasta
        base = Path(env_home) if env_home else PACKAGE_DIR
    root = Path(base)
    dados = root / "dados"
    return Paths(
        base=root,
        config=root / "config.yaml",
        meta=root / "meta.txt",
        env=root / ".env",
        dados=dados,
        logs=root / "logs",
        db=dados / "estado.sqlite",
        sinais_csv=dados / "sinais.csv",
        descartados_csv=dados / "descartados.csv",
        trades_csv=dados / "trades_operador.csv",
        detalhe_csv=dados / "sinais_detalhe.csv",
        pos_runner_csv=dados / "pos_runner.csv",
        pos_runner_detalhe_csv=dados / "pos_runner_detalhe.csv",
        pos_runner_banca_csv=dados / "pos_runner_banca.csv",
        pos_runner_v1_csv=dados / "pos_runner_v1.csv",
        pos_runner_v1_filtrados_csv=dados / "pos_runner_v1_filtrados.csv",
        heartbeat=dados / "heartbeat.json",
        stop_flag=dados / "PARAR",
        pid_file=dados / "supervisor.pid",
        config_versions=dados / "config_versoes",
    )


# ---------------------------------------------------------------------------
# leitura robusta de texto (Bloco de Notas antigo salva em ANSI)
# ---------------------------------------------------------------------------


def read_text_robust(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# objeto Config
# ---------------------------------------------------------------------------


@dataclass
class Config:
    raw: dict
    version: str
    path: Path | None = None

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, dotted: str, default: Any = None) -> Any:
        return get_path(self.raw, dotted, default)

    def chain(self, name: str) -> dict:
        return self.raw["chains"][name]

    def enabled_chains(self) -> dict[str, dict]:
        return {name: c for name, c in self.raw["chains"].items() if c.get("ligada")}

    def sem_dado_acao(self, chain: str) -> str:
        """Politica para 'GoPlus sem dado': a da chain, se preenchida, senao a global."""
        return self.chain(chain).get("sem_dado_acao") or self.raw["seguranca"]["sem_dado_acao"]


def load_config(path: Path) -> Config:
    try:
        text = read_text_robust(path)
    except OSError as exc:
        raise ConfigError(f"nao consegui ler {path}: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML invalido em {path}: {exc}") from exc
    return build_config(raw, path)


def build_config(raw: Any, path: Path | None = None) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("o config.yaml precisa ser um mapa (chave: valor) na raiz")
    errors = validate(raw)
    if errors:
        raise ConfigError("config.yaml invalido:\n  - " + "\n  - ".join(errors))
    return Config(raw=raw, version=short_hash(raw), path=path)


# ---------------------------------------------------------------------------
# validacao
# ---------------------------------------------------------------------------

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_LINK_KEYS = {"pool": "P", "token": "T", "gmgn_slug": "G", "dexscreener_slug": "D"}


_MISSING = object()


class _Checker:
    """Acumula erros em vez de parar no primeiro (o operador corrige tudo de uma vez)."""

    def __init__(self, data: Mapping[str, Any]):
        self.data = data
        self.errors: list[str] = []

    def _value(self, dotted: str) -> Any:
        value = get_path(self.data, dotted, _MISSING)
        if value is _MISSING:
            self.errors.append(f"falta a chave `{dotted}`")
        return value

    def num(self, dotted: str, low: float | None = None, high: float | None = None, integer: bool = False) -> float | None:
        value = self._value(dotted)
        if value is _MISSING:
            return None
        valid_type = isinstance(value, (int, float)) and not isinstance(value, bool)
        if not valid_type or (integer and not isinstance(value, int)):
            self.errors.append(f"`{dotted}` precisa ser {'inteiro' if integer else 'numero'} (veio {value!r})")
            return None
        if low is not None and value < low:
            self.errors.append(f"`{dotted}` precisa ser >= {low} (veio {value})")
        if high is not None and value > high:
            self.errors.append(f"`{dotted}` precisa ser <= {high} (veio {value})")
        return float(value)

    def text(self, dotted: str, choices: tuple[str, ...] | None = None, allow_empty: bool = False) -> str | None:
        value = self._value(dotted)
        if value is _MISSING:
            return None
        if not isinstance(value, str) or (not value and not allow_empty):
            self.errors.append(f"`{dotted}` precisa ser texto{'' if allow_empty else ' nao vazio'} (veio {value!r})")
            return None
        if choices is not None and value not in choices:
            self.errors.append(f"`{dotted}` precisa ser um de {list(choices)} (veio {value!r})")
        return value

    def flag(self, dotted: str) -> bool | None:
        value = self._value(dotted)
        if value is _MISSING:
            return None
        if not isinstance(value, bool):
            self.errors.append(f"`{dotted}` precisa ser true/false (veio {value!r})")
            return None
        return value

    def str_list(self, dotted: str, allow_empty: bool = True) -> list[str] | None:
        value = self._value(dotted)
        if value is _MISSING:
            return None
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value) or (not allow_empty and not value):
            self.errors.append(f"`{dotted}` precisa ser uma lista de textos{'' if allow_empty else ' (nao vazia)'}")
            return None
        return value


PR_TIMEFRAMES = ("5m", "1h", "4h")
PR_SOURCES = ("trending", "pumpswap", "meteora-damm-v2", "raydium")


def _validate_pos_runner(cfg: Mapping[str, Any], c: "_Checker") -> None:
    """Secao OPCIONAL `pos_runner` (Parte B do POS-RUNNER-V0). Sem ela, o POS-RUNNER fica desligado."""
    section = get_path(cfg, "pos_runner", _MISSING)
    if section is _MISSING:
        return
    if not isinstance(section, dict):
        c.errors.append("`pos_runner` precisa ser um mapa (chave: valor)")
        return
    c.flag("pos_runner.ligado")
    c.text("pos_runner.parametros")
    tfs = c.str_list("pos_runner.timeframes", allow_empty=False)
    if tfs is not None and not set(tfs) <= set(PR_TIMEFRAMES):
        c.errors.append(f"`pos_runner.timeframes` so aceita {list(PR_TIMEFRAMES)} (veio {tfs})")
    c.num("pos_runner.max_pools", 1, 60, integer=True)
    # o teto real e dinamico: o engine nunca reserva para o POS-RUNNER mais que (orcamento do ciclo - 3)
    c.num("pos_runner.chamadas_por_ciclo", 1, 20, integer=True)
    c.num("pos_runner.descoberta_min", 1, 1440)
    sources = c.str_list("pos_runner.fontes")
    if sources is not None and not set(sources) <= set(PR_SOURCES):
        c.errors.append(f"`pos_runner.fontes` so aceita {list(PR_SOURCES)} (veio {sources})")
    c.num("pos_runner.mc_max_usd", 1)
    c.num("pos_runner.idade_max_dias", 1, 60)
    for key in ("watchlist", "entrada", "invalidado", "saida", "so_primario"):
        c.flag(f"pos_runner.alertas.{key}")
    c.flag("pos_runner.grafico")


def validate(cfg: Mapping[str, Any]) -> list[str]:
    c = _Checker(cfg)

    c.text("modo", choices=("paper",))
    c.num("ciclo.intervalo_s", 5, 3600)
    stall = c.num("ciclo.stall_guard_s", 30, 7200)
    interval = get_path(cfg, "ciclo.intervalo_s")
    if stall is not None and isinstance(interval, (int, float)) and stall < interval * 2:
        c.errors.append("`ciclo.stall_guard_s` precisa ser pelo menos o dobro de `ciclo.intervalo_s`")

    c.text("gt.base_url")
    c.num("gt.req_por_min", 1, 30)
    c.num("gt.burst", 1, 30, integer=True)
    c.num("gt.orcamento_por_ciclo", 1, 200, integer=True)
    c.num("gt.timeout_s", 1, 120)
    c.num("gt.pausa_429_s", 1, 3600)
    c.num("gt.pausa_429_max_s", 1, 7200)

    c.text("goplus.base_url")
    c.num("goplus.req_por_min", 1, 120)
    c.num("goplus.timeout_s", 1, 120)
    c.num("goplus.lote_max", 1, 100, integer=True)
    c.num("goplus.pausa_erro_s", 1, 3600)

    c.num("filtros.mc_min_usd", 0)
    c.num("filtros.mc_max_usd", 1)
    c.str_list("filtros.dex_ignorar")
    c.str_list("filtros.dex_liquidez_nao_confiavel")

    for label in ("novo",):
        base = f"gatilhos.{label}"
        c.num(f"{base}.idade_max_min", 1, 120)
        c.num(f"{base}.vol_m5_min_usd", 0)
        c.num(f"{base}.transacoes_m5_min", 0, integer=True)
        c.num(f"{base}.compras_m5_min", 0, integer=True)
        c.num(f"{base}.compras_pct_min", 0, 100)
        c.num(f"{base}.compradores_unicos_m5_min", 0, integer=True)
    s20 = "gatilhos.sobrevivente20"
    lo = c.num(f"{s20}.idade_min_min", 1, 600)
    hi = c.num(f"{s20}.idade_max_min", 1, 600)
    if lo is not None and hi is not None and lo >= hi:
        c.errors.append(f"`{s20}.idade_min_min` precisa ser menor que `idade_max_min`")
    c.num(f"{s20}.preco_min_pct_do_inicial", 0, 1000)
    c.num(f"{s20}.primeiro_avistamento_max_s", 1, 3600)
    c.num(f"{s20}.vol_m5_min_usd", 0)
    c.num(f"{s20}.compras_m5_min", 0, integer=True)
    c.num(f"{s20}.compradores_unicos_m5_min", 0, integer=True)

    c.text("seguranca.sem_dado_acao", choices=("liberar_com_aviso", "descartar"))
    c.num("seguranca.top10_max_pct", 0, 100)
    c.num("seguranca.taxa_max_pct", 0, 100)
    c.num("seguranca.cache_min", 0, 1440)
    c.flag("seguranca.recheck_tardio")
    c.flag("seguranca.evm.exigir_open_source")
    c.flag("seguranca.evm.exigir_owner_renunciado")
    c.flag("seguranca.evm.bloquear_mintable")
    c.num("seguranca.evm.lp_min_travada_queimada_pct", 0, 100)
    c.str_list("seguranca.evm.lp_aplicar_em_dex")
    c.num("seguranca.evm.holders_min_contagem", 0, integer=True)
    c.str_list("seguranca.evm.enderecos_ignorar_top10")
    c.str_list("seguranca.evm.tags_ignorar_top10")
    c.str_list("seguranca.evm.flags_bloqueantes")
    c.str_list("seguranca.evm.flags_aviso")
    c.flag("seguranca.solana.usar_gt_para_mint_freeze")

    c.text("narrativa.arquivo")
    c.num("narrativa.substring_min_len", 1, 20, integer=True)
    c.flag("narrativa.buscar_descricao")
    c.flag("enriquecimento.buscar_trades")

    # --- score -------------------------------------------------------------
    c.num("score.minimo_alerta", 0, 100)
    c.num("score.verde_min", 0, 100)
    pesos = {k: c.num(f"score.pesos.{k}", 0, 100) for k in ("narrativa", "fluxo", "distribuicao", "liquidez")}
    if all(v is not None for v in pesos.values()) and abs(sum(pesos.values()) - 100) > 1e-9:
        c.errors.append(f"a soma de `score.pesos` precisa ser 100 (deu {sum(pesos.values())})")
    c.num("score.narrativa.pontos_match_nome_ticker", 0, 100)
    c.num("score.narrativa.pontos_match_descricao", 0, 100)
    sub_fluxo = [c.num(f"score.fluxo.{k}", 0, 100) for k in ("pontos_volume", "pontos_aceleracao", "pontos_pressao_compra", "pontos_participacao")]
    for key in ("vol_m5_zero_usd", "vol_m5_cheio_usd", "acel_cheia", "compras_pct_cheio", "compradores_unicos_cheio"):
        c.num(f"score.fluxo.{key}", 0)
    c.num("score.fluxo.acel_sem_base_fracao", 0, 1)
    if None not in sub_fluxo and pesos["fluxo"] is not None and abs(sum(sub_fluxo) - pesos["fluxo"]) > 1e-9:
        c.errors.append(f"os sub-pesos de `score.fluxo` (pontos_*) precisam somar `score.pesos.fluxo` ({pesos['fluxo']}); deu {sum(sub_fluxo)}")
    sub_dist = [c.num(f"score.distribuicao.{k}", 0, 100) for k in ("pontos_top10", "pontos_dispersao")]
    for key in ("top10_otimo_pct", "dispersao_cheia", "dispersao_zero"):
        c.num(f"score.distribuicao.{key}", 0)
    if None not in sub_dist and pesos["distribuicao"] is not None and abs(sum(sub_dist) - pesos["distribuicao"]) > 1e-9:
        c.errors.append(f"os sub-pesos de `score.distribuicao` precisam somar `score.pesos.distribuicao` ({pesos['distribuicao']}); deu {sum(sub_dist)}")
    sub_liq = [c.num(f"score.liquidez.{k}", 0, 100) for k in ("pontos_nivel", "pontos_impacto")]
    for key in ("liq_zero_usd", "liq_cheia_usd", "impacto_cheio_pct", "impacto_zero_pct"):
        c.num(f"score.liquidez.{key}", 0)
    if None not in sub_liq and pesos["liquidez"] is not None and abs(sum(sub_liq) - pesos["liquidez"]) > 1e-9:
        c.errors.append(f"os sub-pesos de `score.liquidez` precisam somar `score.pesos.liquidez` ({pesos['liquidez']}); deu {sum(sub_liq)}")
    for key in (
        "volume_suspeito_max", "vol_sobre_liq_max", "pen_vol_sobre_liq", "tx_por_carteira_max", "tx_por_carteira_min_tx",
        "pen_tx_por_carteira", "sem_vendas_compras_min", "pen_sem_vendas", "ticket_medio_min_usd", "pen_ticket_baixo",
        "liq_baixa_usd", "pen_liq_baixa_max", "pen_seguranca_sem_dado", "pen_seguranca_parcial",
    ):
        c.num(f"score.penalidades.{key}", 0)

    # --- plano / acompanhamento ----------------------------------------------
    c.num("plano.posicao_usd", 1)
    c.num("plano.tp1_pct", 1, 10000)
    c.num("plano.tp1_venda_pct", 1, 100)
    c.num("plano.sl_pct", 1, 99.9)
    tempo = c.num("plano.tempo_min", 2, 60)
    c.text("plano.sl_apos_tp1", choices=("mantem", "breakeven"))
    c.num("plano.taxa_terminal_pct", 0, 50)

    if tempo is not None and tempo > 60:
        c.errors.append("`plano.tempo_min` nao pode passar de 60 (a janela do OHLCV termina em +60 min)")
    c.num("acompanhamento.espera_pos_janela_s", 0, 3600)
    c.num("acompanhamento.desistir_apos_min", 10, 10080)

    c.flag("alertas.ligado")
    c.num("alertas.max_atraso_s", 1, 3600)
    c.flag("alertas.botoes")
    c.flag("resumo_diario.ligado")
    hora = c.text("resumo_diario.hora_local")
    if hora is not None and not _HHMM.match(hora):
        c.errors.append("`resumo_diario.hora_local` precisa estar no formato HH:MM (ex.: 22:00)")

    for key in ("axiom", "gmgn", "dexscreener"):
        template = c.text(f"links.{key}")
        if template is not None:
            try:
                template.format(**_LINK_KEYS)
            except (KeyError, IndexError, ValueError) as exc:
                c.errors.append(f"`links.{key}` usa placeholder invalido ({exc}); permitidos: {sorted(_LINK_KEYS)}")

    _validate_pos_runner(cfg, c)

    # --- chains ----------------------------------------------------------------
    chains = get_path(cfg, "chains")
    if not isinstance(chains, dict) or not chains:
        c.errors.append("falta a secao `chains`")
    else:
        if not any(isinstance(v, dict) and v.get("ligada") is True for v in chains.values()):
            c.errors.append("pelo menos uma chain precisa estar com `ligada: true`")
        for name in chains:
            base = f"chains.{name}"
            c.flag(f"{base}.ligada")
            c.text(f"{base}.nome")
            c.text(f"{base}.plataforma", choices=("solana", "evm"))
            c.text(f"{base}.gt_rede")
            c.text(f"{base}.goplus_id")
            c.text(f"{base}.terminal", choices=("axiom", "gmgn"))
            c.text(f"{base}.gmgn_slug")
            c.text(f"{base}.dexscreener_slug")
            c.num(f"{base}.paginas_new_pools", 1, 10, integer=True)
            c.num(f"{base}.liquidez_min_usd", 0)
            c.num(f"{base}.fee_rede_usd", 0)
            c.text(f"{base}.sem_dado_acao", choices=("", "liberar_com_aviso", "descartar"), allow_empty=True)
            c.str_list(f"{base}.ativos_referencia", allow_empty=False)
    return c.errors
