# Hightrader

An automated system for passing prop firm evaluations — built on the premise
that an eval is a **stochastic control problem**, not a search for a magic
signal.

## The thesis

A prop eval (FTMO, Topstep, Apex, …) asks you to hit a profit target
(~6% of buying-power-equivalent) before breaching a drawdown rule (~2–10%).
Three facts follow from the math, and this repo operationalizes all three:

1. **Below a minimum edge, nothing helps.** A zero-edge strategy passes a
   symmetric eval ≤50% of the time and you bleed fees forever (gambler's
   ruin). Run `scripts/edge_requirements.py` to see the exact boundary per
   firm. Sample output: at 3 trades/day, **45% win rate at 1.5:1 payoff is
   near-certain to pass FTMO at optimal size, while 40%/1.0 passes 6% of
   the time** — the cliff is sharp.

2. **Above that edge, position sizing is most of the game.** P(pass) as a
   function of risk-per-trade has an interior maximum: too small and you
   never reach target, too big and the trailing drawdown eats you. The
   Monte Carlo engine (`hightrader.montecarlo`) bootstraps your actual
   backtest trades *day-by-day* (preserving intraday correlation, which is
   what makes daily-loss rules bite) through each firm's exact rule
   mechanics and finds that maximum. Adaptive policies (`buffer_scaled`,
   `coast_to_target`) squeeze out more.

3. **Most eval failures are risk failures, not strategy failures.** The
   `RiskGovernor` makes them structurally impossible in live trading: soft
   daily stops inside the firm's limit, a reserved drawdown buffer for
   slippage/gaps, per-trade risk caps as a fraction of *remaining* buffer,
   trade-count limits, and a kill switch on an independent code path.

## What's here

```
src/hightrader/
  firms/        exact rule engines: static DD (FTMO), trailing-EOD (Topstep),
                trailing-intraday (Apex), daily loss, consistency, min days
  backtest/     conservative bar engine (stop fills before target, slippage
                + commission on every side) and trade statistics
  strategies/   baselines: Opening Range Breakout, trend momentum, mean
                reversion — parameterized, no lookahead
  montecarlo/   bootstrap day-blocks -> P(pass), risk sweeps, sizing policies,
                fee-adjusted EV optimizer
  risk/         live RiskGovernor + position sizing
  live/         broker abstraction, paper broker, supervised LiveRunner
scripts/
  run_pipeline.py        data -> backtest -> P(pass) tables per firm
  edge_requirements.py   how much edge do you need? (win-rate x payoff grids)
infra/          Dockerfile + AWS deployment notes (spot batch research,
                supervised live runner, watchdog flatten path)
```

## Quickstart

```bash
uv venv && uv pip install -e ".[dev]"
python -m pytest                      # 29 tests: rule mechanics, fills, MC sanity
python scripts/run_pipeline.py        # full pipeline on synthetic data
python scripts/edge_requirements.py   # minimum-edge grids per firm
python scripts/run_pipeline.py --csv your_5min_bars.csv --strategy orb
```

## The honest part (read this)

- **The included strategies are credible baselines, not validated edges.**
  The demo runs on synthetic data and the pipeline will happily tell you a
  strategy is bad (the demo ORB run shows PF 0.79 — and the MC then shows
  you'd still pass ~20% of evals on pure variance, which is precisely the
  prop firms' business model). Edge must be earned on real intraday data
  with walk-forward validation before an eval fee is worth paying.
- **`funded_value` in the EV optimizer must be conditional on your edge.**
  If your strategy is negative-expectancy, your expected payout from a
  funded account is ~one or two lucky payouts, not a career — don't let a
  generous assumption there justify buying evals.
- **Firm rules drift.** The presets in `firms/profiles.py` are commonly
  published values (early 2026); verify against the current rulebook and
  edit the dataclass — everything downstream adapts.
- **Automation policies differ.** FTMO permits EAs (with restrictions),
  Topstep requires you to supervise automation, Apex prohibits full
  automation. The `LiveRunner` is built to run supervised with a human
  kill switch. Account-copying services, group passing, and demo-feed
  exploits are fraud under firm terms and are not part of this system.

## Validation campaign results (2026-06-11)

A full pre-registered validation campaign was run on real data (16y of
NAS100 and 8y of SPX minute bars; 25-instrument multi-asset daily universe).
**See FINDINGS.md for the scoreboard and the recommendation.** Headline:
eight strategy classes tested under PROTOCOL.md discipline (frozen grids,
CSCV PBO, one-shot holdouts); zero cleared the bar; the SPX TSMOM dev
candidate was killed by the 2018-regime holdout. The bankable path is
`scripts/eval_from_returns.py`: feed any externally-validated daily P&L
stream through the firm-rules Monte Carlo to get firm, size, P(pass), EV.

## Roadmap

1. Feed the L2T2 (or any live-validated) daily P&L through
   `eval_from_returns.py`; if EV > 0, trade the eval under the RiskGovernor.
2. Execution-microstructure research on real tick data (Databento CME) —
   the one surviving intraday channel; same protocol discipline.
3. Broker adapters: MetaTrader 5 (FTMO-style) and Tradovate (Topstep-style)
   implementing `live.Broker`.
4. Funded-phase mode: same machinery, payout-rule profiles, lower risk.
