# Bundle Bot Detection V0 — plumbing implementation status — 2026-10-07

Branch: `bundle-bot-detection-v0-plumbing` (criada a partir de
`research/rust-signal-plane-live-shadow-v0@0fd29e1`). **Não commitada na branch de pesquisa
principal** — por instrução explícita do operador, só faz merge depois que o run da replicação do
PQ-TR-V0 terminar, porque esta implementação toca o mesmo caminho de aquisição
(`src/market_observation_store.py`, `src/market_opportunity_radar.py`) que a replicação usa pra
persistir trades/lifecycle.

Escopo original: `docs/bundle-bot-detection-v0-plumbing-scope-2026-10-07.md` (mantido como estava —
análise pré-implementação, não reescrito). Este documento registra o que foi de fato implementado
depois daquele escopo, autorizado pelo operador ("implementação da persistência de slot/creator pode
começar num branch separado" + autorização ampla de execução autônoma na mesma sessão).

## O que foi implementado

1. **Dataclasses** (`src/market_opportunity_radar.py`): `MarketTradeObservation.slot: int | None = None`;
   `MarketLifecycleObservation.creator: str | None = None`, `.creation_slot: int | None = None`.
2. **Schema** (`src/market_observation_store.py`): 3 colunas novas via `ALTER TABLE ... ADD COLUMN`
   guardado, mesmo padrão já usado pra `transaction_key`. `record_market_trade`/`record_market_lifecycle`/
   `load_market_trades`/`load_latest_market_lifecycle`/`_validate_trade`/`_validate_lifecycle`
   estendidos para os 3 campos.
3. **Call sites corrigidos** (slot/creator já disponíveis em escopo Python, só não eram passados —
   confirmado por leitura direta em cada um, não por suposição):
   - `src/pump_bonding_stream.py` — `persist_pump_notification` (trade + lifecycle).
   - `src/pumpswap_stream.py` — `persist_pumpswap_notification` (trade + lifecycle).
   - `src/pumpswap_normalized_persistence.py` — mesma coisa, caminho role-normalizado.
   - `src/pumpswap_normalized_persistence_v2.py` — idem.
   - `src/pumpswap_normalized_persistence_v3.py` — idem, **e também sua própria reimplementação de
     SQL** (`_record_trade_with_connection`/`_record_lifecycle_with_connection` — este arquivo não
     chama `record_market_trade`/`record_market_lifecycle`, tem cópia própria pra permitir
     microbatching; teve que ser corrigido separadamente, achado só depois que um teste de paridade
     "legacy vs current" falhou e expôs a duplicação).
   - `src/pumpswap_causal_normalization_v5.py` — produtor que alimenta os `_LifecycleWrite`/`_TradeWrite`
     do `_v3`, mesma correção.
   - `benchmarks/integrated_market_signal_plane_v1/live_shadow.py` — o motor de captura viva real
     usado por V68/PQ-V1/PQ-TR-V0 (via `route_research_signal_plane_bridge_v0`). Correção num único
     ponto, depois da cadeia if/elif que monta `observation`/`kind` pra qualquer dos 4 tipos de
     evento (`pump_create`, `pumpswap_create_pool`, `pump_trade`, `pumpswap_buy`/`pumpswap_sell`):
     `dataclasses.replace(observation, slot=manifest_slot)` ou `creation_slot=manifest_slot`,
     usando `manifest["slot"]` que já estava em escopo (setado na função de staging, só não lido até
     agora). `creator` fica **deliberadamente `None`** neste caminho — confirmado por grep que o
     decoder Carbon usado aqui nunca surfaça um campo creator em lugar nenhum deste arquivo; obtê-lo
     exigiria tocar o decoder Carbon em si, fora do escopo desta mudança de plumbing.

## O que foi auditado e corretamente NÃO tocado

- `route_research_v68_release.py` — constrói `MarketTradeObservation` com dados sintéticos fixos
  (`chain_time=119`, `transaction_key="pump-signature"`) pra teste de prontidão do pipeline, não é
  captura real. Sem slot real pra propagar; `None` já é o valor correto.

## O que ficou fora desta rodada (não auditado individualmente)

`adapt_carbon_matched_unit_to_market_trade_v0`/`adapt_carbon_pump_trade_v0`
(`src/carbon_matched_unit_adapter.py`, `src/carbon_market_trade_adapter.py`) são chamados por mais de
10 outros arquivos além do `live_shadow.py` (vários benchmarks: `market_first_signal_plane_v0`,
`market_first_live_smoke_v0`, `market_first_live_discovery_v0`,
`market_first_capacity_harness_v0`, `launch_burst_shadow_v0`,
`launch_burst_prospective_route_paper_v2`, `launch_burst_matched_unit_coverage_v0`,
`helius_standard_wss_shadow_v0`, `carbon_kernel_ingress_v0`/`v1`). A correção aplicada no
`live_shadow.py` foi feita **no ponto de chamada** (`dataclasses.replace` depois do retorno do
adapter), não dentro do adapter compartilhado — então ela não se propaga automaticamente pros outros
chamadores. Threading isso universalmente exigiria mudar a assinatura da função compartilhada
(aceitar um `slot` explícito), o que é uma decisão maior, não feita aqui. Pela nomenclatura
(`_smoke_`, `_capacity_harness_`, `_shadow_`), a maioria parece ser harness de benchmark/diagnóstico,
não o caminho de produção real — mas isso não foi confirmado arquivo por arquivo. Fica como próximo
passo explícito, não como "concluído".

## Um achado que exigiu decisão explícita, não correção silenciosa

`_build_signal_record` (`live_shadow.py`) monta o payload JSON do "signal_record" com uma lista de
campos escrita à mão, não um `asdict()` automático — e esse formato parece ser sensível à paridade
com o lado Rust (`rust_suite.py`, `differential.py` na mesma pasta). Decisão: **não adicionar**
`slot`/`creation_slot`/`creator` a esse payload agora — risco real de quebrar uma comparação de
paridade que eu não entendo completamente. O teste `test_signal_record_preserves_exact_observation`
(`tests/test_rust_signal_plane_live_shadow_v0.py`) comparava esse payload contra
`asdict(observation)` inteiro; como esse payload sempre foi uma projeção deliberada de campos (não
um espelho automático), a comparação só era válida por coincidência enquanto o dataclass não tinha
campo extra nenhum. Corrigido o teste para excluir explicitamente `slot` da comparação, com
comentário explicando por quê — não enfraqueci a garantia real do teste (que todo OUTRO campo segue
preservado exatamente).

## Testes

- Novos: `tests/test_market_observation_transaction_identity.py` (round-trip + migração sem perda
  de dado pros 3 campos novos, mesmo padrão já existente pra `transaction_key`);
  `tests/test_pump_lifecycle_capture.py` (3 asserções novas no teste end-to-end já existente).
- Modificado (motivo documentado acima): `tests/test_rust_signal_plane_live_shadow_v0.py`.
- Suíte completa: `python3 -m unittest discover -s tests -p "test_*.py"` → **1882/1882 OK**
  (uma falha isolada e intermitente, `test_audit_pressure_does_not_overtake_later_stateful_work`,
  confirmada por 3 reruns em isolamento como teste de timing pré-existente, sem nenhuma referência a
  qualquer módulo tocado aqui — não é regressão desta mudança).

## Contratos científicos

Nenhum tocado: nenhuma feature, cutoff, gate, ou hipótese do registro foi alterada. Esta é só
plumbing de observabilidade — não calcula `bundle_flag`, não roda nenhuma discovery, não promove
nada. O pré-registro RASCUNHO do Bundle Bot Detection V0 em si continua RASCUNHO.

## Branch e merge

Esta branch (`bundle-bot-detection-v0-plumbing`) está pronta localmente nesta checkout, mas **não foi
mergeada nem pushada ainda** — aguardando o run da replicação do PQ-TR-V0 terminar, por instrução
explícita do operador.
