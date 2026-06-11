# L2T2 → prop-eval bridge verdict (2026-06-11)

**Verdict: GO** — buying one FTMO 100k Swing evaluation, traded as the
L2T2 insurance-layer stream at ~0.35-0.40x source size under the
RiskGovernor, is positive-EV under every sensitivity tested. Details and
the no-go conditions below.

## What was evaluated

The L2T2 TQQQ system (branch `fable5/edge-and-trust`) after its trust
audit. Per `l2t2/EDGE_REPORT.md`: the CAGR-alpha claim is **retired**
(close-fill artifact + selection luck); what survived OOS is the
**insurance layer** — the regime filter and/or volatility-targeted sizing,
which held Sharpe ~1.25 on the untouched 2023-03→2026-06 holdout under
MOO execution while every mined ensemble collapsed. This bridge evaluates
exactly those survivors. No new signal search was performed; no holdout
was touched (the l2t2 holdout was already spent by its own audit, once).

Export: `scripts/export_l2t2_returns.ts` (read-only against l2t2)
reproduces the audited `sizing-experiment.ts` pipeline — MOO execution
(next_open + 2 bps, 0.05%/leg costs, deadband 0.05) — and writes daily
return streams to `results/l2t2_bridge/`. Cross-check: full-period
live+voltarget_55 came out CAGR 37.1% / Sharpe 1.28 / MaxDD 33.0% vs the
audited dev row 36.0% / 1.29 / 33.0%.

Three streams, two bootstrap pools each (822-day OOS holdout slice;
4,108-day full period 2010-2026 for regime diversity):

| Stream | Full-period Sharpe | Holdout Sharpe | Holdout t |
|---|---|---|---|
| live config + voltarget_55 ("belt & suspenders") | 1.28 | 1.27 | 2.29 |
| voltarget_55 on B&H (no mining ancestry) | 1.04 | 1.25 | 2.26 |
| live config alone | 1.08 | 1.24 | 2.24 |

All three are statistically indistinguishable OOS — consistent with the
audit's conclusion that the de-risking layer, not the oscillator complex,
is the edge.

## Bridge results (FTMO 100k, fee $600, funded_value $8,000, 4,000 sims)

`scripts/eval_from_returns.py <csv> --notional 100000 --eval-fee 600
--funded-value 8000 --swing-only`, MAE proxy 1.3x by default.

Primary stream **live + voltarget_55**, optimal scale per phase:

| Pool | Phase 1 P(pass) | Phase 2 P(pass) | Scale | EV/attempt (per phase) |
|---|---|---|---|---|
| Holdout (OOS, bull-only) | 71.5% | 86.5% | 0.36x | +$5.1k / +$6.3k |
| Full period (all regimes) | 68.8% | 84.3% | 0.40x | +$4.9k / +$6.1k |

Combined P(pass both phases) ≈ **58%** (full-period pool). The other two
streams land within a few points (B&H+vt55: 68.5%/83.3%; live alone:
65.5%/82.8%).

Sensitivities (full-period pool, live+vt55):

- MAE factor 1.6 (harsher intraday excursions): P1 63%, P2 83% — still GO.
- MAE factor 2.0: P1 49%, P2 80%, combined ~39%, EV ≈ +$2.5k — still GO.
- funded_value $3,000 (pessimistic payout): EV ≈ +$1.1k combined — still GO.
- **Breakeven funded_value ≈ $1,050** at combined P(pass) 58%. The claim
  "one funded FTMO account is worth less than $1,050 in expectation" is
  the only way this is negative-EV, and it is not credible for a stream
  with t > 5 over 16 years.

Caveats priced in honestly:

- The holdout pool is one bull regime; that is why the full-period pool
  (2011 chop, 2015-16, 2018, 2020, 2022) is the headline number. The
  live-config dev period carries selection ancestry, but the
  no-ancestry control (voltarget_55 on B&H) gives the same answer.
- Worst year in the stream: 2011 at −$15/day mean (scale 0.40 on 100k) —
  an eval started into a 2011-type regime mostly times out (FTMO has no
  time limit; capital sits, fee survives) rather than busts: P(total-DD
  breach) ≤ 2% at 0.40x.
- P(timeout at 300 sim days) ≈ 18% in Phase 1 — with no FTMO time limit
  these are slow non-failures, so P(pass) above is conservative.

## Execution spec (paper plan only — NO orders placed; human decision)

- **Instrument**: FTMO Swing 100k (allows overnight/weekend holds and
  EAs; required — the system holds for weeks). Map TQQQ weight w(t) ∈
  [0,1] to **US100 CFD notional = w × scale × 3 × account** (TQQQ is 3x
  QQQ). At scale 0.40: max US100 notional $120k = 1.2:1 account leverage
  (Swing leverage cap 1:30 — far inside).
- **Orders**: daily decision at 16:00 ET close from the l2t2 signal +
  20d-vol target; execute the weight change at the 09:30:00 ET cash open
  (the MOO-equivalent the audit recommends; assumed 2 bps slippage ≈
  US100 CFD spread). Rebalance only when |Δw| > 0.05 (deadband already in
  the stream).
- **RiskGovernor** (`hightrader.risk`): daily soft-stop **−$3,500**
  (flatten intraday, 30% buffer inside FTMO's $5k — the stream's worst
  day at 0.40x was −$5.3k, so the governor is load-bearing, not
  decorative); reserved total-DD buffer $2,000 of the $10k; kill switch
  on the independent code path; max one weight change/day.
- **Size**: scale 0.36-0.40x of source (the P1/full-period optima). If
  the governor's daily stop binds more than ~2x/quarter, drop to 0.33x.
- Phase 2 at the same scale (its optimum coincides), then funded at
  ~0.25-0.30x (funded phase optimizes survival/payout, not target speed —
  to be re-run with payout-rule profiles before going funded).

## Trial-ledger note

This bridge ran **zero** new signal-search trials: three pre-existing,
externally-audited streams were pushed through the registered MC
machinery, all results reported. Cumulative mined-config ledger stays at
**63**. No Hightrader holdout was touched.
