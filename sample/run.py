"""Run offline sample or fetch the public Binance history and write reports."""
from __future__ import annotations
import argparse
import os
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = ROOT / "reports"
import pandas as pd
from .data import fetch_binance, load_offline
from .strategy import Config, backtest, performance

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="use bundled ~300-row CSV")
    args = parser.parse_args()
    reports = REPORT_ROOT / ("offline" if args.offline else "online")
    reports.mkdir(parents=True, exist_ok=True)
    (reports / ".mplconfig").mkdir(exist_ok=True)
    (reports / ".cache").mkdir(exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(reports / ".mplconfig")
    os.environ["XDG_CACHE_HOME"] = str(reports / ".cache")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    bars = load_offline(ROOT / "data/sample_btcusdt_1d.csv") if args.offline else fetch_binance(
        int(pd.Timestamp("2021-01-01", tz="UTC").timestamp() * 1000))
    config = Config()
    equity, trades = backtest(bars, config)
    stats = performance(equity, trades, config.initial_cash)
    bh = config.initial_cash * float(bars.close.iloc[-1]) / float(bars.close.iloc[0])
    stats["buy_hold_return"] = bh / config.initial_cash - 1
    reports.mkdir(parents=True, exist_ok=True)
    dates = [datetime.fromisoformat(str(value)) for value in equity.date]
    equity.to_csv(reports / "equity.csv", index=False)
    trades.to_csv(reports / "trades.csv", index=False)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(dates, equity.equity, label="Strategy")
    ax.plot(dates, config.initial_cash * bars.close / bars.close.iloc[0], label="Buy and hold", alpha=.7)
    ax.set(title="BTCUSDT daily EMA crossover equity", ylabel="Equity (USDT)"); ax.legend(); ax.grid(alpha=.2)
    fig.tight_layout(); fig.savefig(reports / "equity.png", dpi=150); plt.close(fig)
    peak = equity.equity.cummax()
    dd = equity.equity / peak - 1
    fig, ax = plt.subplots(figsize=(10, 3)); ax.fill_between(dates, dd, 0, color="firebrick", alpha=.5)
    ax.set(title="Strategy drawdown", ylabel="Drawdown", ylim=(min(-.01, float(dd.min()) * 1.1), .01)); ax.grid(alpha=.2)
    fig.tight_layout(); fig.savefig(reports / "drawdown.png", dpi=150); plt.close(fig)
    reports.joinpath("report.md").write_text(
        "# Backtest report\n\nResearch sample; results are historical and not predictive.\n\n"
        f"Data: {'bundled offline sample' if args.offline else 'Binance BTCUSDT daily candles from 2021-01-01'} ({len(bars)} bars, {bars.date.iloc[0]} to {bars.date.iloc[-1]}).\n\n"
        "| Metric | Strategy | Buy and hold |\n|---|---:|---:|\n"
        f"| Total return | {stats['total_return']:.2%} | {stats['buy_hold_return']:.2%} |\n"
        f"| Annualized return | {stats['annualized_return']:.2%} | — |\n"
        f"| Maximum drawdown | {stats['max_drawdown']:.2%} | — |\n"
        f"| Sharpe (daily, 365 days) | {stats['sharpe']:.3f} | — |\n"
        f"| Win rate (closed trades) | {stats['win_rate']:.2%} | — |\n"
        f"| Closed trades | {stats['trade_count']} | 1 buy and hold |\n\n"
        "See `equity.png`, `drawdown.png`, and `trades.csv`.\n", encoding="utf-8")
    print(f"Mode: {'offline' if args.offline else 'online'}; bars: {len(bars)}; period: {bars.date.iloc[0]} to {bars.date.iloc[-1]}")
    print("Reports:", reports)
    for key, value in stats.items():
        print(f"{key}: {value:.6f}" if isinstance(value, float) else f"{key}: {value}")


if __name__ == "__main__":
    main()
