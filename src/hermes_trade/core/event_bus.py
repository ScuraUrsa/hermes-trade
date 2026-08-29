"""Event bus module — EventBus ABC, RedisEventBus, InMemoryEventBus.

Provides a pluggable event bus for the event-driven architecture. The
InMemoryEventBus is ideal for testing and single-process deployments; the
RedisEventBus enables multi-process / distributed event propagation.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from hermes_trade.models import (
    EventType,
    MarketData,
    NewsItem,
    Order,
    SentimentSignal,
    TradeSignal,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event wrapper
# ---------------------------------------------------------------------------

# Map EventType -> Pydantic model class for deserialization
_EVENT_TYPE_MODEL_MAP: dict[EventType, type[BaseModel] | None] = {
    EventType.MARKET_DATA: MarketData,
    EventType.NEWS_ARTICLE: NewsItem,
    EventType.SENTIMENT_SIGNAL: SentimentSignal,
    EventType.TRADE_SIGNAL: TradeSignal,
    EventType.ORDER_REQUEST: Order,
    EventType.ORDER_UPDATE: Order,
    EventType.SOCIAL_POST: NewsItem,
    EventType.RISK_ALERT: None,  # No dedicated model yet
}


class Event(BaseModel):
    """Serializable envelope for domain events flowing through the bus."""

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    event_type: EventType
    payload: dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def from_model(cls, model: BaseModel, event_type: EventType) -> Event:
        """Create an Event by serializing a Pydantic domain model into the payload."""
        payload = json.loads(model.model_dump_json())
        return cls(event_type=event_type, payload=payload)

    def deserialize_payload(self) -> BaseModel | dict[str, Any]:
        """Reconstruct the domain model from the payload, if the type is known."""
        model_cls = _EVENT_TYPE_MODEL_MAP.get(self.event_type)
        if model_cls is None:
            return self.payload
        try:
            return model_cls.model_validate(self.payload)
        except Exception:
            return self.payload


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

EventHandler = Callable[[Event], Any]


class EventBus(ABC):
    """Abstract base for all event bus implementations."""

    @abstractmethod
    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribers of its event_type."""
        ...

    @abstractmethod
    async def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Register an async handler for a specific event type."""
        ...

    @abstractmethod
    async def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Remove a previously registered handler."""
        ...


# ---------------------------------------------------------------------------
# In-memory event bus (no external dependencies)
# ---------------------------------------------------------------------------

class InMemoryEventBus(EventBus):
    """Event bus that dispatches events in-process using in-memory handler lists.

    Ideal for unit tests and single-process deployments.  Handlers are called
    sequentially; a failing handler does not prevent other handlers from
    receiving the event.
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[EventHandler]] = {}

    async def publish(self, event: Event) -> None:
        handlers = self._handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception(
                    "Handler %s failed for event %s", handler, event.event_id
                )

    async def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    async def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)


# ---------------------------------------------------------------------------
# Redis-backed event bus
# ---------------------------------------------------------------------------

class RedisEventBus(EventBus):
    """Event bus backed by Redis Pub/Sub for multi-process / distributed setups.

    Parameters
    ----------
    redis_client:
        An *async* redis-py client (``redis.asyncio.Redis``).
    """

    CHANNEL_PREFIX = "hermes"

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client
        self._pubsubs: dict[EventType, Any] = {}
        self._listener_tasks: dict[EventType, asyncio.Task[None]] = {}
        self._handlers: dict[EventType, list[EventHandler]] = {}

    @classmethod
    def _channel_name(cls, event_type: EventType) -> str:
        return f"{cls.CHANNEL_PREFIX}:{event_type.value}"

    # -- publish -----------------------------------------------------------

    async def publish(self, event: Event) -> None:
        channel = self._channel_name(event.event_type)
        message = event.model_dump_json()
        await self._redis.publish(channel, message)

    # -- subscribe ---------------------------------------------------------

    async def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

        # Only create one pubsub + listener per event_type
        if event_type in self._pubsubs:
            return

        pubsub = self._redis.pubsub()
        self._pubsubs[event_type] = pubsub
        channel = self._channel_name(event_type)
        await pubsub.subscribe(channel)

        task = asyncio.create_task(self._listen(event_type, pubsub))
        self._listener_tasks[event_type] = task

    async def _listen(self, event_type: EventType, pubsub: Any) -> None:
        """Long-running task that reads messages from the pubsub and dispatches."""
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    event = Event.model_validate_json(message["data"])
                except Exception:
                    logger.exception("Failed to deserialize event from Redis")
                    continue

                for handler in self._handlers.get(event_type, []):
                    try:
                        result = handler(event)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception:
                        logger.exception(
                            "Handler %s failed for event %s", handler, event.event_id
                        )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Listener for %s crashed", event_type)

    # -- unsubscribe -------------------------------------------------------

    async def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

        # If no more handlers, tear down the pubsub and listener
        if not handlers and event_type in self._pubsubs:
            pubsub = self._pubsubs.pop(event_type)
            channel = self._channel_name(event_type)
            await pubsub.unsubscribe(channel)

            task = self._listener_tasks.pop(event_type, None)
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
