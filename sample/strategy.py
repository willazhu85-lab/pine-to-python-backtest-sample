"""A small, explicit daily-bar engine mirroring pine/ma_crossover.pine."""
from __future__ import annotations

from dataclasses import dataclass
import math
from datetime import datetime
import pandas as pd


@dataclass(frozen=True)
class Config:
    fast_length: int = 20
    slow_length: int = 50
    stop_percent: float = 0.05
    commission_rate: float = 0.001  # Pine commission_value=0.1 percent
    slippage_ticks: int = 0         # Pine slippage=0 ticks
    tick_size: float = 0.01
    initial_cash: float = 10_000.0


def indicators(bars: pd.DataFrame, config: Config = Config()) -> pd.DataFrame:
    """Add EMA and crossing columns; Pine ta.ema seeds with first source value."""
    out = bars.copy()
    # adjust=False uses the recursive EMA; with no min_periods it seeds at the
    # first close, matching ta.ema's first non-na source initialization.
    out["fast_ema"] = out["close"].ewm(span=config.fast_length, adjust=False).mean()
    out["slow_ema"] = out["close"].ewm(span=config.slow_length, adjust=False).mean()
    prev_fast, prev_slow = out.fast_ema.shift(1), out.slow_ema.shift(1)
    # Pine ta.crossover(a,b): a > b now and a[1] <= b[1].
    out["cross_up"] = (out.fast_ema > out.slow_ema) & (prev_fast <= prev_slow)
    # Pine ta.crossunder(a,b): a < b now and a[1] >= b[1].
    out["cross_down"] = (out.fast_ema < out.slow_ema) & (prev_fast >= prev_slow)
    return out


def backtest(bars: pd.DataFrame, config: Config = Config()) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Long-only, all-equity daily backtest. Returns (equity curve, trades)."""
    df = indicators(bars, config).reset_index(drop=False)
    date_col = "date" if "date" in df else df.columns[0]
    cash, qty, entry_price, stop_price = config.initial_cash, 0.0, None, None
    pending = None
    trades: list[dict] = []
    curve: list[dict] = []
    active_trade = None
    slip = config.slippage_ticks * config.tick_size

    for i, row in df.iterrows():
        date = row[date_col]
        # Orders generated at the previous close fill at this bar's open, as
        # with Pine's default process_orders_on_close=false.
        if pending == "entry" and qty == 0:
            fill = float(row.open) + slip
            # Pine's percent-of-equity sizing is based on equity/notional;
            # commissions are then charged on top of the order notional.
            qty = cash / fill
            fee = qty * fill * config.commission_rate
            cash -= qty * fill + fee
            entry_price = fill
            stop_price = fill * (1 - config.stop_percent)
            active_trade = {"entry_date": date, "entry_price": fill, "quantity": qty,
                            "entry_fee": fee, "exit_date": None, "exit_price": None,
                            "exit_fee": None, "exit_reason": None}
            pending = None
        elif pending == "exit" and qty > 0:
            fill = float(row.open) - slip
            fee = qty * fill * config.commission_rate
            cash += qty * fill - fee
            active_trade.update(exit_date=date, exit_price=fill, exit_fee=fee,
                                exit_reason="crossunder")
            trades.append(active_trade)
            qty, entry_price, stop_price, active_trade, pending = 0.0, None, None, None, None

        # Stop is active from the bar after entry. A gap through the stop fills
        # at the open; otherwise it fills at stop price (then sell slippage).
        if qty > 0 and active_trade is not None and active_trade["entry_date"] != date:
            if float(row.open) <= stop_price or float(row.low) <= stop_price:
                raw_fill = min(float(row.open), stop_price)
                fill = raw_fill - slip
                fee = qty * fill * config.commission_rate
                cash += qty * fill - fee
                active_trade.update(exit_date=date, exit_price=fill, exit_fee=fee,
                                    exit_reason="stop")
                trades.append(active_trade)
                qty, entry_price, stop_price, active_trade, pending = 0.0, None, None, None, None

        # Signals at close schedule next bar's open order. Opposing signals
        # only act when a position exists, matching the Pine strategy calls.
        if qty == 0 and bool(row.cross_up) and i + 1 < len(df):
            pending = "entry"
        elif qty > 0 and bool(row.cross_down) and i + 1 < len(df):
            pending = "exit"

        equity = cash + qty * float(row.close)
        curve.append({"date": date, "equity": equity, "cash": cash, "position_qty": qty})

    # Mark any open trade at the final close for portfolio equity; leave it out
    # of closed-trade statistics because no exit order was filled.
    return pd.DataFrame(curve), pd.DataFrame(trades)


def performance(equity: pd.DataFrame, trades: pd.DataFrame, initial_cash: float = 10_000.0) -> dict:
    values = equity.equity.astype(float)
    daily = values.pct_change().dropna()
    total = values.iloc[-1] / initial_cash - 1 if len(values) else 0.0
    first, last = equity.date.iloc[0], equity.date.iloc[-1]
    first = first.to_pydatetime() if hasattr(first, "to_pydatetime") else datetime.fromisoformat(str(first))
    last = last.to_pydatetime() if hasattr(last, "to_pydatetime") else datetime.fromisoformat(str(last))
    years = max((last - first).days / 365.25, 1 / 365.25)
    annual = (values.iloc[-1] / initial_cash) ** (1 / years) - 1 if values.iloc[-1] > 0 else -1.0
    drawdown = values / values.cummax() - 1
    sharpe = (daily.mean() / daily.std(ddof=1) * math.sqrt(365)) if len(daily) > 1 and daily.std(ddof=1) else 0.0
    wins = int((trades.exit_price * trades.quantity - trades.exit_fee - trades.entry_price * trades.quantity - trades.entry_fee > 0).sum()) if len(trades) else 0
    return {"total_return": total, "annualized_return": annual, "max_drawdown": float(drawdown.min()),
            "sharpe": float(sharpe), "win_rate": wins / len(trades) if len(trades) else 0.0,
            "trade_count": int(len(trades)), "final_equity": float(values.iloc[-1])}
