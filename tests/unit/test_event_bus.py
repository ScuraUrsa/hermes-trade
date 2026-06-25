"""Tests for the event bus module — EventBus ABC, RedisEventBus, InMemoryEventBus."""

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hermes_trade.core.event_bus import (
    Event,
    EventBus,
    InMemoryEventBus,
    RedisEventBus,
)
from hermes_trade.models import (
    AssetClass,
    EventType,
    MarketData,
    OrderSide,
    TradeSignal,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_market_data() -> MarketData:
    return MarketData(
        symbol="AAPL",
        timestamp=datetime(2026, 6, 25, 14, 30, 0),
        open=Decimal("150.00"),
        high=Decimal("152.50"),
        low=Decimal("149.00"),
        close=Decimal("151.25"),
        volume=Decimal("1000000"),
        asset_class=AssetClass.STOCK,
    )


@pytest.fixture
def sample_trade_signal() -> TradeSignal:
    return TradeSignal(
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=Decimal("100"),
        confidence=0.75,
        reason="Positive sentiment",
    )


# ---------------------------------------------------------------------------
# Event model tests
# ---------------------------------------------------------------------------

class TestEvent:
    """Tests for the Event wrapper model."""

    def test_create_event_from_model(self, sample_market_data: MarketData) -> None:
        event = Event.from_model(sample_market_data, EventType.MARKET_DATA)
        assert event.event_type == EventType.MARKET_DATA
        assert event.event_id != ""
        assert event.timestamp is not None
        assert event.payload["symbol"] == "AAPL"
        assert event.payload["close"] == "151.25"

    def test_event_serialization_roundtrip(self, sample_market_data: MarketData) -> None:
        event = Event.from_model(sample_market_data, EventType.MARKET_DATA)
        json_str = event.model_dump_json()
        restored = Event.model_validate_json(json_str)
        assert restored.event_id == event.event_id
        assert restored.event_type == event.event_type
        assert restored.payload == event.payload

    def test_event_deserialize_payload_to_model(self, sample_market_data: MarketData) -> None:
        event = Event.from_model(sample_market_data, EventType.MARKET_DATA)
        restored_model = event.deserialize_payload()
        assert isinstance(restored_model, MarketData)
        assert restored_model.symbol == "AAPL"
        assert restored_model.close == Decimal("151.25")

    def test_deserialize_payload_unknown_type_returns_dict(self) -> None:
        event = Event(
            event_id="test-1",
            event_type=EventType.MARKET_DATA,
            payload={"custom": "data"},
            timestamp=datetime.utcnow(),
        )
        result = event.deserialize_payload()
        assert isinstance(result, dict)
        assert result == {"custom": "data"}

    def test_event_unique_ids(self, sample_market_data: MarketData) -> None:
        e1 = Event.from_model(sample_market_data, EventType.MARKET_DATA)
        e2 = Event.from_model(sample_market_data, EventType.MARKET_DATA)
        assert e1.event_id != e2.event_id


# ---------------------------------------------------------------------------
# InMemoryEventBus tests
# ---------------------------------------------------------------------------

class TestInMemoryEventBus:
    """Tests for the InMemoryEventBus implementation."""

    @pytest.fixture
    def bus(self) -> InMemoryEventBus:
        return InMemoryEventBus()

    @pytest.mark.asyncio
    async def test_publish_subscribe_single_handler(
        self, bus: InMemoryEventBus, sample_market_data: MarketData
    ) -> None:
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        await bus.subscribe(EventType.MARKET_DATA, handler)
        event = Event.from_model(sample_market_data, EventType.MARKET_DATA)
        await bus.publish(event)

        # Allow async handlers to run
        await asyncio.sleep(0.01)

        assert len(received) == 1
        assert received[0].event_id == event.event_id
        assert received[0].event_type == EventType.MARKET_DATA

    @pytest.mark.asyncio
    async def test_publish_subscribe_multiple_handlers(
        self, bus: InMemoryEventBus, sample_market_data: MarketData
    ) -> None:
        received_1: list[Event] = []
        received_2: list[Event] = []

        async def handler_1(event: Event) -> None:
            received_1.append(event)

        async def handler_2(event: Event) -> None:
            received_2.append(event)

        await bus.subscribe(EventType.MARKET_DATA, handler_1)
        await bus.subscribe(EventType.MARKET_DATA, handler_2)
        event = Event.from_model(sample_market_data, EventType.MARKET_DATA)
        await bus.publish(event)

        await asyncio.sleep(0.01)

        assert len(received_1) == 1
        assert len(received_2) == 1

    @pytest.mark.asyncio
    async def test_handler_only_receives_subscribed_type(
        self, bus: InMemoryEventBus, sample_market_data: MarketData
    ) -> None:
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        await bus.subscribe(EventType.TRADE_SIGNAL, handler)
        event = Event.from_model(sample_market_data, EventType.MARKET_DATA)
        await bus.publish(event)

        await asyncio.sleep(0.01)

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_handler(
        self, bus: InMemoryEventBus, sample_market_data: MarketData
    ) -> None:
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        await bus.subscribe(EventType.MARKET_DATA, handler)
        await bus.unsubscribe(EventType.MARKET_DATA, handler)
        event = Event.from_model(sample_market_data, EventType.MARKET_DATA)
        await bus.publish(event)

        await asyncio.sleep(0.01)

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_handler_no_error(
        self, bus: InMemoryEventBus
    ) -> None:
        async def handler(event: Event) -> None:
            pass

        # Should not raise
        await bus.unsubscribe(EventType.MARKET_DATA, handler)

    @pytest.mark.asyncio
    async def test_multiple_event_types_routing(
        self, bus: InMemoryEventBus,
        sample_market_data: MarketData,
        sample_trade_signal: TradeSignal,
    ) -> None:
        md_received: list[Event] = []
        ts_received: list[Event] = []

        async def md_handler(event: Event) -> None:
            md_received.append(event)

        async def ts_handler(event: Event) -> None:
            ts_received.append(event)

        await bus.subscribe(EventType.MARKET_DATA, md_handler)
        await bus.subscribe(EventType.TRADE_SIGNAL, ts_handler)

        md_event = Event.from_model(sample_market_data, EventType.MARKET_DATA)
        ts_event = Event.from_model(sample_trade_signal, EventType.TRADE_SIGNAL)

        await bus.publish(md_event)
        await bus.publish(ts_event)

        await asyncio.sleep(0.01)

        assert len(md_received) == 1
        assert len(ts_received) == 1
        assert md_received[0].event_type == EventType.MARKET_DATA
        assert ts_received[0].event_type == EventType.TRADE_SIGNAL

    @pytest.mark.asyncio
    async def test_handler_error_does_not_affect_other_handlers(
        self, bus: InMemoryEventBus, sample_market_data: MarketData
    ) -> None:
        received: list[Event] = []

        async def failing_handler(event: Event) -> None:
            raise RuntimeError("handler failure")

        async def good_handler(event: Event) -> None:
            received.append(event)

        await bus.subscribe(EventType.MARKET_DATA, failing_handler)
        await bus.subscribe(EventType.MARKET_DATA, good_handler)
        event = Event.from_model(sample_market_data, EventType.MARKET_DATA)
        await bus.publish(event)

        await asyncio.sleep(0.01)

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_publish_no_subscribers_no_error(
        self, bus: InMemoryEventBus, sample_market_data: MarketData
    ) -> None:
        event = Event.from_model(sample_market_data, EventType.MARKET_DATA)
        # Should not raise
        await bus.publish(event)

    @pytest.mark.asyncio
    async def test_serialization_roundtrip_through_bus(
        self, bus: InMemoryEventBus, sample_market_data: MarketData
    ) -> None:
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        await bus.subscribe(EventType.MARKET_DATA, handler)
        original = Event.from_model(sample_market_data, EventType.MARKET_DATA)
        await bus.publish(original)

        await asyncio.sleep(0.01)

        assert len(received) == 1
        restored = received[0]
        assert restored.event_id == original.event_id
        assert restored.event_type == original.event_type
        assert restored.payload == original.payload
        # Verify we can deserialize back to the model
        model = restored.deserialize_payload()
        assert isinstance(model, MarketData)
        assert model.symbol == "AAPL"


# ---------------------------------------------------------------------------
# RedisEventBus tests (mocked Redis)
# ---------------------------------------------------------------------------

class TestRedisEventBus:
    """Tests for RedisEventBus using mocked redis-py async client."""

    @pytest.fixture
    def mock_redis(self) -> MagicMock:
        redis_mock = MagicMock()
        redis_mock.publish = AsyncMock()
        redis_mock.pubsub = MagicMock()
        return redis_mock

    @pytest.fixture
    def bus(self, mock_redis: MagicMock) -> RedisEventBus:
        return RedisEventBus(redis_client=mock_redis)

    @pytest.mark.asyncio
    async def test_publish_calls_redis_publish(
        self, bus: RedisEventBus, mock_redis: MagicMock, sample_market_data: MarketData
    ) -> None:
        event = Event.from_model(sample_market_data, EventType.MARKET_DATA)
        await bus.publish(event)

        mock_redis.publish.assert_awaited_once()
        call_args = mock_redis.publish.call_args
        channel, message = call_args[0]
        assert channel == "hermes:market_data"
        assert "AAPL" in message

    @pytest.mark.asyncio
    async def test_publish_serializes_event_to_json(
        self, bus: RedisEventBus, mock_redis: MagicMock, sample_market_data: MarketData
    ) -> None:
        event = Event.from_model(sample_market_data, EventType.MARKET_DATA)
        await bus.publish(event)

        _, message = mock_redis.publish.call_args[0]
        # Should be valid JSON that can be parsed back
        import json
        parsed = json.loads(message)
        assert parsed["event_type"] == "market_data"
        assert parsed["payload"]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_subscribe_creates_pubsub_and_subscribes(
        self, bus: RedisEventBus, mock_redis: MagicMock
    ) -> None:
        mock_pubsub = MagicMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_redis.pubsub.return_value = mock_pubsub

        async def handler(event: Event) -> None:
            pass

        await bus.subscribe(EventType.MARKET_DATA, handler)

        mock_redis.pubsub.assert_called_once()
        mock_pubsub.subscribe.assert_awaited_once_with("hermes:market_data")

    @pytest.mark.asyncio
    async def test_subscribe_starts_listener_task(
        self, bus: RedisEventBus, mock_redis: MagicMock
    ) -> None:
        mock_pubsub = MagicMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_redis.pubsub.return_value = mock_pubsub

        async def handler(event: Event) -> None:
            pass

        await bus.subscribe(EventType.MARKET_DATA, handler)

        # A listener task should be created
        assert EventType.MARKET_DATA in bus._listener_tasks

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_handler_and_cancels_task(
        self, bus: RedisEventBus, mock_redis: MagicMock
    ) -> None:
        mock_pubsub = MagicMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_redis.pubsub.return_value = mock_pubsub

        async def handler(event: Event) -> None:
            pass

        await bus.subscribe(EventType.MARKET_DATA, handler)
        await bus.unsubscribe(EventType.MARKET_DATA, handler)

        mock_pubsub.unsubscribe.assert_awaited_once_with("hermes:market_data")
        assert EventType.MARKET_DATA not in bus._listener_tasks

    @pytest.mark.asyncio
    async def test_channel_name_formatting(self) -> None:
        """Verify channel naming convention."""
        assert RedisEventBus._channel_name(EventType.MARKET_DATA) == "hermes:market_data"
        assert RedisEventBus._channel_name(EventType.TRADE_SIGNAL) == "hermes:trade_signal"
        assert RedisEventBus._channel_name(EventType.RISK_ALERT) == "hermes:risk_alert"


# ---------------------------------------------------------------------------
# EventBus ABC tests
# ---------------------------------------------------------------------------

class TestEventBusABC:
    """Tests verifying the EventBus abstract base class contract."""

    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            EventBus()  # type: ignore[abstract]

    def test_in_memory_bus_is_event_bus(self) -> None:
        bus = InMemoryEventBus()
        assert isinstance(bus, EventBus)

    def test_redis_bus_is_event_bus(self, mock_redis: MagicMock) -> None:
        bus = RedisEventBus(redis_client=mock_redis)
        assert isinstance(bus, EventBus)

    @pytest.fixture
    def mock_redis(self) -> MagicMock:
        redis_mock = MagicMock()
        redis_mock.publish = AsyncMock()
        redis_mock.pubsub = MagicMock()
        return redis_mock
