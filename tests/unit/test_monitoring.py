"""Tests for RSS/Atom feed monitor."""

from datetime import datetime

import pytest

from hermes_trade.monitoring import RSSMonitor


class TestRSSMonitorInit:
    def test_requires_at_least_one_feed(self) -> None:
        with pytest.raises(ValueError, match="At least one feed URL"):
            RSSMonitor(feeds=[])

    def test_rejects_negative_poll_interval(self) -> None:
        with pytest.raises(ValueError, match="Poll interval must be >= 1"):
            RSSMonitor(feeds=["https://example.com/rss"], poll_interval=0)

    def test_valid_initialization(self) -> None:
        monitor = RSSMonitor(
            feeds=["https://example.com/rss"],
            poll_interval=30,
        )
        assert monitor.feeds == ["https://example.com/rss"]
        assert monitor.poll_interval == 30


class TestRSSMonitorDateParsing:
    def test_parse_rfc2822_date(self) -> None:
        result = RSSMonitor._parse_date("Wed, 25 Jun 2026 14:30:00 +0000")
        assert result.year == 2026
        assert result.month == 6
        assert result.day == 25

    def test_parse_iso8601_with_tz(self) -> None:
        result = RSSMonitor._parse_date("2026-06-25T14:30:00+0000")
        assert result.year == 2026

    def test_parse_iso8601_utc_z(self) -> None:
        result = RSSMonitor._parse_date("2026-06-25T14:30:00Z")
        assert result.year == 2026

    def test_parse_none_returns_now(self) -> None:
        result = RSSMonitor._parse_date(None)
        assert isinstance(result, datetime)

    def test_parse_invalid_returns_now(self) -> None:
        result = RSSMonitor._parse_date("not a date")
        assert isinstance(result, datetime)


RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <description>Test RSS feed</description>
    <item>
      <title>Fed Raises Rates</title>
      <link>https://example.com/article/1</link>
      <description>The Federal Reserve raised interest rates by 25 basis points today.</description>
      <pubDate>Wed, 25 Jun 2026 14:30:00 +0000</pubDate>
    </item>
    <item>
      <title>Market Update</title>
      <link>https://example.com/article/2</link>
      <description>Markets rallied on positive earnings reports.</description>
      <pubDate>Wed, 25 Jun 2026 15:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""

ATOM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Atom Feed</title>
  <link href="https://example.com/atom"/>
  <entry>
    <title>ECB Decision</title>
    <link href="https://example.com/article/3"/>
    <summary>The ECB held rates steady at 4.25%.</summary>
    <updated>2026-06-25T14:00:00Z</updated>
  </entry>
</feed>"""


class TestRSSMonitorParsing:
    def test_parse_rss_feed(self) -> None:
        monitor = RSSMonitor(feeds=["https://example.com/rss"])
        items = monitor._parse_feed("https://example.com/rss", RSS_XML)
        assert len(items) == 2
        assert items[0].title == "Fed Raises Rates"
        assert items[0].source == "example.com"
        assert items[0].source_url == "https://example.com/article/1"
        assert "Federal Reserve" in items[0].content

    def test_parse_atom_feed(self) -> None:
        monitor = RSSMonitor(feeds=["https://example.com/atom"])
        items = monitor._parse_feed("https://example.com/atom", ATOM_XML)
        assert len(items) == 1
        assert items[0].title == "ECB Decision"
        assert "ECB" in items[0].content

    def test_parse_invalid_xml_returns_empty(self) -> None:
        monitor = RSSMonitor(feeds=["https://example.com/rss"])
        items = monitor._parse_feed("https://example.com/rss", "<not>valid xml")
        assert items == []

    def test_parse_empty_feed(self) -> None:
        monitor = RSSMonitor(feeds=["https://example.com/rss"])
        items = monitor._parse_feed(
            "https://example.com/rss",
            '<rss version="2.0"><channel></channel></rss>',
        )
        assert items == []
