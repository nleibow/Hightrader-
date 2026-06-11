# Pre-registered validation protocol — intraday prop-eval strategies

Registered: 2026-06-11, BEFORE any walk-forward or grid run on the real
datasets below. Follows the L2T2 audit discipline (PART3_PROTOCOL pattern):
declare everything first; failures die here and never touch the holdout.

## Data

- `NAS100_USD` (Oanda CFD, 1m -> 5m RTH 09:30-16:00 NY): 2005-01 .. 2020-05.
- `SPXUSD` (histdata, 1m -> 5m RTH): 2010-11 .. 2018-12.
- **Holdout**: the final 15% of sessions of each dataset (NAS100: ~mid-2018
  onward; SPX: ~mid-2017 onward) is touched EXACTLY ONCE, at the end, by the
  single pre-committed final configuration — not by any selection step.
  Development set: everything before it.

## Engine / leak checklist (verified before registration)

- Signals computed at bar close, filled at NEXT bar open + slippage.
- Stop fills before target when both are inside one bar.
- Costs (commission + slippage) applied inside every backtest, including
  selection-stage runs.
- ORB / momentum / meanrev indicators are backward-looking only
  (groupby-transform on opening-range bars; EWM indicators).
- Costs: NQ $2.25/side + 2 ticks slippage; ES $2.25/side + 1 tick.

## Strategies and grids (FROZEN — the full trial ledger)

Structural candidates only (each has a causal story; no indicator mining):

1. **OpeningRangeBreakout** — trend-day continuation after range expansion.
   Grid: range_bars in {3, 6, 12} x rr in {1.5, 2.5}. (6)
2. **TrendMomentum** — intraday trend persistence, pullback entry.
   Grid: (fast,slow) in {(9,21), (20,50)} x atr_mult in {1.5, 2.5} x rr in
   {1.5, 2.5}. (8)
3. **MeanReversion** — band-fade in chop.
   Grid: bb_std in {2.0, 2.5} x (rsi_low, rsi_high) in {(25,75), (20,80)}. (4)

18 configurations x 2 instruments. max_trades_per_day=3, 1 contract,
flat at session end. NO grid extensions after seeing results: if these fail,
the strategy class is dead for this data, not "needs more tuning".

## Walk-forward design

- Train 504 sessions (~2y), test 126 (~6mo), rolled by 126, on the
  development set only.
- Selection objective: per-trade PnL t-statistic, min 30 train trades.

## Success bar (ALL must hold on concatenated walk-forward OOS trades)

1. OOS expectancy > 0 after costs.
2. OOS per-trade t-stat >= 2.0.
3. >= 55% of test windows profitable.
4. OOS profit factor >= 1.10.
5. PBO (CSCV, 16 blocks, best-in-sample rank OOS) <= 35% for the strategy's
   grid on the development set.
6. Parameter plateau: the winning config's grid neighbors achieve >= 50% of
   its OOS expectancy (no isolated spikes).

Only a strategy passing ALL SIX advances to the holdout, Monte Carlo
pass-probability analysis, and any live consideration. If none passes, the
honest deliverable is "no validated signal edge in this data with these
classes" and the system's value rests on the structural layers (sizing,
rules engine, governor) applied to externally-validated signals.

## Trial ledger

- 18 configs x 2 instruments x ~20 walk-forward windows (selection)
- 18 configs x 2 instruments full-dev-period runs (for PBO)
- 6 (strategy x instrument) OOS aggregates compared against the bar
- Any deflated-Sharpe reporting uses N = 36 config-instrument trials.
