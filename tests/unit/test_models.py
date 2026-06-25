"""Tests for core data models."""

from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from hermes_trade.models import (
    AssetClass,
    MarketData,
    NewsItem,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    RiskLimits,
    SentimentLabel,
    SentimentSignal,
    TradeSignal,
)


class TestMarketData:
    def test_valid_market_data_creation(self) -> None:
        md = MarketData(
            symbol="AAPL",
            timestamp=datetime(2026, 6, 25, 14, 30, 0),
            open=Decimal("150.00"),
            high=Decimal("152.50"),
            low=Decimal("149.00"),
            close=Decimal("151.25"),
            volume=Decimal("1000000"),
            asset_class=AssetClass.STOCK,
        )
        assert md.symbol == "AAPL"
        assert md.close == Decimal("151.25")
        assert md.asset_class == AssetClass.STOCK

    def test_rejects_zero_or_negative_price(self) -> None:
        with pytest.raises(ValidationError):
            MarketData(
                symbol="AAPL",
                timestamp=datetime(2026, 6, 25),
                open=Decimal("0"),
                high=Decimal("152.50"),
                low=Decimal("149.00"),
                close=Decimal("151.25"),
                volume=Decimal("1000000"),
                asset_class=AssetClass.STOCK,
            )

    def test_rejects_negative_volume(self) -> None:
        with pytest.raises(ValidationError):
            MarketData(
                symbol="AAPL",
                timestamp=datetime(2026, 6, 25),
                open=Decimal("150"),
                high=Decimal("152"),
                low=Decimal("149"),
                close=Decimal("151"),
                volume=Decimal("-1"),
                asset_class=AssetClass.STOCK,
            )


class TestNewsItem:
    def test_valid_news_item_creation(self) -> None:
        news = NewsItem(
            source="Reuters",
            source_url="https://reuters.com/article/123",
            title="Fed raises rates",
            content="The Federal Reserve raised interest rates by 25 basis points.",
            published_at=datetime(2026, 6, 25, 10, 0, 0),
            symbols=["SPY", "QQQ"],
        )
        assert news.source == "Reuters"
        assert len(news.symbols) == 2
        assert news.detected_at is not None

    def test_rejects_empty_title(self) -> None:
        with pytest.raises(ValidationError):
            NewsItem(
                source="Reuters",
                title="",
                content="Some content",
                published_at=datetime(2026, 6, 25),
            )

    def test_default_language_is_en(self) -> None:
        news = NewsItem(
            source="Reuters",
            title="Test",
            content="Content",
            published_at=datetime(2026, 6, 25),
        )
        assert news.language == "en"


class TestSentimentSignal:
    def test_valid_sentiment_signal(self) -> None:
        signal = SentimentSignal(
            news_item_id="news-123",
            symbol="AAPL",
            label=SentimentLabel.POSITIVE,
            score=0.85,
            confidence=0.92,
            model_name="FinBERT",
        )
        assert signal.label == SentimentLabel.POSITIVE
        assert signal.score == 0.85

    def test_rejects_score_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            SentimentSignal(
                news_item_id="news-123",
                symbol="AAPL",
                label=SentimentLabel.POSITIVE,
                score=1.5,
                confidence=0.9,
                model_name="FinBERT",
            )

    def test_rejects_confidence_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            SentimentSignal(
                news_item_id="news-123",
                symbol="AAPL",
                label=SentimentLabel.POSITIVE,
                score=0.8,
                confidence=-0.1,
                model_name="FinBERT",
            )


class TestTradeSignal:
    def test_valid_trade_signal(self) -> None:
        signal = TradeSignal(
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            confidence=0.75,
            reason="Positive sentiment from Fed announcement",
        )
        assert signal.side == OrderSide.BUY
        assert signal.order_type == OrderType.MARKET

    def test_rejects_zero_quantity(self) -> None:
        with pytest.raises(ValidationError):
            TradeSignal(
                symbol="AAPL",
                side=OrderSide.BUY,
                quantity=Decimal("0"),
                confidence=0.75,
                reason="Test",
            )


class TestOrder:
    def test_valid_order_creation(self) -> None:
        order = Order(
            id="ord-001",
            broker="alpaca",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
        )
        assert order.status == OrderStatus.PENDING
        assert order.filled_quantity == Decimal("0")

    def test_order_id_is_required(self) -> None:
        with pytest.raises(ValidationError):
            Order(
                id="",
                broker="alpaca",
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("100"),
            )


class TestRiskLimits:
    def test_valid_risk_limits(self) -> None:
        limits = RiskLimits(
            max_position_size=Decimal("10000"),
            max_daily_loss=Decimal("1000"),
            max_drawdown_pct=20.0,
            max_trades_per_day=50,
            stop_loss_pct=2.0,
        )
        assert limits.max_position_size == Decimal("10000")
        assert limits.stop_loss_pct == 2.0

    def test_rejects_negative_max_drawdown(self) -> None:
        with pytest.raises(ValidationError):
            RiskLimits(
                max_position_size=Decimal("10000"),
                max_daily_loss=Decimal("1000"),
                max_drawdown_pct=-5.0,
                max_trades_per_day=50,
                stop_loss_pct=2.0,
            )
