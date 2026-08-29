"""Backtesting engine and paper trading simulator for HermesTrade.

Wraps backtesting.py for strategy backtesting, provides performance metrics
calculation, a paper trading simulator, and a chronological event-replay runner.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import yfinance as yf  # type: ignore[import-untyped]
from backtesting import Backtest, Strategy  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# PerformanceMetrics
# ---------------------------------------------------------------------------


class PerformanceMetrics:
    """Static methods for computing trading performance metrics."""

    @staticmethod
    def sharpe_ratio(
        returns: pd.Series,
        risk_free_rate: float = 0.0,
        periods_per_year: int = 252,
    ) -> float:
        """Calculate annualized Sharpe ratio.

        Args:
            returns: Series of periodic returns (e.g. daily).
            risk_free_rate: Annual risk-free rate (decimal).
            periods_per_year: Number of periods in a year (252 for daily).

        Returns:
            Sharpe ratio, or 0.0 if returns have zero volatility.
        """
        if len(returns) < 2:
            return 0.0
        excess = returns - risk_free_rate / periods_per_year
        std = excess.std(ddof=1)
        if std == 0 or np.isnan(std):
            return 0.0
        return float(excess.mean() / std * np.sqrt(periods_per_year))

    @staticmethod
    def max_drawdown(equity: pd.Series) -> float:
        """Calculate maximum drawdown as a decimal fraction.

        Args:
            equity: Series of equity values over time.

        Returns:
            Maximum drawdown as a decimal (e.g. 0.15 for 15%).
        """
        if len(equity) < 2:
            return 0.0
        rolling_max = equity.cummax()
        drawdown = (equity - rolling_max) / rolling_max
        min_dd = drawdown.min()
        if pd.isna(min_dd):
            return 0.0
        return float(abs(min_dd))

    @staticmethod
    def win_rate(trades: pd.DataFrame) -> float:
        """Calculate win rate as a percentage.

        Args:
            trades: DataFrame with a 'PnL' column.

        Returns:
            Win rate as a percentage (0-100).
        """
        if trades.empty or len(trades) == 0:
            return 0.0
        winners = (trades["PnL"] > 0).sum()
        return float(winners / len(trades) * 100)

    @staticmethod
    def profit_factor(trades: pd.DataFrame) -> float:
        """Calculate profit factor (gross profit / gross loss).

        Args:
            trades: DataFrame with a 'PnL' column.

        Returns:
            Profit factor, or inf if no losing trades, or 0 if no trades.
        """
        if trades.empty or len(trades) == 0:
            return 0.0
        gross_profit = trades.loc[trades["PnL"] > 0, "PnL"].sum()
        gross_loss = abs(trades.loc[trades["PnL"] < 0, "PnL"].sum())
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return float(gross_profit / gross_loss)

    @staticmethod
    def cagr(start_value: float, end_value: float, days: int) -> float:
        """Calculate Compound Annual Growth Rate.

        Args:
            start_value: Initial portfolio value.
            end_value: Final portfolio value.
            days: Number of days in the period.

        Returns:
            CAGR as a decimal.
        """
        if days <= 0 or start_value <= 0:
            return 0.0
        years = days / 365.25
        return float((end_value / start_value) ** (1 / years) - 1)

    @staticmethod
    def total_return(start_value: float, end_value: float) -> float:
        """Calculate total return as a decimal.

        Args:
            start_value: Initial portfolio value.
            end_value: Final portfolio value.

        Returns:
            Total return as a decimal.
        """
        if start_value == 0:
            return 0.0
        return float((end_value - start_value) / start_value)

    @classmethod
    def compute_all(
        cls,
        equity_curve: pd.Series,
        trades: pd.DataFrame,
        risk_free_rate: float = 0.0,
    ) -> dict[str, Any]:
        """Compute a full dictionary of performance metrics.

        Args:
            equity_curve: Series of equity values over time.
            trades: DataFrame of trade records with 'PnL' column.
            risk_free_rate: Annual risk-free rate.

        Returns:
            Dictionary of metric names to values.
        """
        if len(equity_curve) < 2:
            return {
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "total_return": 0.0,
                "cagr": 0.0,
                "total_trades": 0,
            }

        # Daily returns from equity curve
        returns = equity_curve.pct_change().dropna()

        start_val = float(equity_curve.iloc[0])
        end_val = float(equity_curve.iloc[-1])
        days = (equity_curve.index[-1] - equity_curve.index[0]).days

        return {
            "sharpe_ratio": cls.sharpe_ratio(returns, risk_free_rate),
            "max_drawdown": cls.max_drawdown(equity_curve),
            "win_rate": cls.win_rate(trades),
            "profit_factor": cls.profit_factor(trades),
            "total_return": cls.total_return(start_val, end_val),
            "cagr": cls.cagr(start_val, end_val, days),
            "total_trades": len(trades),
        }


# ---------------------------------------------------------------------------
# BacktestEngine
# ---------------------------------------------------------------------------


class BacktestEngine:
    """Wraps backtesting.py Backtest for strategy evaluation.

    Provides data loading from yfinance, backtest execution, and
    access to results, equity curves, and trade records.
    """

    def __init__(
        self,
        initial_cash: float = 100_000.0,
        commission: float = 0.001,
        spread: float = 0.0,
    ) -> None:
        """Initialize the backtesting engine.

        Args:
            initial_cash: Starting capital for the backtest.
            commission: Commission rate as a decimal (e.g. 0.001 = 0.1%).
            spread: Bid-ask spread as a decimal.
        """
        self.initial_cash = initial_cash
        self.commission = commission
        self.spread = spread
        self._last_result: pd.Series | None = None
        self._last_backtest: Backtest | None = None

    def load_data(
        self,
        symbol: str,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Download historical OHLCV data from Yahoo Finance.

        Args:
            symbol: Ticker symbol (e.g. 'AAPL').
            start: Start date string (YYYY-MM-DD).
            end: End date string (YYYY-MM-DD).
            interval: Data interval (default '1d').

        Returns:
            DataFrame with columns Open, High, Low, Close, Volume.

        Raises:
            ValueError: If no data is returned for the given symbol/range.
        """
        data = yf.download(symbol, start=start, end=end, interval=interval, progress=False)

        if data.empty:
            raise ValueError(f"No data returned for symbol '{symbol}' in range {start} to {end}")

        # Flatten MultiIndex columns if present (yfinance sometimes returns them)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        # Ensure standard column names
        expected = ["Open", "High", "Low", "Close", "Volume"]
        data = data[[c for c in expected if c in data.columns]]

        return data

    def run(
        self,
        data: pd.DataFrame,
        strategy: type[Strategy],
        **strategy_params: Any,
    ) -> pd.Series:
        """Run a backtest with the given data and strategy.

        Args:
            data: OHLCV DataFrame (must have Open, High, Low, Close, Volume).
            strategy: A backtesting.py Strategy subclass.
            **strategy_params: Parameters passed to the strategy.

        Returns:
            A Series of backtest statistics (from backtesting.py's _Stats).
        """
        bt = Backtest(
            data,
            strategy,
            cash=self.initial_cash,
            commission=self.commission,
            spread=self.spread,
        )
        result = bt.run(**strategy_params)
        self._last_result = result
        self._last_backtest = bt
        return result

    def get_equity_curve(self) -> pd.DataFrame | None:
        """Return the equity curve from the last backtest run.

        Returns:
            DataFrame with Equity, DrawdownPct, and DrawdownDuration columns,
            or None if no backtest has been run.
        """
        if self._last_result is None:
            return None
        equity_curve = self._last_result.get("_equity_curve")
        if equity_curve is None:
            return None
        return pd.DataFrame(equity_curve)

    def get_trades(self) -> pd.DataFrame | None:
        """Return trade records from the last backtest run.

        Returns:
            DataFrame of trades, or None if no backtest has been run.
        """
        if self._last_result is None:
            return None
        trades = self._last_result.get("_trades")
        if trades is None:
            return None
        return pd.DataFrame(trades)


# ---------------------------------------------------------------------------
# PaperTradingSimulator
# ---------------------------------------------------------------------------


class PaperTradingSimulator:
    """Logs orders without executing them — a paper trading sandbox.

    Orders are recorded with unique IDs and timestamps. No cash or
    position state is modified. Useful for testing strategies before
    live deployment.
    """

    def __init__(self, initial_cash: float = 100_000.0) -> None:
        """Initialize the paper trading simulator.

        Args:
            initial_cash: Starting virtual capital.
        """
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: dict[str, dict[str, Any]] = {}
        self.orders_log: list[dict[str, Any]] = []
        self._order_counter = 0

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        limit_price: float | None = None,
        stop_price: float | None = None,
    ) -> dict[str, Any]:
        """Log a paper trade order without executing it.

        Args:
            symbol: Ticker symbol.
            side: 'buy' or 'sell'.
            quantity: Number of shares/contracts.
            order_type: 'market', 'limit', 'stop', or 'stop_limit'.
            limit_price: Limit price (required for limit orders).
            stop_price: Stop price (required for stop orders).

        Returns:
            The logged order as a dictionary.

        Raises:
            ValueError: If side is invalid or quantity is non-positive.
        """
        side = side.lower()
        if side not in ("buy", "sell"):
            raise ValueError(f"Invalid side '{side}'. Must be 'buy' or 'sell'.")

        if quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {quantity}.")

        self._order_counter += 1
        order: dict[str, Any] = {
            "id": f"paper-{uuid.uuid4().hex[:12]}",
            "symbol": symbol.upper(),
            "side": side,
            "quantity": quantity,
            "order_type": order_type,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "status": "logged",
            "timestamp": datetime.now(UTC),
            "order_num": self._order_counter,
        }
        self.orders_log.append(order)
        return order

    def get_orders_log(
        self,
        symbol: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve logged orders, optionally filtered.

        Args:
            symbol: Filter by symbol (case-insensitive).
            status: Filter by order status.

        Returns:
            List of matching order dictionaries.
        """
        orders = self.orders_log
        if symbol is not None:
            orders = [o for o in orders if o["symbol"] == symbol.upper()]
        if status is not None:
            orders = [o for o in orders if o["status"] == status]
        return orders

    def clear_orders_log(self) -> None:
        """Clear all logged orders."""
        self.orders_log.clear()

    def get_summary(self) -> dict[str, Any]:
        """Return a summary of the simulator state.

        Returns:
            Dictionary with cash, order counts, and position info.
        """
        pending = sum(1 for o in self.orders_log if o["status"] == "logged")
        return {
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "total_orders": len(self.orders_log),
            "pending_orders": pending,
            "positions": dict(self.positions),
        }


# ---------------------------------------------------------------------------
# StrategyRunner
# ---------------------------------------------------------------------------


class StrategyRunner:
    """Runs a strategy over historical data, replaying events chronologically.

    Wraps backtesting.py to provide event collection and structured
    output suitable for integration with the event-driven architecture.
    """

    def __init__(
        self,
        data: pd.DataFrame,
        strategy: type[Strategy],
        cash: float = 100_000.0,
        commission: float = 0.001,
        spread: float = 0.0,
    ) -> None:
        """Initialize the strategy runner.

        Args:
            data: OHLCV DataFrame.
            strategy: A backtesting.py Strategy subclass.
            cash: Starting capital.
            commission: Commission rate.
            spread: Bid-ask spread.
        """
        self.data = data
        self.strategy = strategy
        self.cash = cash
        self.commission = commission
        self.spread = spread
        self.events: list[dict[str, Any]] = []
        self._result: pd.Series | None = None

    def run(self, **strategy_params: Any) -> pd.Series:
        """Run the strategy and collect chronological events.

        Args:
            **strategy_params: Parameters passed to the strategy.

        Returns:
            Backtest statistics Series.
        """
        bt = Backtest(
            self.data,
            self.strategy,
            cash=self.cash,
            commission=self.commission,
            spread=self.spread,
        )
        result = bt.run(**strategy_params)
        self._result = result

        # Collect events from trades
        trades = result.get("_trades")
        if trades is not None:
            # _trades can be a DataFrame (multiple trades) or Series (single trade)
            trade_iter = (
                trades.iterrows() if hasattr(trades, "iterrows") else [(0, trades)]
            )

            for _, trade in trade_iter:
                self.events.append(
                    {
                        "timestamp": trade.get("EntryTime"),
                        "type": "trade_entry",
                        "size": trade.get("Size"),
                        "price": trade.get("EntryPrice"),
                    }
                )
                self.events.append(
                    {
                        "timestamp": trade.get("ExitTime"),
                        "type": "trade_exit",
                        "size": trade.get("Size"),
                        "price": trade.get("ExitPrice"),
                        "pnl": trade.get("PnL"),
                    }
                )

        # Sort events chronologically
        self.events.sort(key=lambda e: e.get("timestamp") or pd.Timestamp.min)

        return result

    def get_events(self) -> list[dict[str, Any]]:
        """Return collected events in chronological order.

        Returns:
            List of event dictionaries.
        """
        return self.events
