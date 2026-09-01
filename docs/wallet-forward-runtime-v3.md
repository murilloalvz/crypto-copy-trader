# Wallet Forward Runtime v3 — Rotating Poll Order

Status: **IMPLEMENTADO / TESTADO** em `feat/exit-engine-v1`.

Runtime id:

`wallet_forward_runtime_v3_rotating_poll_order`

## Por que v3

O coletor Solana RPC continua sequencial por simplicidade/controle de carga. Em uma ordem fixa:

```text
A -> B -> C
A -> B -> C
A -> B -> C
```

A wallet A tende a ser consultada antes de B/C em todo ciclo. Se cada sync consumir tempo não desprezível, parte do `source lag` pode refletir posição fixa no loop, não apenas a velocidade real com que a transação apareceu no RPC.

Isto cria um viés de observabilidade evitável.

## Mudança

A ordem agora gira deterministicamente:

```text
ciclo 1: A -> B -> C
ciclo 2: B -> C -> A
ciclo 3: C -> A -> B
ciclo 4: A -> B -> C
```

A coorte congelada no manifest não muda. Somente quem é consultado primeiro em cada ciclo muda.

## O que permanece do runtime v2

- bootstrap não vira forward;
- causal boundary por `chain_time`;
- transação anterior ao início descoberta tarde não vira confirmação forward;
- quote intake grace;
- end observation id congelado quando Wallet Watch termina;
- Quote Watch com cursor bounded e final bounded scan;
- exact-event quote linkage;
- run manifest;
- runs sobrepostas bloqueadas.

## O que v3 NÃO resolve

Rotação reduz viés fixo de posição, mas não transforma polling em stream.

Ainda existem:

- RPC provider latency;
- sync duration variável;
- transações muito rápidas entre ciclos;
- limites de `MAX_SIGNATURES_PER_SYNC`;
- sequencialidade dentro de cada ciclo;
- atraso local até parser/persistência.

Não chamar v3 de captura em tempo real.

## Comparação com runs anteriores

- coleta de 6h iniciada antes desta mudança: `wallet_forward_runtime_v1_unversioned`;
- runtime causal-boundary anterior: `wallet_forward_runtime_v2_causal_boundary`;
- novas runs: `wallet_forward_runtime_v3_rotating_poll_order`.

Estes regimes devem permanecer separados em auditoria.

Use:

```powershell
python wallet_forward_run_compare.py
```

Mesmo duas runs v3 com configurações iguais não são pooled automaticamente.
