"""Core data models for HermesTrade — all domain types used across the system."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AssetClass(str, Enum):
    STOCK = "stock"
    CRYPTO = "crypto"
    FOREX = "forex"
    CFD = "cfd"
    OPTION = "option"
    FUTURE = "future"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class SentimentLabel(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class EventType(str, Enum):
    MARKET_DATA = "market_data"
    NEWS_ARTICLE = "news_article"
    SOCIAL_POST = "social_post"
    SENTIMENT_SIGNAL = "sentiment_signal"
    TRADE_SIGNAL = "trade_signal"
    ORDER_REQUEST = "order_request"
    ORDER_UPDATE = "order_update"
    RISK_ALERT = "risk_alert"


class MarketData(BaseModel):
    """OHLCV bar for a single instrument."""

    symbol: str = Field(..., min_length=1, max_length=20)
    timestamp: datetime
    open: Decimal = Field(..., gt=0)
    high: Decimal = Field(..., gt=0)
    low: Decimal = Field(..., gt=0)
    close: Decimal = Field(..., gt=0)
    volume: Decimal = Field(..., ge=0)
    asset_class: AssetClass


class NewsItem(BaseModel):
    """A news article or social media post detected by watchers."""

    source: str = Field(..., min_length=1)
    source_url: Optional[str] = None
    title: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    published_at: datetime
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    symbols: list[str] = Field(default_factory=list)
    language: str = Field(default="en", min_length=2, max_length=5)


class SentimentSignal(BaseModel):
    """Output of the sentiment analysis pipeline."""

    news_item_id: str
    symbol: str
    label: SentimentLabel
    score: float = Field(..., ge=0.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    model_name: str
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)
    explanation: Optional[str] = None


class TradeSignal(BaseModel):
    """Decision output from the decision engine."""

    symbol: str
    side: OrderSide
    quantity: Decimal = Field(..., gt=0)
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason: str = Field(..., min_length=1)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    source_signals: list[str] = Field(default_factory=list)


class Order(BaseModel):
    """An order sent to or received from a broker."""

    id: str = Field(..., min_length=1)
    broker: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal = Field(..., gt=0)
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    avg_fill_price: Optional[Decimal] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    broker_order_id: Optional[str] = None


class RiskLimits(BaseModel):
    """Risk management constraints."""

    max_position_size: Decimal = Field(..., gt=0)
    max_daily_loss: Decimal = Field(..., gt=0)
    max_drawdown_pct: float = Field(..., gt=0.0, le=100.0)
    max_trades_per_day: int = Field(..., gt=0)
    stop_loss_pct: float = Field(..., gt=0.0, le=100.0)
    take_profit_pct: Optional[float] = Field(default=None, gt=0.0, le=1000.0)
