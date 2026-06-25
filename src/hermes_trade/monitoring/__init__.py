"""RSS/Atom feed monitor — polls configured feeds and emits NewsItem events."""

import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import httpx
import structlog

from hermes_trade.models import NewsItem

logger = structlog.get_logger(__name__)


class RSSMonitor:
    """Polls RSS/Atom feeds and yields NewsItem events.

    Args:
        feeds: List of feed URLs to monitor.
        poll_interval: Seconds between poll cycles.
        http_client: Optional httpx.AsyncClient (creates one if not provided).
    """

    def __init__(
        self,
        feeds: list[str],
        poll_interval: int = 60,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        if not feeds:
            raise ValueError("At least one feed URL is required")
        if poll_interval < 1:
            raise ValueError("Poll interval must be >= 1 second")

        self.feeds = feeds
        self.poll_interval = poll_interval
        self._client = http_client
        self._own_client = http_client is None
        self._last_etags: dict[str, str] = {}

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "HermesTrade/0.1 RSS Monitor"},
            )
        return self._client

    async def _fetch_feed(self, feed_url: str) -> list[NewsItem]:
        """Fetch a single feed and parse entries into NewsItems."""
        client = await self._ensure_client()
        headers: dict[str, str] = {}
        if feed_url in self._last_etags:
            headers["If-None-Match"] = self._last_etags[feed_url]

        try:
            response = await client.get(feed_url, headers=headers)
        except httpx.RequestError as e:
            logger.warning("feed_fetch_failed", url=feed_url, error=str(e))
            return []

        if response.status_code == 304:
            return []  # Not modified

        if response.status_code != 200:
            logger.warning(
                "feed_http_error", url=feed_url, status=response.status_code
            )
            return []

        etag = response.headers.get("etag")
        if etag:
            self._last_etags[feed_url] = etag

        return self._parse_feed(feed_url, response.text)

    def _parse_feed(self, feed_url: str, xml_content: str) -> list[NewsItem]:
        """Parse RSS 2.0 or Atom feed XML into NewsItem list."""
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            logger.warning("feed_parse_error", url=feed_url, error=str(e))
            return []

        source = urlparse(feed_url).netloc
        items: list[NewsItem] = []

        # RSS 2.0
        for item in root.findall(".//item"):
            title_el = item.find("title")
            desc_el = item.find("description")
            link_el = item.find("link")
            date_el = item.find("pubDate")

            title = title_el.text if title_el is not None and title_el.text else ""
            content = desc_el.text if desc_el is not None and desc_el.text else ""
            link = link_el.text if link_el is not None and link_el.text else None

            if not title or not content:
                continue

            published_at = self._parse_date(
                date_el.text if date_el is not None and date_el.text else None
            )

            items.append(
                NewsItem(
                    source=source,
                    source_url=link,
                    title=title.strip(),
                    content=content.strip(),
                    published_at=published_at,
                )
            )

        # Atom
        for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
            title_el = entry.find("{http://www.w3.org/2005/Atom}title")
            summary_el = entry.find("{http://www.w3.org/2005/Atom}summary")
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")
            updated_el = entry.find("{http://www.w3.org/2005/Atom}updated")

            title = title_el.text if title_el is not None and title_el.text else ""
            content = (
                summary_el.text if summary_el is not None and summary_el.text else ""
            )
            link = (
                link_el.attrib.get("href")
                if link_el is not None
                else None
            )

            if not title or not content:
                continue

            published_at = self._parse_date(
                updated_el.text if updated_el is not None and updated_el.text else None
            )

            items.append(
                NewsItem(
                    source=source,
                    source_url=link,
                    title=title.strip(),
                    content=content.strip(),
                    published_at=published_at,
                )
            )

        return items

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> datetime:
        """Parse common RSS/Atom date formats."""
        if not date_str:
            return datetime.utcnow()

        formats = [
            "%a, %d %b %Y %H:%M:%S %z",  # RFC 2822
            "%Y-%m-%dT%H:%M:%S%z",  # ISO 8601 with tz
            "%Y-%m-%dT%H:%M:%SZ",  # ISO 8601 UTC
            "%Y-%m-%dT%H:%M:%S",  # ISO 8601 no tz
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        return datetime.utcnow()

    async def poll(self) -> list[NewsItem]:
        """Poll all feeds once and return new items."""
        tasks = [self._fetch_feed(feed) for feed in self.feeds]
        results = await asyncio.gather(*tasks)
        all_items: list[NewsItem] = []
        for items in results:
            all_items.extend(items)
        logger.info("rss_poll_complete", feeds=len(self.feeds), items=len(all_items))
        return all_items

    async def run_forever(self) -> None:
        """Run continuous polling loop. Yields items via callback."""
        try:
            while True:
                await self.poll()
                await asyncio.sleep(self.poll_interval)
        finally:
            if self._own_client and self._client is not None:
                await self._client.aclose()
