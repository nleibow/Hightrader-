# Protocol addendum 3 — execution-microstructure channel (ES/MES tick data)

Registered 2026-06-11, BEFORE any Databento tick/MBP-1 pull and BEFORE any
analysis of tick-level data. This is the one surviving intraday research
channel from the L2T2 audit (FINDINGS.md §3): measure execution reality
instead of mining more signals on bar data.

## Data already on disk (inventoried before registration; no new cost)

From the Breakout project (`~/Desktop/Breakout/data/raw/`, Databento
GLBX.MDP3 exports, plus broker bar exports):

- 1m bars, all contract months: MES / MNQ / MYM / M2K / MCL / MGC,
  2024-04-01 → 2026-03-30 (~2 years).
- 1m bars, 2026-02-27 → 2026-03-30 only: ES, NQ, RTY, YM, MBT.
- 5m bars: ES 2023-01-02 → 2026-03-30 (and the same set of symbols as 1m).
- None of this is tick/MBP-1 data; it cannot answer the fill-model
  questions. It WILL be used for: session vol stratification (sampling
  design below), and as the bar series for the re-costing in hypothesis B.

## New data to pull (GLBX.MDP3), with cost control

Target window: 2024-04-01 → 2026-03-31 (matches the bar inventory; ~2y).

1. **trades**, ES lead-month (continuous `ES.v.0` or parent `ES.FUT`
   filtered to lead), full window — needed for hypotheses A and C.
2. **trades**, MES lead-month, full window — micro-vs-mini spread/cost
   comparison (evals trade micros first).
3. **mbp-1** (top of book), ES lead-month, a **stratified day sample**,
   not the full window: sessions are ranked by realized vol (computed
   from the on-disk 1m bars), and we sample equally from each vol
   quintile, alternating across the two years, minimum 40 sessions. The
   sample is sized DOWN from the budget, never up from the results; the
   selection seed is fixed at 11 and the day list is committed before any
   MBP-1 analysis runs.

Cost rules (binding):
- `metadata.get_cost` is called for every (dataset, schema, symbols,
  range) BEFORE the corresponding download; the estimate is recorded in
  the verdict file.
- Anything totaling over $25 requires explicit user confirmation first.
- Every pull is cached to parquet under `data/databento/` immediately;
  nothing is ever re-downloaded.
- RTH filtering (we only analyze 09:00–16:00 ET) is applied locally after
  download.

## Hypothesis A — measured fill models (descriptive; no trial-ledger cost)

From ES MBP-1 + trades, by time-of-day bucket (09:30 open auction,
09:30–11:30, 11:30–14:00, 14:00–16:00) and vol quintile, measure:

- effective spread (trade price vs prevailing mid) and quoted spread;
- top-of-book depth and queue dynamics (add/cancel/fill rates at touch);
- for a hypothetical **market order**: expected cost = half effective
  spread (+ depth-exceedance check for 1-lot: does top level ever fail to
  cover it — for ES/MES essentially never, verify);
- for a **marketable-limit**: same, plus non-fill probability when the
  touch moves away within 1s;
- for a **passive limit at the touch**: fill probability within horizon h
  ∈ {1min, 5min} as a function of queue position estimated from MBP-1
  (order joins end of current queue; queue ahead depletes via observed
  trades + cancels pro-rata), and the adverse-selection cost conditional
  on fill (mid move from order placement to h after fill).

Output: `results/addendum3/fill_models.json` — a cost table replacing the
engine's assumed flat 1–2 tick slippage. This is measurement, not
selection; nothing here consumes the trial ledger.

## Hypothesis B — re-cost the dead intraday classes (NOT new signal search)

The PROTOCOL.md verdict killed ORB / TrendMomentum / MeanReversion with
assumed costs (market-order fills, 1–2 ticks slippage + commission). If
measured passive-limit execution is materially cheaper, the honest move is
to re-run the SAME frozen 18-config grid, unchanged walk-forward, on ES
5m bars (2023-01 → 2026-03, on disk), under the measured fill model from
A — entries as passive limits at the signal bar's close touch (fill
probability + adverse selection from the measured model, missed fills =
missed trades), exits per original rules with stop exits as market
orders at measured market-order cost.

- Grid, walk-forward, and all six success-bar gates are IDENTICAL to
  PROTOCOL.md. No parameter may be added or changed.
- This consumes **18 trial-ledger entries** (18 configs × 1 instrument;
  re-costing is a new test of an old hypothesis, counted honestly).
- The 2023→2026 ES data has never been used for selection in this
  project (original intraday protocol used NAS100 ≤2020-05 and SPX
  ≤2018-12). **Holdout: final 15% of ES sessions (~2025-10 → 2026-03),
  one shot, only if a class passes all six gates on the dev 85%.**
- Expected outcome stated up front: passive fills save ~1 tick/side but
  add non-fill selection bias against you (you get filled when flow goes
  through you). If the measured adverse selection eats the spread saving,
  the classes stay dead and we say so.

## Hypothesis C — ONE order-flow candidate (frozen micro-grid)

Causal story: short-horizon signed trade-imbalance predicts continuation
in the direction of informed flow, strongest in the high-participation
morning session (documented order-flow literature; not mined here).

- Signal: rolling signed trade imbalance I(w) = (buy volume − sell
  volume) / total volume over trailing window w, aggressor side from the
  trades feed. At each minute boundary in 09:30–11:30 ET, if I(w) z-score
  (vs trailing 20-session distribution of I(w) at that minute-of-day)
  exceeds +2 → long; below −2 → short.
- Frozen grid: w ∈ {1min, 5min} × holding period h ∈ {5min, 15min} —
  **4 configs, the entire budget**. One position at a time, exit at
  h or 11:30 ET hard flat, whichever first. No stops (horizon exit only).
- Instrument: ES lead month, 1 contract. Entry at next trade price after
  signal + measured market-order cost from A (both sides) + $2.25/side
  commission. (Market-order costing — deliberately the conservative model.)
- Walk-forward: train 252 sessions / test 63 / step 63 on the dev 85% of
  the trades window; selection by per-trade t-stat as in PROTOCOL.md.
- Success bar: ALL SIX gates of PROTOCOL.md, verbatim (PBO computed on
  the 4-config grid, 16 blocks). Pass → one shot at the final-15%
  holdout (same sessions reserved as in B).
- Consumes **4 trial-ledger entries**. If it fails, signed-imbalance
  momentum at these horizons is dead on this data; no window/threshold
  extensions.

## Trial ledger

63 (prior) + 18 (B) + 4 (C) = **85 project-wide configurations** after
this addendum completes. Hypothesis A is descriptive measurement and adds
zero.

## Kill conditions / honesty clauses

- If `metadata.get_cost` shows the trades pulls alone exceed the budget
  envelope materially, we stop and ask — the protocol does not authorize
  spend, only the analysis once data exists.
- The MBP-1 day sample is fixed before analysis; no day may be added or
  removed after fill-model numbers are seen.
- If A's measured costs are WORSE than the assumed 1–2 ticks (entirely
  possible at the open), B is reported as "deader than believed" with the
  same prominence a resurrection would have received.
- The SPX and NAS100 holdouts remain spent; nothing here touches them.
