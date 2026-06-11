# Running on AWS

## Research / backtesting (batch)

Backtests and Monte Carlo sweeps are embarrassingly parallel. The cheap way:

1. Build the image: `docker build -f infra/Dockerfile -t hightrader .`
2. Push to ECR.
3. Run parameter sweeps on **EC2 Spot** (c7i/c7a, compute-optimized) or
   **AWS Batch** with a job per (strategy, params, instrument) cell.
4. Write results (trade lists as parquet/CSV + the `EvalResult` rows) to S3;
   aggregate locally or in Athena.

A full 5-year 1-minute backtest + 5k-sim Monte Carlo runs in minutes on a
single core — you need many cores only for walk-forward grids. A spot
c7a.8xlarge (~$0.6/hr spot) chews through thousands of cells per hour.

## Data

- **Databento** (CME futures, per-GB pricing) or **Polygon** for real
  intraday history. Store raw pulls in S3, cache locally as parquet.
- yfinance is wired in for smoke tests only (60 days of 5m bars max).

## Live execution

- One small instance (t3.small is plenty) per account, in **us-east-1 /
  us-east-2** (close to CME/broker gateways in Aurora/NY4).
- Run the `LiveRunner` under systemd or ECS with auto-restart; the
  `RiskGovernor` halts trading on restart-loops (halted state persists to
  disk — wire `kill_switch` to an SNS alarm button on your phone).
- Credentials in **SSM Parameter Store / Secrets Manager**, never in env files.
- CloudWatch alarm on heartbeat metric: if the runner misses 2 heartbeats,
  trigger a Lambda that calls the broker's flatten-all REST endpoint
  directly (independent code path from the bot).
- Remember: some firms (Apex) require a human supervising the automation.
  The runner is designed to be supervised — keep it that way where required.

## Cost reality check

Research: <$20/mo if you use spot and shut things down.
Live: ~$15/mo per account instance. Data is the real cost ($50–200/mo).
