"""Risk manager — validates trade signals against configured risk limits."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

import structlog

from hermes_trade.models import OrderSide, RiskLimits, TradeSignal

logger = structlog.get_logger(__name__)


@dataclass
class RiskCheckResult:
    """Result of a risk check on a trade signal."""

    approved: bool
    reason: str
    checked_at: datetime = field(default_factory=datetime.utcnow)


class RiskManager:
    """Validates trade signals against risk limits.

    Tracks daily P&L, trade count, and position sizes to enforce limits.

    Args:
        limits: Risk limit configuration.
    """

    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits
        self._daily_trades: int = 0
        self._daily_pnl: Decimal = Decimal("0")
        self._positions: dict[str, Decimal] = {}
        self._last_reset: datetime = datetime.utcnow()

    def _reset_daily_if_needed(self) -> None:
        """Reset daily counters if a new day has started."""
        now = datetime.utcnow()
        if now.date() > self._last_reset.date():
            self._daily_trades = 0
            self._daily_pnl = Decimal("0")
            self._last_reset = now

    def check_signal(self, signal: TradeSignal) -> RiskCheckResult:
        """Check if a trade signal passes all risk limits.

        Args:
            signal: The trade signal to validate.

        Returns:
            RiskCheckResult indicating approval or rejection with reason.
        """
        self._reset_daily_if_needed()

        # Check daily trade limit
        if self._daily_trades >= self.limits.max_trades_per_day:
            return RiskCheckResult(
                approved=False,
                reason=f"Daily trade limit reached ({self.limits.max_trades_per_day})",
            )

        # Check position size
        if signal.quantity > self.limits.max_position_size:
            return RiskCheckResult(
                approved=False,
                reason=f"Position size {signal.quantity} exceeds max {self.limits.max_position_size}",
            )

        # Check daily loss limit
        if self._daily_pnl <= -self.limits.max_daily_loss:
            return RiskCheckResult(
                approved=False,
                reason=f"Daily loss limit reached ({self.limits.max_daily_loss})",
            )

        # Check confidence threshold
        if signal.confidence < 0.5:
            return RiskCheckResult(
                approved=False,
                reason=f"Signal confidence too low ({signal.confidence:.2f})",
            )

        return RiskCheckResult(approved=True, reason="All checks passed")

    def record_trade(self, signal: TradeSignal) -> None:
        """Record a trade after it passes risk checks.

        Args:
            signal: The approved trade signal.
        """
        self._daily_trades += 1
        current = self._positions.get(signal.symbol, Decimal("0"))
        if signal.side == OrderSide.BUY:
            self._positions[signal.symbol] = current + signal.quantity
        else:
            self._positions[signal.symbol] = current - signal.quantity

    def record_pnl(self, amount: Decimal) -> None:
        """Record realized P&L for daily loss tracking.

        Args:
            amount: Profit (positive) or loss (negative).
        """
        self._daily_pnl += amount

    @property
    def daily_trades(self) -> int:
        """Number of trades executed today."""
        self._reset_daily_if_needed()
        return self._daily_trades

    @property
    def daily_pnl(self) -> Decimal:
        """Cumulative P&L for today."""
        self._reset_daily_if_needed()
        return self._daily_pnl

    @property
    def positions(self) -> dict[str, Decimal]:
        """Current position sizes by symbol."""
        return dict(self._positions)
