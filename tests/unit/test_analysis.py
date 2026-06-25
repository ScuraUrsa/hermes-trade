"""Tests for sentiment analysis pipeline."""

from datetime import datetime

import pytest

from hermes_trade.analysis import SentimentAnalyzer
from hermes_trade.models import NewsItem, SentimentLabel


@pytest.fixture
def analyzer() -> SentimentAnalyzer:
    return SentimentAnalyzer(use_heuristic=True)


class TestSentimentAnalyzerHeuristic:
    async def test_positive_sentiment(self, analyzer: SentimentAnalyzer) -> None:
        news = NewsItem(
            source="Reuters",
            title="Fed raises rates",
            content="Markets surge on strong profit growth and record earnings. Bullish outlook.",
            published_at=datetime(2026, 6, 25),
            symbols=["SPY"],
        )
        signal = await analyzer.analyze(news)
        assert signal.label == SentimentLabel.POSITIVE
        assert signal.score > 0.5
        assert signal.confidence > 0.0

    async def test_negative_sentiment(self, analyzer: SentimentAnalyzer) -> None:
        news = NewsItem(
            source="Reuters",
            title="Market crash fears",
            content="Stocks plunge on recession concerns and inflation fears. Bearish sentiment.",
            published_at=datetime(2026, 6, 25),
            symbols=["SPY"],
        )
        signal = await analyzer.analyze(news)
        assert signal.label == SentimentLabel.NEGATIVE
        assert signal.score < 0.5

    async def test_neutral_sentiment(self, analyzer: SentimentAnalyzer) -> None:
        news = NewsItem(
            source="Reuters",
            title="Markets close flat",
            content="Stocks ended the day unchanged with low volume trading.",
            published_at=datetime(2026, 6, 25),
            symbols=["SPY"],
        )
        signal = await analyzer.analyze(news)
        assert signal.label == SentimentLabel.NEUTRAL
        assert signal.score == 0.5

    async def test_confidence_computation(self, analyzer: SentimentAnalyzer) -> None:
        # Strong positive should have high confidence
        news = NewsItem(
            source="Reuters",
            title="Record profits",
            content="surge surge surge rally rally profit profit record record",
            published_at=datetime(2026, 6, 25),
        )
        signal = await analyzer.analyze(news)
        assert signal.confidence > 0.5

    async def test_analyze_batch(self, analyzer: SentimentAnalyzer) -> None:
        items = [
            NewsItem(
                source="Reuters",
                title="Bullish outlook",
                content="Markets surge on strong growth.",
                published_at=datetime(2026, 6, 25),
            ),
            NewsItem(
                source="Reuters",
                title="Bearish warning",
                content="Stocks plunge on recession fears.",
                published_at=datetime(2026, 6, 25),
            ),
        ]
        signals = await analyzer.analyze_batch(items)
        assert len(signals) == 2
        assert signals[0].label == SentimentLabel.POSITIVE
        assert signals[1].label == SentimentLabel.NEGATIVE

    async def test_uses_first_symbol(self, analyzer: SentimentAnalyzer) -> None:
        news = NewsItem(
            source="Reuters",
            title="AAPL beats estimates",
            content="Apple reported record profits.",
            published_at=datetime(2026, 6, 25),
            symbols=["AAPL", "QQQ"],
        )
        signal = await analyzer.analyze(news)
        assert signal.symbol == "AAPL"

    async def test_no_symbols_defaults_to_unknown(self, analyzer: SentimentAnalyzer) -> None:
        news = NewsItem(
            source="Reuters",
            title="Market update",
            content="General market news.",
            published_at=datetime(2026, 6, 25),
        )
        signal = await analyzer.analyze(news)
        assert signal.symbol == "UNKNOWN"


class TestSentimentAnalyzerInit:
    def test_default_model_name(self) -> None:
        analyzer = SentimentAnalyzer()
        assert analyzer.model_name == "ProsusAI/finbert"

    def test_custom_model_name(self) -> None:
        analyzer = SentimentAnalyzer(model_name="custom/model")
        assert analyzer.model_name == "custom/model"

    def test_heuristic_mode_flag(self) -> None:
        analyzer = SentimentAnalyzer(use_heuristic=True)
        assert analyzer.use_heuristic is True
