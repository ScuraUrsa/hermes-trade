"""Tests for risk manager."""

from decimal import Decimal

import pytest

from hermes_trade.execution import RiskManager
from hermes_trade.models import OrderSide, RiskLimits, TradeSignal


@pytest.fixture
def limits() -> RiskLimits:
    return RiskLimits(
        max_position_size=Decimal("1000"),
        max_daily_loss=Decimal("500"),
        max_drawdown_pct=20.0,
        max_trades_per_day=10,
        stop_loss_pct=2.0,
    )


@pytest.fixture
def risk_mgr(limits: RiskLimits) -> RiskManager:
    return RiskManager(limits)


class TestRiskManager:
    def test_approves_valid_signal(self, risk_mgr: RiskManager) -> None:
        signal = TradeSignal(
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            confidence=0.85,
            reason="Positive sentiment",
        )
        result = risk_mgr.check_signal(signal)
        assert result.approved is True
        assert "passed" in result.reason.lower()

    def test_rejects_excessive_position_size(self, risk_mgr: RiskManager) -> None:
        signal = TradeSignal(
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("2000"),
            confidence=0.85,
            reason="Positive sentiment",
        )
        result = risk_mgr.check_signal(signal)
        assert result.approved is False
        assert "exceeds max" in result.reason.lower()

    def test_rejects_low_confidence(self, risk_mgr: RiskManager) -> None:
        signal = TradeSignal(
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            confidence=0.3,
            reason="Weak signal",
        )
        result = risk_mgr.check_signal(signal)
        assert result.approved is False
        assert "confidence" in result.reason.lower()

    def test_enforces_daily_trade_limit(self, risk_mgr: RiskManager) -> None:
        signal = TradeSignal(
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("10"),
            confidence=0.8,
            reason="Test",
        )
        # Fill up to the limit
        for _ in range(10):
            result = risk_mgr.check_signal(signal)
            assert result.approved is True
            risk_mgr.record_trade(signal)

        # 11th should be rejected
        result = risk_mgr.check_signal(signal)
        assert result.approved is False
        assert "limit reached" in result.reason.lower()

    def test_enforces_daily_loss_limit(self, risk_mgr: RiskManager) -> None:
        # Record a loss that hits the limit
        risk_mgr.record_pnl(Decimal("-500"))

        signal = TradeSignal(
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("10"),
            confidence=0.8,
            reason="Test",
        )
        result = risk_mgr.check_signal(signal)
        assert result.approved is False
        assert "loss limit" in result.reason.lower()

    def test_tracks_positions(self, risk_mgr: RiskManager) -> None:
        buy_signal = TradeSignal(
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            confidence=0.8,
            reason="Buy",
        )
        risk_mgr.record_trade(buy_signal)
        assert risk_mgr.positions["AAPL"] == Decimal("100")

        sell_signal = TradeSignal(
            symbol="AAPL",
            side=OrderSide.SELL,
            quantity=Decimal("50"),
            confidence=0.8,
            reason="Sell",
        )
        risk_mgr.record_trade(sell_signal)
        assert risk_mgr.positions["AAPL"] == Decimal("50")

    def test_tracks_daily_pnl(self, risk_mgr: RiskManager) -> None:
        risk_mgr.record_pnl(Decimal("100"))
        risk_mgr.record_pnl(Decimal("-30"))
        assert risk_mgr.daily_pnl == Decimal("70")

    def test_daily_trade_count(self, risk_mgr: RiskManager) -> None:
        assert risk_mgr.daily_trades == 0
        signal = TradeSignal(
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("10"),
            confidence=0.8,
            reason="Test",
        )
        risk_mgr.record_trade(signal)
        risk_mgr.record_trade(signal)
        assert risk_mgr.daily_trades == 2
