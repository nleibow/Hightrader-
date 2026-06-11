# Protocol addendum 1 — daily-frequency structural candidates

Registered 2026-06-11, after the intraday protocol RUNS began but BEFORE any
daily-frequency backtest was run on this data, and independent of intraday
outcomes. Motivated by the L2T2 meta-finding: structural mechanisms
(documented risk premia, risk arithmetic) survive OOS; mined intraday TA
does not.

## Candidate class

**Time-series momentum (TSMOM) with volatility-targeted sizing**, daily
bars, on NAS100 (2005-2020) and SPX (2010-2018). Causal story: the
time-series momentum premium (Moskowitz-Ooi-Pedersen 2012 and 40 years of
managed-futures evidence) plus vol-targeting arithmetic (drag ~ sigma^2).
Suitable for FTMO-style swing accounts (overnight/weekend holding allowed);
NOT for intraday-only futures firms.

## Frozen grid (the entire trial budget for this addendum)

- Signal: sign of total return over lookback L in {63, 126, 252} sessions.
- Variants: long-only (flat when signal < 0) and long-short. (2)
- Sizing: vol-target 15% annualized via 20d realized vol, weight capped at
  1.0x notional (no leverage), vs fixed 1.0x. (2)

12 configs total per instrument. Execution: signal at close t, position
changed at open t+1, return measured open-to-open; costs = 1 tick + $2.25
commission per side per position change (NQ/ES micro-lot equivalents scale
linearly). No stops (the audit killed intraday stops on swing positions;
exits are signal flips / vol-target rebalances only; rebalance band 10% to
avoid cost churn).

## Success bar

Walk-forward as in the main protocol (train 504 / test 126 on dev set;
selection by daily-PnL t-stat). ALL must hold on concatenated OOS days:

1. OOS mean daily PnL > 0 after costs.
2. OOS daily t-stat >= 2.0.
3. >= 55% of test windows profitable.
4. PBO (12 configs, 16 blocks) <= 35%.
5. Regime honesty: OOS not net-negative in BOTH halves of the dev OOS span
   (no single-regime lottery tickets).
6. Plateau: lookback neighbors of the modal config >= 50% of its OOS mean
   daily PnL.

Pass -> single holdout shot (same 15% sessions), then Monte Carlo vs the
firm profiles that permit swing holding (FTMO).
