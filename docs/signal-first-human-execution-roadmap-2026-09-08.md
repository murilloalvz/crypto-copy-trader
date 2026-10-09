# Signal-First / Human-Executed Product Roadmap

Status: **architecture/documentation only** — no UI, migration, live execution or V68 change.

## Product thesis

Crypto Copy Trader is evolving into an **Opportunity Intelligence Engine**. Its initial value is
to help a human find, understand and evaluate opportunities before operating. The project does
not need full automation to prove opportunity quality or signal usefulness.

The distinction is explicit:

1. find an opportunity or edge;
2. emit a prospective, useful and auditable decision;
3. capture that opportunity economically;
4. automate the capture.

Automation may be delayed. Execution realism may not: executable quotes, liquidity, slippage,
latency, entry geometry, route availability, exit behavior, shadow execution and net economics
remain part of the evidence.

## Intended lifecycle

```text
Opportunity Intelligence
        -> Research Signal
        -> Validated Signal
        -> Human TAKE/SKIP
        -> Manual Execution initially
        -> Automatic Outcome Tracking
        -> Shadow Execution
        -> Assisted Execution
        -> Selective Automation
        -> eventual Full Automation
```

No stage authorizes live money by itself.

## Prospective signal contract

Every signal must be immutable and versioned. The conceptual contract includes:

```text
signal_id, signal_version, episode_id
token, detected_at, emitted_at, decision_as_of
detector_version, strategy_version
signal_class, eligibility_status
reference_quote, reference_quote_observed_at
market_flow_evidence
participant_structure_evidence
wallet_evidence
social_narrative_evidence
launch_quality_evidence
execution_reality_evidence
missingness, risk_flags, reason_codes
confidence_method, confidence_version, confidence_value
human_decision, human_decision_at, human_reason
```

The signal may use only information available by `decision_as_of`. Later information must become
an update, new version or new event; it must not rewrite the original decision. Until a confidence
method has a calibration dataset and prospective validation, confidence is `NOT_AVAILABLE`.

## Independent outcome populations

Future human-execution experiments must preserve:

### ALL SIGNALS

Every signal emitted prospectively, including signals the human skips.

### HUMAN SELECTED

The human records `TAKE` or `SKIP` before the outcome, together with decision timestamp, optional
reason and the signal version shown. The system then tracks the outcome automatically.

### SHADOW AUTO

The same frozen execution policy is evaluated independently of the human decision. Human-selected
performance is not evidence of incremental edge merely because its median exceeds ALL SIGNALS;
comparisons must control for evidence available in the original signal.

## Signal taxonomy

- **Research Signal:** hypothesis/evidence under research; not an operating recommendation.
- **Validated Signal:** rule passed its declared prospective protocol; execution is not necessarily
  economically validated.
- **Operational Signal:** opportunity validation, execution realism, exit behavior, shadow evidence
  and risk specification are sufficiently established; this still does not authorize live money.

## Evidence families

The future Signal Engine may combine, while keeping provenance and missingness explicit:

1. **Market / Flow:** acceleration, event count, buy/sell structure and timing.
2. **Participant Structure:** distribution, concentration, participant mix and independent actors.
3. **Wallet Intelligence:** wallet quality, convergence, direct funding and behavioral history.
4. **Social / Narrative:** attention acceleration, public actors and event context.
5. **Launch / Token Quality:** lifecycle, authorities, hazards and token structure.
6. **Execution Reality:** liquidity, executable quote, slippage, route, exit and net economics.
7. **Cross-Market / Multichain:** Solana plus future chain/venue context.

Wallet evidence is post-opportunity evidence, not a primary acquisition whitelist. Social
`created_at` is not causal availability. Multichain research must not block Solana validation or
rescue a failed hypothesis.

## Roadmap phases

1. **Opportunity Intelligence:** detect and structure causal opportunities.
2. **Research Signals:** emit versioned, auditable prospective signals.
3. **Validated Signal Bot:** promote only rules that pass prospective validation.
4. **Human-Executed Workflow:** record TAKE/SKIP before outcome and track outcomes automatically.
5. **Shadow Execution:** compare ALL SIGNALS, HUMAN SELECTED and SHADOW AUTO.
6. **Assisted Execution:** prepare execution while retaining human confirmation.
7. **Selective Automation:** automate only economically and operationally validated contexts.
8. **Full Automation:** consider only if later evidence justifies it.

## Scientific and operational boundaries

- historical P&L is not causal edge;
- systems PASS is not economic edge;
- route is not fill;
- discovery is not holdout validation;
- failed prospective hypotheses are closed, not retuned;
- missingness, latency and execution limitations remain explicit;
- detector, V68 feature/bins/horizon/gates and economics remain frozen;
- funded executable BUY is `BLOCKED_BY_FUNDING`;
- landing/fill validation and shadow are `NOT_RELEASED`;
- market-first exit is `NOT_VALIDATED`;
- live money is `NOT_AUTHORIZED`.

V68 remains the existing frozen next economic experiment and stays `NOT_EVALUATED`. This roadmap
does not start it, reinterpret it or change its protocol.
