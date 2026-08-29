"""Tests for the backtesting engine and paper trading simulator.

TDD: tests written before implementation.
"""

from datetime import timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_ohlcv_data() -> pd.DataFrame:
    """Generate 200 days of synthetic OHLCV data."""
    dates = pd.date_range("2024-01-01", periods=200, freq="D")
    rng = np.random.RandomState(42)
    close = 100 + rng.randn(200).cumsum() * 0.5
    data = pd.DataFrame(
        {
            "Open": close + rng.randn(200) * 0.2,
            "High": close + np.abs(rng.randn(200)) * 0.5,
            "Low": close - np.abs(rng.randn(200)) * 0.5,
            "Close": close,
            "Volume": rng.randint(100_000, 1_000_000, 200),
        },
        index=dates,
    )
    return data


@pytest.fixture
def sample_equity_curve() -> pd.Series:
    """Generate a sample equity curve for metrics testing."""
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    rng = np.random.RandomState(42)
    equity = 10_000 + rng.randn(100).cumsum() * 50
    return pd.Series(equity, index=dates, name="Equity")


@pytest.fixture
def sample_trades() -> pd.DataFrame:
    """Generate sample trade records."""
    return pd.DataFrame(
        {
            "Size": [10, -10, 20, -20, 15, -15],
            "EntryBar": [0, 1, 2, 3, 4, 5],
            "ExitBar": [1, 2, 3, 4, 5, 6],
            "EntryPrice": [100.0, 102.0, 101.0, 103.0, 104.0, 106.0],
            "ExitPrice": [102.0, 101.0, 103.0, 104.0, 106.0, 105.0],
            "PnL": [20.0, 10.0, 40.0, -20.0, 30.0, 15.0],
            "ReturnPct": [2.0, 0.98, 1.98, -0.97, 1.92, -0.94],
            "EntryTime": pd.to_datetime(
                [
                    "2024-01-01",
                    "2024-01-02",
                    "2024-01-03",
                    "2024-01-04",
                    "2024-01-05",
                    "2024-01-06",
                ]
            ),
            "ExitTime": pd.to_datetime(
                [
                    "2024-01-02",
                    "2024-01-03",
                    "2024-01-04",
                    "2024-01-05",
                    "2024-01-06",
                    "2024-01-07",
                ]
            ),
            "Duration": [
                timedelta(days=1),
                timedelta(days=1),
                timedelta(days=1),
                timedelta(days=1),
                timedelta(days=1),
                timedelta(days=1),
            ],
            "Tag": [None] * 6,
        }
    )


# ---------------------------------------------------------------------------
# Test: BacktestEngine
# ---------------------------------------------------------------------------


class TestBacktestEngine:
    """Tests for the BacktestEngine class."""

    def test_engine_initialization_defaults(self) -> None:
        """Engine should initialize with sensible defaults."""
        from hermes_trade.backtesting.engine import BacktestEngine

        engine = BacktestEngine()
        assert engine.initial_cash == 100_000.0
        assert engine.commission == 0.001
        assert engine.spread == 0.0

    def test_engine_initialization_custom(self) -> None:
        """Engine should accept custom parameters."""
        from hermes_trade.backtesting.engine import BacktestEngine

        engine = BacktestEngine(
            initial_cash=50_000.0,
            commission=0.002,
            spread=0.01,
        )
        assert engine.initial_cash == 50_000.0
        assert engine.commission == 0.002
        assert engine.spread == 0.01

    def test_load_data_from_yfinance(self) -> None:
        """Should download and return properly formatted OHLCV DataFrame."""
        from hermes_trade.backtesting.engine import BacktestEngine

        engine = BacktestEngine()

        with patch("hermes_trade.backtesting.engine.yf.download") as mock_download:
            mock_df = pd.DataFrame(
                {
                    "Open": [100.0, 101.0, 102.0],
                    "High": [101.0, 102.0, 103.0],
                    "Low": [99.0, 100.0, 101.0],
                    "Close": [100.5, 101.5, 102.5],
                    "Volume": [1000000, 1100000, 1200000],
                },
                index=pd.date_range("2024-01-01", periods=3, freq="D"),
            )
            mock_download.return_value = mock_df

            data = engine.load_data("AAPL", start="2024-01-01", end="2024-01-05")

            mock_download.assert_called_once_with(
                "AAPL", start="2024-01-01", end="2024-01-05", interval="1d", progress=False
            )
            assert isinstance(data, pd.DataFrame)
            assert list(data.columns) == ["Open", "High", "Low", "Close", "Volume"]
            assert len(data) == 3

    def test_load_data_handles_multiindex_columns(self) -> None:
        """Should flatten MultiIndex columns from yfinance."""
        from hermes_trade.backtesting.engine import BacktestEngine

        engine = BacktestEngine()

        with patch("hermes_trade.backtesting.engine.yf.download") as mock_download:
            # yfinance sometimes returns MultiIndex columns
            arrays = [
                ["Open", "High", "Low", "Close", "Volume"],
                ["AAPL", "AAPL", "AAPL", "AAPL", "AAPL"],
            ]
            tuples = list(zip(*arrays, strict=False))
            index = pd.MultiIndex.from_tuples(tuples)
            mock_df = pd.DataFrame(
                np.random.randn(5, 5), columns=index, index=pd.date_range("2024-01-01", periods=5)
            )
            mock_download.return_value = mock_df

            data = engine.load_data("AAPL", start="2024-01-01", end="2024-01-10")
            # Should be flat columns now
            assert not isinstance(data.columns, pd.MultiIndex)
            assert list(data.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_load_data_empty_result_raises(self) -> None:
        """Should raise ValueError when yfinance returns empty data."""
        from hermes_trade.backtesting.engine import BacktestEngine

        engine = BacktestEngine()

        with patch("hermes_trade.backtesting.engine.yf.download") as mock_download:
            mock_download.return_value = pd.DataFrame()

            with pytest.raises(ValueError, match="No data returned"):
                engine.load_data("INVALID_TICKER_XYZ", start="2024-01-01", end="2024-01-05")

    def test_run_backtest_basic(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """Should run a backtest and return a stats result."""
        from hermes_trade.backtesting.engine import BacktestEngine

        engine = BacktestEngine(initial_cash=10_000)

        # Use a simple built-in strategy
        from backtesting import Strategy

        class SimpleMA(Strategy):
            n1 = 10
            n2 = 20

            def init(self):
                self.sma1 = self.I(lambda x: pd.Series(x).rolling(self.n1).mean(), self.data.Close)
                self.sma2 = self.I(lambda x: pd.Series(x).rolling(self.n2).mean(), self.data.Close)

            def next(self):
                if self.sma1[-1] > self.sma2[-1] and not self.position:
                    self.buy()
                elif self.sma1[-1] < self.sma2[-1] and self.position:
                    self.position.close()

        result = engine.run(sample_ohlcv_data, SimpleMA, n1=10, n2=20)

        assert result is not None
        assert "Sharpe Ratio" in result
        assert "Max. Drawdown [%]" in result
        assert "Win Rate [%]" in result
        assert "Profit Factor" in result
        assert "Return [%]" in result

    def test_run_backtest_with_commission(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """Should apply commission to backtest results."""
        from hermes_trade.backtesting.engine import BacktestEngine

        engine_no_comm = BacktestEngine(initial_cash=10_000, commission=0.0)
        engine_with_comm = BacktestEngine(initial_cash=10_000, commission=0.01)

        from backtesting import Strategy

        class BuyHold(Strategy):
            def init(self):
                pass

            def next(self):
                if len(self.data) == 20 and not self.position:
                    self.buy()

        result_no_comm = engine_no_comm.run(sample_ohlcv_data, BuyHold)
        result_with_comm = engine_with_comm.run(sample_ohlcv_data, BuyHold)

        # With commission, final equity should be lower
        assert result_with_comm["Equity Final [$]"] <= result_no_comm["Equity Final [$]"]

    def test_run_returns_equity_curve(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """Should return equity curve data."""
        from hermes_trade.backtesting.engine import BacktestEngine

        engine = BacktestEngine(initial_cash=10_000)

        from backtesting import Strategy

        class BuyHold(Strategy):
            def init(self):
                pass

            def next(self):
                if len(self.data) == 20 and not self.position:
                    self.buy()

        engine.run(sample_ohlcv_data, BuyHold)
        equity_curve = engine.get_equity_curve()

        assert equity_curve is not None
        assert isinstance(equity_curve, pd.DataFrame)
        assert "Equity" in equity_curve.columns

    def test_run_returns_trades(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """Should return trade records."""
        from hermes_trade.backtesting.engine import BacktestEngine

        engine = BacktestEngine(initial_cash=10_000)

        from backtesting import Strategy

        class BuyHold(Strategy):
            def init(self):
                pass

            def next(self):
                if len(self.data) == 20 and not self.position:
                    self.buy()
                elif len(self.data) == 40 and self.position:
                    self.position.close()

        engine.run(sample_ohlcv_data, BuyHold)
        trades = engine.get_trades()

        assert trades is not None
        assert isinstance(trades, pd.DataFrame)
        assert len(trades) >= 1


# ---------------------------------------------------------------------------
# Test: PerformanceMetrics
# ---------------------------------------------------------------------------


class TestPerformanceMetrics:
    """Tests for performance metrics calculation."""

    def test_sharpe_ratio_calculation(self) -> None:
        """Should calculate Sharpe ratio correctly."""
        from hermes_trade.backtesting.engine import PerformanceMetrics

        # Risk-free rate ~0 for simplicity
        returns = pd.Series([0.01, 0.02, -0.01, 0.03, 0.01, -0.005, 0.02, 0.01])
        sharpe = PerformanceMetrics.sharpe_ratio(returns, risk_free_rate=0.0, periods_per_year=252)
        assert sharpe > 0  # Positive returns => positive Sharpe

    def test_sharpe_ratio_zero_volatility(self) -> None:
        """Should return 0 when returns have zero volatility."""
        from hermes_trade.backtesting.engine import PerformanceMetrics

        returns = pd.Series([0.01, 0.01, 0.01, 0.01])
        sharpe = PerformanceMetrics.sharpe_ratio(returns)
        assert sharpe == 0.0

    def test_max_drawdown_calculation(self) -> None:
        """Should calculate max drawdown correctly."""
        from hermes_trade.backtesting.engine import PerformanceMetrics

        equity = pd.Series([100, 110, 105, 95, 100, 90, 95, 100])
        mdd = PerformanceMetrics.max_drawdown(equity)
        # Peak at 110, trough at 90 => drawdown = (110-90)/110 ≈ 0.1818
        assert pytest.approx(mdd, abs=0.01) == 0.1818

    def test_max_drawdown_always_increasing(self) -> None:
        """Should return 0 when equity never decreases."""
        from hermes_trade.backtesting.engine import PerformanceMetrics

        equity = pd.Series([100, 101, 102, 103, 104, 105])
        mdd = PerformanceMetrics.max_drawdown(equity)
        assert mdd == 0.0

    def test_win_rate_calculation(self) -> None:
        """Should calculate win rate correctly."""
        from hermes_trade.backtesting.engine import PerformanceMetrics

        trades = pd.DataFrame(
            {
                "PnL": [100, -50, 200, -30, 150, -10],
            }
        )
        win_rate = PerformanceMetrics.win_rate(trades)
        # 3 winners out of 6 = 50%
        assert win_rate == 50.0

    def test_win_rate_no_trades(self) -> None:
        """Should return 0 when there are no trades."""
        from hermes_trade.backtesting.engine import PerformanceMetrics

        trades = pd.DataFrame({"PnL": []})
        win_rate = PerformanceMetrics.win_rate(trades)
        assert win_rate == 0.0

    def test_profit_factor_calculation(self) -> None:
        """Should calculate profit factor correctly."""
        from hermes_trade.backtesting.engine import PerformanceMetrics

        trades = pd.DataFrame(
            {
                "PnL": [100, -50, 200, -30],
            }
        )
        pf = PerformanceMetrics.profit_factor(trades)
        # Gross profit = 300, gross loss = 80 => PF = 300/80 = 3.75
        assert pf == 3.75

    def test_profit_factor_no_losing_trades(self) -> None:
        """Should return inf when there are no losing trades."""
        from hermes_trade.backtesting.engine import PerformanceMetrics

        trades = pd.DataFrame(
            {
                "PnL": [100, 200, 150],
            }
        )
        pf = PerformanceMetrics.profit_factor(trades)
        assert pf == float("inf")

    def test_profit_factor_no_trades(self) -> None:
        """Should return 0 when there are no trades."""
        from hermes_trade.backtesting.engine import PerformanceMetrics

        trades = pd.DataFrame({"PnL": []})
        pf = PerformanceMetrics.profit_factor(trades)
        assert pf == 0.0

    def test_compute_all_metrics(self, sample_equity_curve, sample_trades) -> None:
        """Should compute a full metrics dictionary."""
        from hermes_trade.backtesting.engine import PerformanceMetrics

        metrics = PerformanceMetrics.compute_all(sample_equity_curve, sample_trades)

        assert isinstance(metrics, dict)
        assert "sharpe_ratio" in metrics
        assert "max_drawdown" in metrics
        assert "win_rate" in metrics
        assert "profit_factor" in metrics
        assert "total_return" in metrics
        assert "cagr" in metrics
        assert "total_trades" in metrics

    def test_cagr_calculation(self) -> None:
        """Should calculate CAGR correctly."""
        from hermes_trade.backtesting.engine import PerformanceMetrics

        # 10% return over exactly 1 year => CAGR = 10%
        cagr = PerformanceMetrics.cagr(start_value=1000, end_value=1100, days=365)
        assert pytest.approx(cagr, abs=0.001) == 0.10

    def test_total_return_calculation(self) -> None:
        """Should calculate total return correctly."""
        from hermes_trade.backtesting.engine import PerformanceMetrics

        ret = PerformanceMetrics.total_return(start_value=1000, end_value=1150)
        assert ret == 0.15


# ---------------------------------------------------------------------------
# Test: PaperTradingSimulator
# ---------------------------------------------------------------------------


class TestPaperTradingSimulator:
    """Tests for the paper trading simulator."""

    def test_simulator_initialization(self) -> None:
        """Should initialize with given cash and parameters."""
        from hermes_trade.backtesting.engine import PaperTradingSimulator

        sim = PaperTradingSimulator(initial_cash=50_000.0)
        assert sim.initial_cash == 50_000.0
        assert sim.cash == 50_000.0
        assert sim.positions == {}
        assert sim.orders_log == []

    def test_place_market_buy_order(self) -> None:
        """Should log a market buy order without executing."""
        from hermes_trade.backtesting.engine import PaperTradingSimulator

        sim = PaperTradingSimulator(initial_cash=10_000.0)
        order = sim.place_order(
            symbol="AAPL",
            side="buy",
            quantity=10,
            order_type="market",
        )

        assert order["symbol"] == "AAPL"
        assert order["side"] == "buy"
        assert order["quantity"] == 10
        assert order["order_type"] == "market"
        assert order["status"] == "logged"
        assert "id" in order
        assert "timestamp" in order
        assert len(sim.orders_log) == 1

    def test_place_limit_sell_order(self) -> None:
        """Should log a limit sell order."""
        from hermes_trade.backtesting.engine import PaperTradingSimulator

        sim = PaperTradingSimulator(initial_cash=10_000.0)
        order = sim.place_order(
            symbol="TSLA",
            side="sell",
            quantity=5,
            order_type="limit",
            limit_price=250.0,
        )

        assert order["symbol"] == "TSLA"
        assert order["side"] == "sell"
        assert order["limit_price"] == 250.0
        assert order["status"] == "logged"

    def test_place_order_rejects_invalid_side(self) -> None:
        """Should reject orders with invalid side."""
        from hermes_trade.backtesting.engine import PaperTradingSimulator

        sim = PaperTradingSimulator()
        with pytest.raises(ValueError, match="side"):
            sim.place_order(symbol="AAPL", side="hold", quantity=10)

    def test_place_order_rejects_invalid_quantity(self) -> None:
        """Should reject orders with non-positive quantity."""
        from hermes_trade.backtesting.engine import PaperTradingSimulator

        sim = PaperTradingSimulator()
        with pytest.raises(ValueError, match="positive"):
            sim.place_order(symbol="AAPL", side="buy", quantity=0)

        with pytest.raises(ValueError, match="positive"):
            sim.place_order(symbol="AAPL", side="buy", quantity=-5)

    def test_get_orders_log(self) -> None:
        """Should return all logged orders."""
        from hermes_trade.backtesting.engine import PaperTradingSimulator

        sim = PaperTradingSimulator()
        sim.place_order("AAPL", "buy", 10)
        sim.place_order("TSLA", "sell", 5)
        sim.place_order("MSFT", "buy", 20, order_type="limit", limit_price=300.0)

        log = sim.get_orders_log()
        assert len(log) == 3
        assert log[0]["symbol"] == "AAPL"
        assert log[1]["symbol"] == "TSLA"
        assert log[2]["symbol"] == "MSFT"

    def test_get_orders_log_filtered_by_symbol(self) -> None:
        """Should filter orders by symbol."""
        from hermes_trade.backtesting.engine import PaperTradingSimulator

        sim = PaperTradingSimulator()
        sim.place_order("AAPL", "buy", 10)
        sim.place_order("TSLA", "sell", 5)
        sim.place_order("AAPL", "sell", 5)

        aapl_orders = sim.get_orders_log(symbol="AAPL")
        assert len(aapl_orders) == 2
        assert all(o["symbol"] == "AAPL" for o in aapl_orders)

    def test_get_orders_log_filtered_by_status(self) -> None:
        """Should filter orders by status."""
        from hermes_trade.backtesting.engine import PaperTradingSimulator

        sim = PaperTradingSimulator()
        sim.place_order("AAPL", "buy", 10)
        sim.place_order("TSLA", "sell", 5)

        # Manually update one order's status
        sim.orders_log[0]["status"] = "filled"

        logged = sim.get_orders_log(status="logged")
        assert len(logged) == 1
        assert logged[0]["symbol"] == "TSLA"

    def test_clear_orders_log(self) -> None:
        """Should clear all logged orders."""
        from hermes_trade.backtesting.engine import PaperTradingSimulator

        sim = PaperTradingSimulator()
        sim.place_order("AAPL", "buy", 10)
        sim.place_order("TSLA", "sell", 5)

        sim.clear_orders_log()
        assert len(sim.orders_log) == 0

    def test_get_summary(self) -> None:
        """Should return a summary of the simulator state."""
        from hermes_trade.backtesting.engine import PaperTradingSimulator

        sim = PaperTradingSimulator(initial_cash=100_000.0)
        sim.place_order("AAPL", "buy", 10)
        sim.place_order("TSLA", "sell", 5, order_type="limit", limit_price=250.0)

        summary = sim.get_summary()
        assert summary["initial_cash"] == 100_000.0
        assert summary["cash"] == 100_000.0
        assert summary["total_orders"] == 2
        assert summary["pending_orders"] == 2

    def test_order_id_uniqueness(self) -> None:
        """Each order should have a unique ID."""
        from hermes_trade.backtesting.engine import PaperTradingSimulator

        sim = PaperTradingSimulator()
        o1 = sim.place_order("AAPL", "buy", 10)
        o2 = sim.place_order("AAPL", "buy", 10)
        o3 = sim.place_order("AAPL", "buy", 10)

        ids = {o1["id"], o2["id"], o3["id"]}
        assert len(ids) == 3

    def test_simulator_does_not_modify_cash(self) -> None:
        """Paper trading should NOT modify cash (no execution)."""
        from hermes_trade.backtesting.engine import PaperTradingSimulator

        sim = PaperTradingSimulator(initial_cash=10_000.0)
        sim.place_order("AAPL", "buy", 100, limit_price=150.0)
        sim.place_order("TSLA", "sell", 50)

        # Cash should remain unchanged
        assert sim.cash == 10_000.0


# ---------------------------------------------------------------------------
# Test: StrategyRunner (chronological event replay)
# ---------------------------------------------------------------------------


class TestStrategyRunner:
    """Tests for the StrategyRunner that replays events chronologically."""

    def test_runner_initialization(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """Should initialize with data and strategy."""
        from backtesting import Strategy

        from hermes_trade.backtesting.engine import StrategyRunner

        class DummyStrategy(Strategy):
            def init(self):
                pass

            def next(self):
                pass

        runner = StrategyRunner(sample_ohlcv_data, DummyStrategy, cash=10_000)
        assert runner.data is sample_ohlcv_data
        assert runner.cash == 10_000
        assert len(runner.events) == 0

    def test_runner_replays_events_chronologically(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """Should replay events in chronological order."""
        from backtesting import Strategy

        from hermes_trade.backtesting.engine import StrategyRunner

        events_received = []

        class RecordingStrategy(Strategy):
            def init(self):
                pass

            def next(self):
                events_received.append(
                    {
                        "index": len(events_received),
                        "close": float(self.data.Close[-1]),
                    }
                )

        runner = StrategyRunner(sample_ohlcv_data, RecordingStrategy, cash=10_000)
        runner.run()

        # Should have processed all bars (minus warmup for indicators if any)
        assert len(events_received) > 0
        # Events should be in chronological order (index increasing)
        for i in range(1, len(events_received)):
            assert events_received[i]["index"] > events_received[i - 1]["index"]

    def test_runner_collects_events(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """Should collect events during replay."""
        from backtesting import Strategy

        from hermes_trade.backtesting.engine import StrategyRunner

        class EventStrategy(Strategy):
            def init(self):
                pass

            def next(self):
                # Buy at bar 20, sell at bar 40
                if len(self.data) == 20 and not self.position:
                    self.buy(size=1)
                elif len(self.data) == 40 and self.position:
                    self.position.close()

        runner = StrategyRunner(sample_ohlcv_data, EventStrategy, cash=10_000)
        runner.run()

        events = runner.get_events()
        assert len(events) > 0
        # Each event should have a timestamp and type
        for event in events:
            assert "timestamp" in event
            assert "type" in event

    def test_runner_returns_stats(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """Should return backtest statistics after running."""
        from backtesting import Strategy

        from hermes_trade.backtesting.engine import StrategyRunner

        class SimpleStrategy(Strategy):
            def init(self):
                pass

            def next(self):
                if len(self.data) == 20 and not self.position:
                    self.buy()
                elif len(self.data) == 40 and self.position:
                    self.position.close()

        runner = StrategyRunner(sample_ohlcv_data, SimpleStrategy, cash=10_000)
        stats = runner.run()

        assert stats is not None
        assert "Sharpe Ratio" in stats or "sharpe_ratio" in stats
