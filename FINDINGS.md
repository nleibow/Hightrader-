# Findings — prop-firm system validation campaign (2026-06-11)

Everything below was produced under pre-registered protocols (PROTOCOL.md,
addenda 1-2) with frozen grids, leak-checked engines, and one-shot
holdouts, following the L2T2 audit discipline. Raw outputs in `results/`.

## Scoreboard

| Candidate | Data | Dev/OOS verdict | Holdout |
|---|---|---|---|
| ORB intraday 5m | NAS100 05-18, SPX 10-18 | FAIL: OOS -$10 to -$31/trade, PF 0.74-0.90 | untouched |
| Trend momentum 5m | both | FAIL | untouched |
| Mean reversion 5m | both | FAIL | untouched |
| TSMOM daily, single index | NAS100 | FAIL (t=1.68 < 2) | untouched |
| TSMOM daily, single index | SPX | dev CANDIDATE (t=2.30, PBO 22%) | **KILLED: -$13k, t=-0.66 on 2018 regimes** |
| TSMOM diversified, 25 assets | Oanda 05-20 | FAIL (t=0.78; sens. max t=1.5) | untouched |

Eight strategy classes/cells tested; zero validated edges. Total spent on
eval fees finding this out: $0.

## What the verdicts mean

1. **Intraday TA on free 5m index data does not clear realistic costs.**
   Uniformly negative OOS with stop-first fills, 1-2 tick slippage, and
   commissions. Low PBO (2-8%) shows the grids rank consistently — the
   classes are simply unprofitable, not unstably ranked. This replicates
   the L2T2 meta-finding at 5-minute resolution.
2. **Single-index TSMOM is regime beta.** The SPX dev candidate (bull
   2010-2017) died on the first adversarial regime draw (Volmageddon +
   Q4-2018). The pre-registration + one-shot holdout caught it for free.
3. **Diversified TSMOM is real-but-thin here**: positive every way we cut
   it, never close to t>=2 on 13 years. At eval timescales (1-3 months =
   one regime draw) that is not a bankable edge.
4. **The eval math itself is the durable asset.** Given any genuinely
   validated daily return stream, the Monte Carlo machine converts it to
   P(pass) and an optimal size. Demonstration (synthetic Sharpe-2 stream,
   FTMO 100k Swing): P(pass) 93.5% phase 1 / 97.1% phase 2 at ~1.1x source
   size, EV ~ +$7k/attempt — and oversizing visibly destroys it (2.3x
   scale -> P(pass) drops to 62% via daily-loss busts).

## The recommendation (the "right answer")

The validated route to prop capital from here is **not** a strategy mined
from free data — it is plugging an externally-validated edge into the
sizing/rules machine:

1. **Feed L2T2 through the bridge.** The TQQQ system survived a full
   trust audit with live money. Export its daily P&L (or the vol-targeted
   QQQ-equivalent exposure stream) to CSV and run
   `scripts/eval_from_returns.py returns.csv --swing-only`. The output is
   the firm, size, P(pass), and EV decision. FTMO Swing allows overnight
   holding and EAs; the same exposure trades as NQ/MNQ futures or US100
   CFD. This is hours of work, not weeks, and it is the highest-EV move
   available.
2. **If the L2T2 stream clears the bridge with positive EV**: run the
   eval with the RiskGovernor enforcing the daily soft-stop and buffer
   reserve; sizes come from the optimizer, not vibes.
3. **Research channel for new edges** (after 1): per the audit, the
   surviving channel at intraday frequency is execution microstructure,
   which requires real tick/order-flow data (Databento CME, ~$50-200) —
   not more indicator search on bar data. Any new candidate goes through
   the same protocol: pre-registration, frozen grid, PBO, one-shot holdout.

## Cumulative trial ledger

36 intraday + 24 single-index daily + 3 diversified = 63 configurations
tested project-wide. Any future deflated-Sharpe computation on this
project's results must use at least this denominator.
