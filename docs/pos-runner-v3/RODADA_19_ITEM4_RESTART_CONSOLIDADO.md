# Rodada 19, item 4 — restart consolidado (carteiras rodada 15 + fix dets_v3 + lock de banco + sombra desta rodada)

PAPER/READ-ONLY. Esta rodada não exige restart por si (itens 1-3 são só gravação/leitura), mas o
pedido pede juntar num único restart as mudanças que **já estão no código, commitadas, mas ainda
não aplicadas num processo vivo na VM**: (a) rodada 15 (RPC dedicado de carteiras + placebo), (b)
rodada 17 item 4 (fix do `dets_v3` na limpeza de aposentação/rotação — memory leak), (c) rodada 17
item 5 (lock de arquivo contra 2 processos físicos no mesmo banco), (d) a sombra desta rodada
(`pr3_suporte_sombra`). Nenhuma mudança de detector/parâmetro/H1/critério em nenhuma delas.

## 1) Variáveis de ambiente novas (com valor padrão)

Nenhuma delas MUDA um comportamento já em produção por si — todas têm um padrão que reproduz
exatamente o que já rodava antes de cada rodada ser commitada (SEM_X nunca ligado por padrão;
CARTEIRAS_RPC_PER_MIN/CARTEIRAS_PLACEBO_K só afinam ritmo/K, nunca desligam nada por si).

| variável | rodada | padrão (sem configurar) | o que faz |
|---|---|---|---|
| `CARTEIRAS_RPC_PER_MIN` | 15, Parte 2 | `10` | ritmo (chamadas/min) do RPC DEDICADO da coleta horária de baixa prioridade de carteiras "pro" — nunca o mesmo limitador de lineage/graduação |
| `CARTEIRAS_PLACEBO_K` | 15, Parte 3 | `3` | nº de pools de controle/placebo gravados em `pr3_carteiras_sinal` no mesmo ciclo de cada sinal V3 real |
| `SEM_SUPORTE_SOMBRA` | 19, item 1 | desligado (sombra LIGADA) | `1` desliga por completo a sombra forward "entrada no suporte" (`pr3_suporte_sombra`) |

Já existente, sem mudança nesta rodada, mas relevante ao contexto do item 2 abaixo:
`CARTEIRAS_MAX_CHAMADAS_DIA` (padrão `600`) — teto diário de chamadas RPC da coleta horária.

Adicionadas a `signals_mvp/.env.example` nesta rodada (nunca estavam documentadas lá antes, apesar
de já existirem no código desde a rodada 15 — lacuna fechada agora).

## 2) Comportamento do orçamento sob `RateLimited` (resposta à Rodada 15, Parte 1)

**Antes** (achado do diagnóstico, `docs/pos-runner-v1/DIAGNOSTICO_2026-11-10_CARTEIRAS_PRO_RATELIMITED.md`):
`_registrar_snapshot_carteiras` só gravava uma linha em `pr_carteiras_snapshot` em SUCESSO — o
contador de orçamento (`pr_carteiras_snapshot_count_since`) só somava sucessos. Sob `RateLimited`
sistemático (100% de falha), o contador ficava **preso em 0 para sempre** e o bot nunca se
autolimitava — tentava de novo em TODO pool elegível, toda hora, indefinidamente, mesmo sabendo que
ia falhar.

**Depois** (já implementado, rodada 15 Parte 2 — `live.py: _atualizar_carteiras_horaria`): o
orçamento agora conta **TENTATIVAS** (sucesso+falha, `pr_carteiras_tentativa`), nunca só sucessos —
o bot se autolimita corretamente mesmo sob falha total. Além disso, a prioridade foi separada:
pools com posição/sinal **aberto** (qualquer versão) usam o RPC compartilhado rápido, prioridade
absoluta, nunca afetados por `RateLimited` na coleta de baixa prioridade; os demais elegíveis (só
fase runner/pullback, sem posição) usam o RPC DEDICADO (`CARTEIRAS_RPC_PER_MIN`, ritmo
deliberadamente baixo, nunca AIMD-degradável pelo tráfego de lineage/graduação). **Isto já está no
código — só precisa do restart para valer num processo vivo.**

## 3) Medição de cobertura (pergunta nova desta rodada — não existia resposta antes)

O que **já existe** hoje (`saude.py`): "orçamento hoje: X/600" (agora contando tentativas, não só
sucessos, pós rodada 15) e "último erro" — isso mede **volume de tentativa**, nunca **cobertura**
(fração de pools ELEGÍVEIS que de fato conseguiram pelo menos 1 snapshot bem-sucedido na janela).

**Não implementado** (fora do escopo desta rodada, que é só gravação/leitura): uma métrica dedicada
de cobertura, análoga ao "radar coverage >=95%" já usado nos gates do sistema de sinal. Proposta
(texto apenas, para uma rodada futura caso o operador autorize): `pr_carteiras_cobertura_pct` =
`(pools elegíveis distintos com >=1 snapshot bem-sucedido na janela de 24h) / (pools elegíveis
distintos na mesma janela)` — exibido ao lado do orçamento em `saude.py`, nunca usado como gate
automático (só diagnóstico, igual ao resto do painel de saúde).

## 4) Plano de RPC (resposta à Rodada 15, Parte 1 — sem mudança nova)

`worker.py` usa `endpoints_from_env()` (env `POS_RUNNER_RPC_URLS`), que cai no default
`DEFAULT_ENDPOINTS = ("https://api.mainnet-beta.solana.com",)` — **1 único endpoint público e
gratuito** — quando a variável não está configurada. **Esta sessão não tem evidência de um RPC
pago configurado na VM real** (mesma limitação declarada desde a rodada 15 Parte 1 — sessão cloud
isolada, sem acesso ao `.env` real). Recomendação (repetida, ainda válida): se o volume de
"carteiras pro" + lineage continuar gerando `RateLimited` com frequência mesmo depois deste
restart (Parte 2 da rodada 15 já separa o tráfego, mas o endpoint público continua sendo o mesmo
recurso físico por baixo), configurar `POS_RUNNER_RPC_URLS` com um endpoint pago (Helius/QuickNode,
camada gratuita já cobre a maioria dos casos de uso leve) é o próximo passo natural — decisão do
operador, nunca automática.

## Passo a passo do restart seguro

1. **Backup antes de qualquer coisa** (o backup diário já existe, `BACKUP_RETENCAO_DIAS` — mas
   confirme que correu nas últimas 24h, ou force um manual, antes de reiniciar com schema novo):
   ```bash
   ls -la backups/ | tail -5
   ```
2. **Puxar o código novo** (branch `signals-mvp`, PR #10) e confirmar que a suíte de testes está
   verde NA VM antes de reiniciar o serviço real (nunca confiar só na suíte desta sessão cloud):
   ```bash
   cd /caminho/do/repo && git pull
   python -m unittest discover -s signals_mvp/tests -t .
   ```
3. **Conferir o `.env`** — nenhuma variável nova é OBRIGATÓRIA (todos os padrões reproduzem o
   comportamento já commitado); só adicione `CARTEIRAS_RPC_PER_MIN`/`CARTEIRAS_PLACEBO_K`/
   `SEM_SUPORTE_SOMBRA` ao `.env` real se quiser um valor DIFERENTE do padrão.
4. **Reiniciar pelo mecanismo já em uso** (systemd, conforme `docs/DEPLOY_VPS_LINUX.md`, seção de
   restart — ou `tmux` se ainda não migrou):
   ```bash
   sudo systemctl restart signals-mvp
   sudo systemctl status signals-mvp   # confirmar "active (running)"
   ```
5. **Confirmar que o schema novo foi criado** (as 2 tabelas desta rodada são `CREATE TABLE IF NOT
   EXISTS`, criadas automaticamente no 1º `Storage(paths)` do processo novo — nunca precisa de
   migração manual):
   ```bash
   sqlite3 signals_mvp/dados/estado.sqlite ".tables" | grep suporte_sombra
   ```
6. **Confirmar que o hash do pré-registro da sombra forward foi aceito** (se o processo SOBE sem
   erro e sem a mensagem de `PreregistroAlteradoError`, o hash foi aceito — a 1ª vez grava, as
   seguintes só confirmam):
   ```bash
   journalctl -u signals-mvp -n 50 --no-pager | grep -i "preregistro\|PosRunnerLive"
   ```
7. **Observar 1-2 ciclos** (`saude.py`) para confirmar que o orçamento de carteiras agora reflete
   tentativas (não fica mais travado em "0/600" sob falha) e que não há exceção nova nos logs —
   `_sombra_safe` garante que qualquer erro da sombra nova nunca derruba o ciclo, mas vale conferir.
8. **Nunca** rodar o worker 2x ao mesmo tempo (rodada 17 item 5 já trava isso com um lock de
   arquivo automático — `signals_mvp/dados/estado.sqlite.lock` — mas pare a sessão antiga
   explicitamente antes de iniciar a nova, nunca confie só no lock pra evitar confusão operacional).

## O que NÃO muda neste restart

Detector, `ParamsV1`/`ParamsV2`/`ParamsV3`, H1, critério de sinal, banca/capital real — tudo
intocado. As 2 tabelas novas (`pr3_suporte_sombra`/`pr3_suporte_sombra_saida`) e a coleta de
carteiras com RPC dedicado são aditivas, nunca substituem nada já existente; `SEM_SUPORTE_SOMBRA=1`
reverte a parte nova desta rodada a zero custo caso o operador prefira não ligar ainda.
