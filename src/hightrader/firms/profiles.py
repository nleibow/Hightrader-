"""Preset evaluation profiles for the major prop firms.

IMPORTANT: firms change these numbers frequently. These presets reflect the
commonly published rules as of early 2026 and exist so the simulator has
realistic defaults — ALWAYS verify against the firm's current rulebook
before trading, and adjust the dataclass fields to match.

Also verify each firm's automation policy: FTMO allows EAs (with restrictions
on shared/commercial EAs and tick-scalping exploits), Topstep allows
automation only while you supervise it, and Apex prohibits fully automated
trading. Violating those terms forfeits the account — this system includes a
human-supervision mode for firms that require it.
"""

from .rules import DrawdownMode, FirmProfile

FTMO_100K_PHASE1 = FirmProfile(
    name="FTMO 100k Challenge (Phase 1)",
    account_size=100_000,
    profit_target=10_000,
    max_total_drawdown=10_000,
    drawdown_mode=DrawdownMode.STATIC,
    max_daily_loss=5_000,
    min_trading_days=4,
    max_calendar_days=None,  # FTMO removed the 30-day time limit
    notes="Daily loss = day realized + open floating P&L vs initial balance.",
)

FTMO_100K_PHASE2 = FirmProfile(
    name="FTMO 100k Verification (Phase 2)",
    account_size=100_000,
    profit_target=5_000,
    max_total_drawdown=10_000,
    drawdown_mode=DrawdownMode.STATIC,
    max_daily_loss=5_000,
    min_trading_days=4,
)

TOPSTEP_50K = FirmProfile(
    name="Topstep 50k Combine",
    account_size=50_000,
    profit_target=3_000,
    max_total_drawdown=2_000,
    drawdown_mode=DrawdownMode.TRAILING_EOD,
    max_daily_loss=None,  # Topstep removed the daily loss limit on Combines
    min_trading_days=2,
    notes="Max Loss Limit trails EOD balance high and locks at initial balance.",
)

APEX_50K = FirmProfile(
    name="Apex 50k Full",
    account_size=50_000,
    profit_target=3_000,
    max_total_drawdown=2_500,
    drawdown_mode=DrawdownMode.TRAILING_INTRADAY,
    max_daily_loss=None,
    min_trading_days=1,
    trailing_lock_offset=100.0,
    notes="Threshold trails intraday equity highs; locks at initial + $100. "
    "Apex prohibits fully automated trading — supervision required.",
)

ALL_PROFILES = [FTMO_100K_PHASE1, FTMO_100K_PHASE2, TOPSTEP_50K, APEX_50K]
