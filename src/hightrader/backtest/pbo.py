"""Probability of Backtest Overfitting via CSCV (Bailey et al. 2015).

Port of the single best overfitting detector from the L2T2 audit
(`src/core/pbo.ts` there): combinatorially symmetric cross-validation.

Given a matrix of per-period returns for N configurations over T periods:
split the T periods into S contiguous blocks; for every C(S, S/2) way to
pick half the blocks as in-sample, find the config with the best in-sample
score and look up its RANK out-of-sample. PBO = fraction of splits where
the in-sample winner ranks in the bottom half out-of-sample.

Calibration from the audit: pure noise -> PBO ~= 0.5; real edge -> < 0.15.
A grid with PBO near or above 0.5 is anti-predictive — in-sample winners
are systematically the OOS losers.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import List, Sequence

import numpy as np


@dataclass
class PBOResult:
    pbo: float
    n_splits: int
    n_configs: int
    median_oos_rank_of_is_winner: float  # 1.0 = best possible, 0.0 = worst

    def summary(self) -> str:
        return (
            f"PBO={self.pbo:.0%} over {self.n_splits} CSCV splits "
            f"({self.n_configs} configs); IS-winner median OOS rank pct="
            f"{self.median_oos_rank_of_is_winner:.0%}"
        )


def _sharpe(x: np.ndarray) -> float:
    sd = x.std(ddof=1)
    if sd == 0 or len(x) < 2:
        return 0.0
    return float(x.mean() / sd)


def cscv_pbo(
    returns_matrix: np.ndarray,
    n_blocks: int = 16,
) -> PBOResult:
    """returns_matrix: shape (n_periods, n_configs) of per-period PnL/returns.

    Scoring is the Sharpe of concatenated periods, computed from per-block
    sufficient statistics (sum, sumsq, count) so each of the C(S, S/2)
    splits costs O(n_configs) instead of re-touching every row.
    """
    T, N = returns_matrix.shape
    if N < 2:
        raise ValueError("need at least 2 configurations")
    edges = np.linspace(0, T, n_blocks + 1, dtype=int)
    b_sum = np.array(
        [returns_matrix[edges[i] : edges[i + 1]].sum(axis=0) for i in range(n_blocks)]
    )
    b_sumsq = np.array(
        [(returns_matrix[edges[i] : edges[i + 1]] ** 2).sum(axis=0) for i in range(n_blocks)]
    )
    b_n = np.array([edges[i + 1] - edges[i] for i in range(n_blocks)], dtype=float)

    def scores(block_ids) -> np.ndarray:
        n = b_n[list(block_ids)].sum()
        s = b_sum[list(block_ids)].sum(axis=0)
        ss = b_sumsq[list(block_ids)].sum(axis=0)
        mean = s / n
        var = np.maximum((ss - n * mean**2) / (n - 1), 0.0)
        sd = np.sqrt(var)
        with np.errstate(divide="ignore", invalid="ignore"):
            out = np.where(sd > 0, mean / sd, 0.0)
        return out

    below_median = 0
    ranks: List[float] = []
    splits = list(combinations(range(n_blocks), n_blocks // 2))
    for ins in splits:
        outs = tuple(b for b in range(n_blocks) if b not in ins)
        is_scores = scores(ins)
        oos_scores = scores(outs)
        winner = int(np.argmax(is_scores))
        # Rank percentile of the IS winner among OOS scores (1 = best).
        rank_pct = (oos_scores < oos_scores[winner]).sum() / (N - 1)
        ranks.append(rank_pct)
        if rank_pct < 0.5:
            below_median += 1

    return PBOResult(
        pbo=below_median / len(splits),
        n_splits=len(splits),
        n_configs=N,
        median_oos_rank_of_is_winner=float(np.median(ranks)),
    )


def daily_pnl_matrix(
    trade_lists: Sequence[Sequence],
    all_days: Sequence,
) -> np.ndarray:
    """Build (n_days, n_configs) daily PnL matrix from per-config trade lists."""
    day_index = {d: i for i, d in enumerate(all_days)}
    out = np.zeros((len(all_days), len(trade_lists)))
    for j, trades in enumerate(trade_lists):
        for t in trades:
            i = day_index.get(t.exit_time.date())
            if i is not None:
                out[i, j] += t.pnl
    return out
