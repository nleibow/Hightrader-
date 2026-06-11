"""CSCV PBO calibration, mirroring the L2T2 audit's calibration checks."""

import numpy as np

from hightrader.backtest.pbo import cscv_pbo


def test_pure_noise_pbo_near_half():
    rng = np.random.default_rng(5)
    mat = rng.normal(0, 1, size=(640, 20))
    res = cscv_pbo(mat, n_blocks=16)
    assert 0.3 < res.pbo < 0.7


def test_real_edge_pbo_low():
    rng = np.random.default_rng(6)
    mat = rng.normal(0, 1, size=(640, 20))
    mat[:, 7] += 0.25  # one config with genuine, persistent edge
    res = cscv_pbo(mat, n_blocks=16)
    assert res.pbo < 0.15
    assert res.median_oos_rank_of_is_winner > 0.8


def test_overfit_grid_pbo_high():
    # Configs that each win in one regime and lose in the other: in-sample
    # winners are systematically anti-predictive (the PBO=78% movie).
    rng = np.random.default_rng(8)
    T, N = 640, 16
    mat = rng.normal(0, 1, size=(T, N))
    regime = (np.arange(T) // 40) % 2
    for j in range(N):
        sign = 1 if j % 2 == 0 else -1
        mat[:, j] += sign * np.where(regime == 0, 0.3, -0.3)
    res = cscv_pbo(mat, n_blocks=16)
    assert res.pbo > 0.35
