"""Sentiment analysis pipeline — FinBERT-based financial text sentiment."""

from datetime import datetime

import structlog

from hermes_trade.models import NewsItem, SentimentLabel, SentimentSignal

logger = structlog.get_logger(__name__)


class SentimentAnalyzer:
    """Analyzes financial text sentiment using a configurable model.

    In production, this wraps HuggingFace transformers (FinBERT).
    For testing/demo, a heuristic fallback is provided.

    Args:
        model_name: HuggingFace model ID (default: ProsusAI/finbert).
        use_heuristic: If True, use keyword-based fallback (no GPU needed).
    """

    # Financial sentiment keywords for heuristic mode
    POSITIVE_KEYWORDS: set[str] = {
        "beat", "beats", "surge", "surges", "rally", "rallies",
        "upgrade", "upgrades", "outperform", "bullish", "growth",
        "profit", "profits", "record", "raised", "raises",
        "positive", "strong", "gain", "gains", "jump", "jumps",
        "boost", "boosts", "exceed", "exceeds", "optimistic",
    }
    NEGATIVE_KEYWORDS: set[str] = {
        "miss", "misses", "plunge", "plunges", "crash", "crashes",
        "downgrade", "downgrades", "underperform", "bearish", "decline",
        "loss", "losses", "cut", "cuts", "negative", "weak",
        "drop", "drops", "fall", "falls", "warn", "warns",
        "risk", "risks", "concern", "concerns", "fear", "fears",
        "recession", "inflation", "crisis", "default",
    }

    def __init__(
        self,
        model_name: str = "ProsusAI/finbert",
        use_heuristic: bool = False,
    ) -> None:
        self.model_name = model_name
        self.use_heuristic = use_heuristic
        self._model: object | None = None

    async def analyze(self, news_item: NewsItem) -> SentimentSignal:
        """Analyze a single news item and return a sentiment signal.

        Args:
            news_item: The news article or social post to analyze.

        Returns:
            SentimentSignal with label, score, and confidence.
        """
        text = f"{news_item.title}. {news_item.content}"

        if self.use_heuristic:
            label, score = self._heuristic_analyze(text)
        else:
            label, score = await self._model_analyze(text)

        confidence = self._compute_confidence(score)

        return SentimentSignal(
            news_item_id=news_item.title[:50],
            symbol=news_item.symbols[0] if news_item.symbols else "UNKNOWN",
            label=label,
            score=score,
            confidence=confidence,
            model_name=self.model_name,
            analyzed_at=datetime.utcnow(),
        )

    def _heuristic_analyze(self, text: str) -> tuple[SentimentLabel, float]:
        """Keyword-based sentiment analysis (no ML model required).

        Args:
            text: The text to analyze (lowercased internally).

        Returns:
            Tuple of (label, score) where score is 0.0-1.0.
        """
        text_lower = text.lower()
        words = set(text_lower.split())

        positive_count = len(words & self.POSITIVE_KEYWORDS)
        negative_count = len(words & self.NEGATIVE_KEYWORDS)

        total = positive_count + negative_count
        if total == 0:
            return SentimentLabel.NEUTRAL, 0.5

        if positive_count > negative_count:
            score = 0.5 + (0.5 * positive_count / total)
            return SentimentLabel.POSITIVE, min(score, 1.0)
        elif negative_count > positive_count:
            score = 0.5 - (0.5 * negative_count / total)
            return SentimentLabel.NEGATIVE, max(score, 0.0)
        else:
            return SentimentLabel.NEUTRAL, 0.5

    async def _model_analyze(self, text: str) -> tuple[SentimentLabel, float]:
        """Analyze using the actual HuggingFace model.

        This is a placeholder — in production, loads FinBERT via transformers.
        """
        # TODO: Implement actual model inference
        # For now, fall back to heuristic
        logger.warning(
            "model_not_loaded",
            model=self.model_name,
            fallback="heuristic",
        )
        return self._heuristic_analyze(text)

    @staticmethod
    def _compute_confidence(score: float) -> float:
        """Compute confidence based on distance from neutral (0.5).

        Args:
            score: Sentiment score between 0.0 and 1.0.

        Returns:
            Confidence between 0.0 and 1.0.
        """
        return abs(score - 0.5) * 2.0

    async def analyze_batch(self, items: list[NewsItem]) -> list[SentimentSignal]:
        """Analyze multiple news items.

        Args:
            items: List of news items to analyze.

        Returns:
            List of sentiment signals in the same order.
        """
        signals: list[SentimentSignal] = []
        for item in items:
            signal = await self.analyze(item)
            signals.append(signal)
        return signals
