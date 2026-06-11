// Export L2T2 daily strategy returns for the prop-eval bridge.
//
// READ-ONLY with respect to ~/Desktop/l2t2: imports its engine + DB, writes
// CSVs into the Hightrader repo only. Reproduces the exact audited pipeline
// from l2t2/src/sizing-experiment.ts (branch fable5/edge-and-trust) under the
// MOO execution model recommended by EDGE_REPORT.md (next_open + 2 bps,
// costs 0.05%/leg, hysteresis deadband 0.05).
//
// Streams exported (full period, with dev/holdout boundary in meta):
//   bh_voltarget_55    — vol-targeted B&H (EDGE_REPORT recommended: no mining ancestry)
//   live_voltarget_55  — live config + voltarget overlay (belt & suspenders)
//   live_none          — live config, binary all-in (insurance layer alone)
//
// Run: cd ~/Desktop/l2t2 && npx tsx ~/Desktop/Hightrader-/scripts/export_l2t2_returns.ts

import fs from 'node:fs';
import path from 'node:path';
import { initDb, getPrices } from '/Users/nate/Desktop/l2t2/src/core/db.js';
import { runWeightedBacktest, type BacktestOptions } from '/Users/nate/Desktop/l2t2/src/core/backtest-engine.js';
import {
  computeVotedSignals,
  buildFilteredSignals,
  precomputeAllMAs,
  ALL_MA_TYPES,
  ALL_PERIODS,
} from '/Users/nate/Desktop/l2t2/src/core/trend-filters.js';
import type { OHLCV, Signal, IndicatorConfig } from '/Users/nate/Desktop/l2t2/src/core/types.js';

const L2T2 = '/Users/nate/Desktop/l2t2';
const OUT_DIR = '/Users/nate/Desktop/Hightrader-/results/l2t2_bridge';

const HOLDOUT_FRAC = 0.2; // identical to sizing-experiment.ts
const TX = 0.0005;
const MOO: BacktestOptions = {
  transactionCostPct: TX,
  execution: { mode: 'next_open', lagBars: 1, slippageBps: 2, volSlippageK: 0 },
};
const DEADBAND = 0.05;
const SQRT252 = Math.sqrt(252);

function trailingVol(prices: OHLCV[], window = 20): number[] {
  const n = prices.length;
  const rets: number[] = new Array(n).fill(0);
  for (let i = 1; i < n; i++) rets[i] = prices[i].close / prices[i - 1].close - 1;
  const out: number[] = new Array(n).fill(NaN);
  for (let i = window; i < n; i++) {
    let s = 0;
    for (let j = i - window + 1; j <= i; j++) s += rets[j];
    const mean = s / window;
    let v = 0;
    for (let j = i - window + 1; j <= i; j++) v += (rets[j] - mean) ** 2;
    out[i] = Math.sqrt(v / (window - 1)) * SQRT252;
  }
  return out;
}

function applyDeadband(raw: number[], deadband = DEADBAND): number[] {
  const out: number[] = new Array(raw.length);
  let held = 0;
  for (let i = 0; i < raw.length; i++) {
    const target = raw[i];
    if (target === 0 || held === 0 || Math.abs(target - held) > deadband) held = target;
    out[i] = held;
  }
  return out;
}

const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));

function voltarget55(signals: number[], vol20: number[]): number[] {
  return applyDeadband(signals.map((x, i) => x * (isNaN(vol20[i]) ? 1 : clamp(0.55 / vol20[i], 0, 1))));
}

function main() {
  initDb();
  const prices = getPrices();
  const n = prices.length;
  const devEnd = Math.floor(n * (1 - HOLDOUT_FRAC)) - 1;
  console.log(`${n} bars ${prices[0].date} → ${prices[n - 1].date}; devEnd=${prices[devEnd].date}`);

  const closes = prices.map(p => p.close);
  const vol20 = trailingVol(prices);
  const maCache = precomputeAllMAs(closes, ALL_MA_TYPES, ALL_PERIODS);

  const live = JSON.parse(fs.readFileSync(path.join(L2T2, 'data/live_strategy.json'), 'utf-8'));
  const liveBase = computeVotedSignals(
    prices, live.indicators as IndicatorConfig[],
    `${live.voting.rule}_${live.voting.threshold}`, { threshold: live.voting.threshold },
  );
  const liveSignals = buildFilteredSignals(liveBase, closes, maCache, {
    maType: 'ema', period: 20, method: 'band', bandPct: 0.05, downtrendBehavior: 'trust_osc',
  });
  const bhSignals: Signal[] = prices.map(() => 1 as Signal);

  const streams: Record<string, number[]> = {
    bh_voltarget_55: voltarget55(bhSignals as number[], vol20),
    live_voltarget_55: voltarget55(liveSignals as number[], vol20),
    live_none: (liveSignals as number[]).slice(),
  };

  fs.mkdirSync(OUT_DIR, { recursive: true });
  const meta: any = {
    source: 'l2t2 fable5/edge-and-trust, MOO execution (next_open+2bps, 0.05%/leg)',
    period: { start: prices[0].date, end: prices[n - 1].date, bars: n },
    devEnd: prices[devEnd].date,
    summaries: {},
  };

  for (const [name, weights] of Object.entries(streams)) {
    const bt = runWeightedBacktest(weights, prices, 0, n - 1, MOO);
    const eq = bt.equityCurve; // length n+1, eq[0]=1
    const lines = ['date,return'];
    for (let i = 1; i < eq.length; i++) {
      lines.push(`${prices[i - 1].date.slice(0, 10)},${(eq[i] / eq[i - 1] - 1).toFixed(8)}`);
    }
    const file = path.join(OUT_DIR, `${name}.csv`);
    fs.writeFileSync(file, lines.join('\n') + '\n');
    meta.summaries[name] = {
      cagr: bt.annualizedReturn, sharpe: bt.sharpeRatio, maxDrawdown: bt.maxDrawdown,
    };
    console.log(`${name}: CAGR ${(bt.annualizedReturn * 100).toFixed(1)}% Sharpe ${bt.sharpeRatio.toFixed(2)} MaxDD ${(bt.maxDrawdown * 100).toFixed(1)}% -> ${file}`);
  }

  fs.writeFileSync(path.join(OUT_DIR, 'meta.json'), JSON.stringify(meta, null, 2));
}

main();
