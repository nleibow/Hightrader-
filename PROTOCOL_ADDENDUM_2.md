# Protocol addendum 2 — diversified multi-asset TSMOM (single config)

Registered 2026-06-11, BEFORE any multi-asset run. The SPX holdout is spent
(candidate killed); this addendum uses different series whose holdouts are
untouched.

## Rationale

Single-index TSMOM failed the holdout (it is mostly equity beta timing).
The documented time-series-momentum premium (Moskowitz-Ooi-Pedersen 2012;
a century of managed-futures evidence) is a DIVERSIFIED phenomenon: sign of
trailing return per asset, vol-weighted, across many lowly-correlated
markets. Diversification is arithmetic, not a fitted pattern. An FTMO swing
account trades FX, indices, metals, commodities CFDs — this portfolio is
implementable there.

## Universe (inclusion rule, fixed before looking at returns)

All Oanda instruments in the dataset with >= 8 years of development data:
FX majors/crosses, equity indices, bonds, commodities, gold. No
per-instrument selection beyond the data-coverage rule. NAS100 and SPX500
are included (their earlier single-index failure does not exclude them from
a portfolio).

## THE configuration (exactly one; no grid, no selection)

- Signal per asset: sign of 252-session total return (the canonical 12-month
  lookback), long-short.
- Weight per asset: (0.40 / N) / sigma_i, sigma_i = 60d realized annualized
  vol, capped at 3x equal-notional; i.e. equal-risk weights scaled so the
  portfolio targets roughly 40%/sqrt(N)-style risk parity normalized to a
  10% annual portfolio vol at N assets (implemented as: target portfolio
  vol 10%, equal risk contribution assumption, per-asset weight =
  10% / (N * sigma_i), cap 3/N notional).
- Rebalance weekly (every 5 sessions) at next session open; 25% band.
- Costs: 3 bps of traded notional per side, all instruments (conservative
  for FX majors/indices, about right for commodity CFDs).
- Daily bars = NY-calendar-day aggregation of the full 24h session.

Sensitivity (reported for context, NOT used for selection): lookback 126,
monthly rebalance. The primary verdict rests on the single config above.

## Success bar (dev set = first 85% of sessions)

1. Mean daily PnL > 0 after costs.
2. Daily-PnL t-stat >= 2.0 on the dev set.
3. Both dev halves positive.
4. Max drawdown on dev, at 10% vol scaling, <= 20% of notional (an eval
   cannot survive a strategy that routinely draws 2x its annual vol).

Pass -> single holdout shot on the final 15% of sessions (includes the
2020 COVID regime for most instruments). Confirmed = positive holdout mean
daily PnL. Then Monte Carlo vs FTMO swing profiles.

## Trial ledger

One primary configuration. Two sensitivity variants reported but not
selectable. Cumulative project trials to date (for any deflated metric):
36 intraday + 24 daily single-index + 3 here = 63.
