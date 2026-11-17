# Revisão completa do projeto — Rodada 16 (2026-11-10)

Auditoria read-only (PAPER). Nenhum código/parâmetro/detector/config/hash alterado
(`ParamsV1=279b79ffa3f0`/`ParamsV2=d57b4331d51d`/`ParamsV3=56762db29cd6`, reconfirmados intactos em
cada parte). Partes detalhadas em `docs/revisao-2026-11-10/`:

- [Parte A — Verificação independente dos números-chave](revisao-2026-11-10/PARTE_A_VERIFICACAO_NUMEROS.md)
- [Parte B — Correção do pipeline de dados](revisao-2026-11-10/PARTE_B_PIPELINE_DADOS.md)
- [Parte C — Detector e hipóteses](revisao-2026-11-10/PARTE_C_DETECTOR_HIPOTESES.md)
- [Parte D — Estatística e processo](revisao-2026-11-10/PARTE_D_ESTATISTICA_PROCESSO.md)
- [Parte E — Realismo de execução](revisao-2026-11-10/PARTE_E_EXECUCAO_REALISMO.md)
- [Parte F — Operação e robustez](revisao-2026-11-10/PARTE_F_OPERACAO_ROBUSTEZ.md)
- [Parte G — Caminho ranqueado até o edge](revisao-2026-11-10/PARTE_G_CAMINHO_PARA_EDGE.md)

## Resumo executivo

Esta sessão **não tem acesso ao banco SQLite ao vivo da VM** (gitignored, nunca commitado) — nenhum
número de R/contagem de `ao_vivo`/`retro_lote1`/`replay_v3` pôde ser recalculado de dado real; toda
a auditoria é sobre CÓDIGO (fato verificado por leitura direta, citado linha a linha) mais o que já
está documentado. Nenhum achado **P0** foi encontrado — nada aqui corrompe dinheiro real hoje (o
projeto segue 100% PAPER). Mas dois achados **P1** merecem atenção prioritária porque afetam
diretamente a validade do caminho até dinheiro real: (1) **H1** — a única hipótese confirmatória,
porta para `EDGE_PROVISORIO` — **nunca foi migrada** para o motor de R no horizonte fixo que o
próprio projeto construiu (rodadas 11-12) para corrigir o viés de excluir sinais não resolvidos por
regra (`perdido_offline`/`aberto`); (2) o modelo de custo que decide H1 usa uma posição **fixa** de
0,15 SOL, desacoplada do mecanismo de custo-por-tamanho-real que o projeto já tem implementado
(`bankroll.py`) mas nunca liga ao caminho estatístico. Fora isso: nenhum lookahead foi encontrado em
nenhum dos 3 caminhos (vivo/replay/retro) — achado positivo e importante; o motor exploratório de
R@72h não aplica o mesmo veto de candle corrompido que o caminho ao vivo aplica (mesma classe do
incidente McRib -561R); duas ferramentas de contagem (`varredura_v3.py`, `funil_diario.py`) têm
lacunas de identidade (symbol em vez de mint) e cobertura (sem V3) que tornam alguns números já
citados em rodadas anteriores não-confiáveis sem correção; a V3 vaza memória lentamente (detectores
nunca liberados); e o R reportado hoje é, honestamente, um **teto** de execução quase-perfeita —
MEV/priority fee/atraso de execução/profundidade de book nunca são subtraídos. A Parte G ranqueia o
que fazer a seguir: primeiro a higiene dos achados acima (barato), depois um redesenho estrutural de
alvo curto de alta frequência (maior valor esperado por tempo, ataca o bottleneck de poder
estatístico já sofrido pelo projeto), com carteiras forward e bundle/funding como as próximas
fronteiras de dado novo.

## Tabela de achados

| Sev. | Parte | Achado | Confiança |
|---|---|---|---|
| P1 | C | H1 (única confirmatória) nunca migrada para o motor de horizonte fixo — exclui `perdido_offline`/`aberto` por construção | alto (fato) / médio (magnitude real) |
| P1 | E | `CostModel` que decide H1/R@72h usa posição FIXA 0,15 SOL, desacoplada da banca real | alto |
| P1 | B | `horizonte_fixo.py` não aplica veto de candle corrompido (mesma classe do incidente McRib -561R) | alto |
| P1 | A | `varredura_v3.py` usa SYMBOL como identidade de token em 3 origens (mint nunca carregado) | alto |
| P1 | A / C | `funil_diario.py` nunca inclui V3 — ETA/funil citado pelo operador não mede a hipótese prioritária | alto |
| P1 | D | ≥5 famílias de Holm/Bonferroni paralelas nunca combinadas numa família projeto-inteira | alto |
| P1 | E | Limite de 1,5% do supply nunca é aplicado como filtro — só reportado | alto |
| P1 | E | MEV/priority fee/jito nunca modelados (já reconhecido pelo próprio projeto, citado com linha) | alto |
| P1 | E | Saída (stop/TP) não modela profundidade de book em quedas correlacionadas | médio |
| P1 | F | `dets_v3` nunca é liberado em aposentação/rotação de pool — vazamento de memória específico da V3 | alto |
| P1 | F | `DetectorV1.bars`/`.tr`/`.events` crescem sem limite pela vida do rastreamento | alto (crescimento) / hipótese (impacto real na VM) |
| P1 | F | Nenhuma trava contra 2 processos simultâneos no mesmo banco (orçamento de API pode dobrar silenciosamente) | alto |
| P1 | A / C | Teste de RECALL (B9, Aoin/Solana Cat/Apil) nunca preenchido pelo operador — não executável | alto |
| P1 | A | Números citados em conversas (ex. "mediana -1,1R") não têm trilha de auditoria commitada | alto |
| P1 | B | `perdido_offline` não tratado nos scripts de análise formal (leitura mista — ver Parte B/C) | médio |
| P1 | D | Não foi feita varredura de `git log`/`git blame` por retunes não declarados (lacuna, não achado positivo) | alto (honestidade da lacuna) |
| P2 | B | `varredura_v3.py` checa candle corrompido em pontos específicos, não comprovadamente em todo o caminho | médio |
| P2 | B | Zero checagem de volume do candle de entrada vs tamanho de posição modelado | alto |
| P2 | B | Detecção de clone/vamp é exclusiva de V1/V2 (V3 é deliberadamente "lean", já documentado) | alto |
| P2 | C | Filtros que podem cortar sinais verdadeiros (idade, `l_bc_ceiling_usd`) não quantificados nesta sessão | baixo |
| P2 | D | H13/H14 sem `n` mínimo de reporte explícito no trecho lido | baixo |
| P2 | D | Dois desenhos de poder diferentes reusam o mesmo DP sem re-medição | médio |
| P2 | E | Atraso sinal→ordem não quantificado nesta auditoria (falta de acesso, não de instrumentação) | não verificável |
| P2 | E | Custo fixo de rede (0,0003 SOL) não é a mesma coisa que priority fee competitivo | médio |
| P2 | F | systemd sem `MemoryMax=`/`StartLimitBurst` reforçado | médio |
| P2 | F | Teste `test_never_writes_to_the_database` só confere 1 de ~20 tabelas | alto |
| P2 | F | Backup nunca foi testado em restauração | alto (ausência) |

## Parte G — ranking resumido (ver documento completo para lógica/evidência/custo/N/controle)

0. **[pré-requisito, barato]** Corrigir a higiene de sinal acima (H1→horizonte fixo, `CostModel`,
   veto de candle corrompido, vamp na V3) antes de confiar em qualquer R futuro.
1. **[maior valor esperado por tempo]** Redesenho estrutural: alvo curto de alta frequência em
   paralelo à cauda — ataca o bottleneck de poder estatístico (MDE alto, N=60) já sofrido.
2. **[já em andamento, bem desenhado]** Carteiras rastreadas/smart money forward (V3) — custo é só
   tempo, placebo já obrigatório.
3. **[lógica forte, nunca tentado]** Bundle/cluster de funding — hipótese nova, custo de RPC
   médio-alto, exige o mesmo cuidado de orçamento dedicado já corrigido na Rodada 15.
4. **[já testado desfavoravelmente em linha relacionada]** Fluxo/participação genérico — V68 FAIL +
   PQ-V1 KILL na mesma categoria de ideia; só com feature genuinamente nova.
5. **[barato, já rodando]** Entrada no suporte com stop curto — já é o grupo H2 `reacao_suporte`.

**Não vale mais a pena**: mais variantes de gestão de saída; reparametrizar V1→V2→V3 sobre o mesmo
detector-base sem evidência de bug; reabrir PQ-V1; mais estratos sem dado novo.

**Red team (o que tornaria a leitura cautelosa atual errada)**: H1 não migrada pode estar jogando
fora perdas reais (H1 mais favorável do que deveria, nunca menos); candle corrompido não vetado pode
distorcer a média exploratória em qualquer direção; viés de seleção do universo de replay/retro
(só sobreviventes com candle cacheado); e a distinção não resolvida entre "sem sinal" vs "sinal
existe mas não é executável" dado o realismo de custo ainda incompleto.

## Commits desta rodada

Um por parte: Parte A (`765f784`), Parte B (`cd4e4fb`), Parte C (`0637029`), Parte D (`d1c05d4`),
Parte E (`67d5078`), Parte F (`5d05a90`), Parte G (`d945794`), e este índice.
