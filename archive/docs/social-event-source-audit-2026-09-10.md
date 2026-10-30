# Social/Event Source Audit — 2026-09-10

Status: RESEARCH ONLY / NO SOCIAL COLLECTOR / NO EDGE CLAIM
Track: B — Social/Event-First

## Decision

Do not integrate Axiom or J7Tracker as a Social/Event production source yet.

Current classifications:

- J7Tracker: **LEARN / DEFER INTEGRATION**
- Axiom: **LEARN / DEFER INTEGRATION**

Reason: both expose useful evidence that social tracking exists as a product capability, but the public evidence found today is insufficient to establish a causal, reproducible feed contract with `available_at`, source coverage, replay semantics, event identity, and programmatic access suitable for research.

This is not a rejection of either product. It means the project's scientific requirements are stricter than UI/marketing evidence.

## J7Tracker

Sources inspected:

- https://j7tracker.com/
- https://docs.j7tracker.io/docs
- https://docs.j7tracker.io/docs/endpoints-and-regions
- https://docs.j7tracker.io/docs/create-token
- https://docs.j7tracker.io/docs/create-token/bundle

Documented/verifiable today:

- Regional HTTP deploy/trade API exists.
- Public docs describe `/submit` for token create/sell and `/ping` for regional health/latency.
- API requires JWT/session plus encrypted API key for authenticated deploy/trade actions.
- Pump.fun and other launch modes are documented.
- Bundle/sniper wallet execution controls are documented.

Vendor claims / not yet independently validated:

- site markets social-media tracking across Twitter/X, Truth Social, Instagram and TikTok;
- site claims roughly sub-second (~200 ms average) social delivery.

Critical gaps for Track B:

- no public social-feed API contract was found in the inspected API docs;
- no documented event payload/schema for social observations was found;
- no documented `available_at` semantics were found;
- no documented replay/history contract was found;
- no documented source-level coverage guarantee was found;
- no documented event-to-token mapping contract was found.

Therefore J7 social claims are useful Existing-Solutions-First leads, but cannot yet be treated as causal research data.

## Axiom

Source inspected:

- https://axiom.trade/trackers

Externally observable today:

- tracker UI exposes `Social Alerts` and an `Add Twitter Handles` action;
- Axiom also exposes wallet/KOL tracking surfaces in the same product area.

Critical gaps for Track B:

- no public Social Alerts API contract was established in this audit;
- no causal `available_at` contract established;
- no replay/history contract established;
- no source coverage contract established;
- no event-to-token mapping contract established.

Therefore the UI is evidence that Axiom has a useful product concept to study, not evidence that the project can currently integrate it as a reproducible research feed.

## Scientific requirements before INTEGRATE

A candidate Social/Event source must provide or allow us to measure:

1. stable source event identity;
2. source-created timestamp when available;
3. local causal receive timestamp (`available_at`/`observed_at`);
4. explicit distinction between created time and availability time;
5. deterministic deduplication;
6. source/provider identity;
7. coverage status and gaps;
8. replay/history semantics, if any;
9. raw payload retention or sufficient provenance for audit;
10. event-to-token mapping as a separate, auditable step rather than an inferred truth;
11. no future observation backfilled into T0.

Marketing latency alone cannot satisfy these requirements.

## Next Existing-Solutions-First steps

Before building a Social collector:

- inspect authenticated/product-accessible export/webhook/API capabilities if available without relying on undocumented scraping;
- identify other documented providers that expose social events programmatically;
- benchmark `available_at` only from locally observed receipt times;
- classify each candidate as INTEGRATE / LEARN / DEFER / REJECT;
- build only the missing neutral observation layer after source selection.

## Isolation rule

Track B remains independent from Market-First and Launch Burst.

No Social score, KOL score, mention count, attention score, or convergence rule enters Track A or Track C before Track B demonstrates standalone causal observability and receives its own preregistered prospective test.
