"""Offline Loom demo: run from the sample repo root; no reports or downloads."""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import subprocess
import sys

# Suppress bytecode before importing the sample, even without python -B.
sys.dont_write_bytecode = True


def normal_run(root: Path) -> None:
    """A1：读取随仓库提供的 CSV，只输出交易表。"""
    from sample.data import load_offline
    from sample.strategy import Config, backtest

    print("=== A1 | Normal offline run ===")
    bars = load_offline(root / "data/sample_btcusdt_1d.csv")
    equity, trades = backtest(bars, Config())
    print("Local candles:", len(bars))
    print("Equity rows:", len(equity))
    print("Closed trades:", len(trades))
    columns = ["entry_date", "entry_price", "exit_date", "exit_price", "exit_reason"]
    print(trades[columns].to_string(index=False) if len(trades) else "No closed trades.")


def gap_case() -> None:
    """A2：在内存中重建原 Loom A2 的五行数据与配置。"""
    import pandas as pd
    from sample.strategy import Config, backtest

    print("=== A2 | Gap below stop ===")
    closes = [10, 8, 9, 10, 10]
    bars = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=5, freq="D"),
        "open": [10, 8, 9, 12, 9],
        "high": [value + 1 for value in closes],
        "low": [9.75, 7.75, 8.75, 11.5, 8],
        "close": closes,
        "volume": [1] * 5,
    })
    _, trades = backtest(bars, Config(
        fast_length=1, slow_length=2, initial_cash=100,
        stop_percent=0.1, commission_rate=0,
    ))
    if len(trades) != 1:
        raise ValueError("Expected one closed gap trade")
    trade = trades.iloc[0]
    stop = 12 * (1 - 0.1)
    print("Entry:", trade.entry_price)
    print("Stop level:", stop)
    print("Gap open:", bars.open.iloc[-1])
    print("Actual exit:", trade.exit_price)
    try:
        # Explicit raise also keeps this demonstration valid under python -O.
        if not math.isclose(trade.exit_price, stop):
            raise AssertionError("Wrong assumption: fill at stop despite gap")
    except AssertionError as error:
        print("CAUGHT:", error)
    else:
        raise ValueError("Wrong fill-at-stop assumption was not caught")
    if not (trade.entry_price == 12 and trade.exit_price == 9 and trade.exit_reason == "stop"):
        raise ValueError("Correct gap check failed")
    print("Correct gap check: PASS")
    print("The rejected expectation is intentional; it is not an engine bug.")


def regression_checks(root: Path) -> bool:
    """A3：隔离 pytest 输出，关闭外部插件、字节码和缓存写入。"""
    print("=== A3 | Named regression checks ===")
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTEST_ADDOPTS="")
    env.pop("PYTEST_DEBUG", None)
    passed = True
    for name in (
        "test_signal_at_close_fills_at_next_bar_open",
        "test_gap_below_stop_fills_at_open",
    ):
        result = subprocess.run(
            [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=no",
             f"tests/test_strategy.py::{name}"],
            cwd=root, env=env, capture_output=True, text=True, check=False,
        )
        ok = result.returncode == 0
        # Raw pytest diagnostics can contain local paths; show name and status only.
        print(f"{name}: {'PASS' if ok else 'FAIL'} (exit {result.returncode})")
        passed = passed and ok
    return passed


def main() -> int:
    """从当前工作目录定位仓库，支持一次运行或分段录制。"""
    parser = argparse.ArgumentParser(description="Offline Loom demo; run from the sample repo root.")
    parser.add_argument("--section", choices=("all", "a1", "a2", "a3"), default="all")
    parser.add_argument("--run-tests", action="store_true", help="Include A3 with all sections.")
    parser.add_argument("--pause", action="store_true", help="Wait for Enter between sections.")
    args = parser.parse_args()
    root = Path.cwd()
    if not all((root / name).is_file() for name in (
        "sample/strategy.py", "sample/data.py", "data/sample_btcusdt_1d.csv",
    )):
        print("Demo: FAIL. Run from the sample repo root.", file=sys.stderr)
        return 1
    sys.path.insert(0, str(root))
    sections = [args.section] if args.section != "all" else ["a1", "a2", "a3"]
    for index, section in enumerate(sections):
        if index:
            print()
            if args.pause:
                input("Press Enter for the next section...")
        if section == "a1":
            normal_run(root)
        elif section == "a2":
            gap_case()
        elif args.run_tests or args.section == "a3":
            if not regression_checks(root):
                return 1
        else:
            print("=== A3 | Named regression checks ===")
            print("Skipped. Add --run-tests or use --section a3.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Exception, KeyboardInterrupt) as error:
        # Exception messages and tracebacks may expose absolute paths.
        print(f"Demo: FAIL ({type(error).__name__}). Check data and installed requirements.", file=sys.stderr)
        sys.exit(1)
