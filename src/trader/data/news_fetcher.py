"""
News Fetcher for Market News.

Fetches news from RSS feeds of major Indian financial news sources.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import feedparser
import re

from ..core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class NewsArticle:
    """Represents a news article."""
    title: str
    link: str
    published: datetime
    summary: str
    source: str
    symbols: List[str] = None  # Extracted stock symbols


class NewsFetcher:
    """
    Fetches financial news from RSS feeds.

    Supports multiple Indian financial news sources and can filter
    news by stock symbols.
    """

    # RSS Feed URLs for Indian financial news
    RSS_FEEDS = {
        'MoneyControl': 'https://www.moneycontrol.com/rss/latestnews.xml',
        'Economic Times': 'https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms',
        'Business Standard': 'https://www.business-standard.com/rss/markets-106.rss',
        'LiveMint': 'https://www.livemint.com/rss/markets',
        'NDTV Profit': 'https://www.ndtvprofit.com/rss/markets'
    }

    def __init__(self, cache_duration_minutes: int = 15):
        """
        Initialize news fetcher.

        Args:
            cache_duration_minutes: How long to cache fetched news (default: 15 minutes)
        """
        self.cache_duration = timedelta(minutes=cache_duration_minutes)
        self._cache: Dict[str, List[NewsArticle]] = {}
        self._cache_timestamp: Dict[str, datetime] = {}

        logger.info(
            "News fetcher initialized",
            sources=len(self.RSS_FEEDS),
            cache_duration=cache_duration_minutes
        )

    def fetch_latest_news(
        self,
        sources: Optional[List[str]] = None,
        limit: int = 10
    ) -> List[NewsArticle]:
        """
        Fetch latest news from RSS feeds.

        Args:
            sources: List of source names to fetch from (None = all sources)
            limit: Maximum number of articles to return

        Returns:
            List of NewsArticle objects, sorted by publication date (newest first)
        """
        if sources is None:
            sources = list(self.RSS_FEEDS.keys())

        all_articles = []

        for source in sources:
            if source not in self.RSS_FEEDS:
                logger.warning(f"Unknown news source: {source}")
                continue

            # Check cache
            if self._is_cache_valid(source):
                logger.debug(f"Using cached news for {source}")
                all_articles.extend(self._cache[source])
                continue

            # Fetch from RSS feed
            try:
                articles = self._fetch_from_source(source)
                self._cache[source] = articles
                self._cache_timestamp[source] = datetime.now()
                all_articles.extend(articles)

                logger.info(
                    f"Fetched news from {source}",
                    articles_count=len(articles)
                )

            except Exception as e:
                logger.error(f"Error fetching news from {source}: {e}")
                continue

        # Sort by publication date (newest first)
        all_articles.sort(key=lambda x: x.published, reverse=True)

        # Apply limit
        return all_articles[:limit]

    def fetch_news_for_symbol(
        self,
        symbol: str,
        sources: Optional[List[str]] = None,
        limit: int = 5
    ) -> List[NewsArticle]:
        """
        Fetch news articles mentioning a specific stock symbol.

        Args:
            symbol: Stock symbol to search for (e.g., "RELIANCE", "TCS")
            sources: List of source names to fetch from (None = all sources)
            limit: Maximum number of articles to return

        Returns:
            List of NewsArticle objects mentioning the symbol
        """
        logger.info(f"Fetching news for {symbol}")

        # Fetch all latest news
        all_news = self.fetch_latest_news(sources=sources, limit=50)

        # Filter by symbol
        symbol_news = []
        for article in all_news:
            if self._article_mentions_symbol(article, symbol):
                # Add symbol to article
                if article.symbols is None:
                    article.symbols = []
                if symbol not in article.symbols:
                    article.symbols.append(symbol)
                symbol_news.append(article)

        logger.info(
            f"Found {len(symbol_news)} articles mentioning {symbol}"
        )

        return symbol_news[:limit]

    def _fetch_from_source(self, source: str) -> List[NewsArticle]:
        """
        Fetch news from a specific RSS feed.

        Args:
            source: Source name

        Returns:
            List of NewsArticle objects
        """
        feed_url = self.RSS_FEEDS[source]
        articles = []

        try:
            feed = feedparser.parse(feed_url)

            for entry in feed.entries:
                # Parse publication date
                published = self._parse_published_date(entry)

                # Extract summary
                summary = entry.get('summary', entry.get('description', ''))
                # Clean HTML tags from summary
                summary = re.sub(r'<[^>]+>', '', summary)

                article = NewsArticle(
                    title=entry.get('title', 'No title'),
                    link=entry.get('link', ''),
                    published=published,
                    summary=summary[:500],  # Limit summary length
                    source=source,
                    symbols=self._extract_symbols(entry.get('title', '') + ' ' + summary)
                )

                articles.append(article)

        except Exception as e:
            logger.error(f"Error parsing feed from {source}: {e}")

        return articles

    def _parse_published_date(self, entry: Dict) -> datetime:
        """
        Parse publication date from feed entry.

        Args:
            entry: Feed entry dict

        Returns:
            Publication datetime
        """
        # Try different date fields
        for date_field in ['published_parsed', 'updated_parsed', 'created_parsed']:
            if date_field in entry and entry[date_field]:
                try:
                    import time
                    return datetime.fromtimestamp(time.mktime(entry[date_field]))
                except Exception:
                    continue

        # Default to now if no date found
        return datetime.now()

    def _extract_symbols(self, text: str) -> List[str]:
        """
        Extract potential stock symbols from text.

        Args:
            text: Text to search

        Returns:
            List of potential stock symbols
        """
        # Common Indian stock symbols (this is a simple implementation)
        common_symbols = [
            'RELIANCE', 'TCS', 'INFY', 'HDFC', 'HDFCBANK', 'ICICIBANK',
            'SBIN', 'BAJFINANCE', 'BHARTIARTL', 'ITC', 'KOTAKBANK',
            'LT', 'AXISBANK', 'ASIANPAINT', 'MARUTI', 'TITAN',
            'WIPRO', 'NESTLEIND', 'ULTRACEMCO', 'SUNPHARMA',
            'TATASTEEL', 'TATAMOTORS', 'POWERGRID', 'NTPC', 'ONGC',
            'ADANIPORTS', 'JSWSTEEL', 'INDUSINDBK', 'TECHM', 'DRREDDY'
        ]

        symbols_found = []
        text_upper = text.upper()

        for symbol in common_symbols:
            # Look for symbol as whole word
            if re.search(r'\b' + symbol + r'\b', text_upper):
                symbols_found.append(symbol)

        return symbols_found

    def _article_mentions_symbol(self, article: NewsArticle, symbol: str) -> bool:
        """
        Check if article mentions a specific symbol.

        Args:
            article: NewsArticle to check
            symbol: Symbol to search for

        Returns:
            True if article mentions the symbol
        """
        symbol_upper = symbol.upper()

        # Check title and summary
        text = (article.title + ' ' + article.summary).upper()

        # Look for exact symbol match
        if re.search(r'\b' + symbol_upper + r'\b', text):
            return True

        # Also check extracted symbols
        if article.symbols and symbol_upper in article.symbols:
            return True

        return False

    def _is_cache_valid(self, source: str) -> bool:
        """
        Check if cached news for a source is still valid.

        Args:
            source: Source name

        Returns:
            True if cache is valid
        """
        if source not in self._cache_timestamp:
            return False

        age = datetime.now() - self._cache_timestamp[source]
        return age < self.cache_duration

    def clear_cache(self) -> None:
        """Clear the news cache."""
        self._cache = {}
        self._cache_timestamp = {}
        logger.info("News cache cleared")

    def get_available_sources(self) -> List[str]:
        """
        Get list of available news sources.

        Returns:
            List of source names
        """
        return list(self.RSS_FEEDS.keys())

    def add_custom_source(self, name: str, rss_url: str) -> None:
        """
        Add a custom RSS feed source.

        Args:
            name: Source name
            rss_url: RSS feed URL
        """
        self.RSS_FEEDS[name] = rss_url
        logger.info(f"Added custom news source: {name}")

    def get_news_summary(
        self,
        hours_back: int = 24,
        sources: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Get a summary of recent news.

        Args:
            hours_back: How many hours of news to summarize
            sources: List of sources to include (None = all)

        Returns:
            Summary dict with statistics and top articles
        """
        cutoff_time = datetime.now() - timedelta(hours=hours_back)

        articles = self.fetch_latest_news(sources=sources, limit=100)

        # Filter by time
        recent_articles = [
            a for a in articles
            if a.published >= cutoff_time
        ]

        # Count by source
        by_source = {}
        for article in recent_articles:
            by_source[article.source] = by_source.get(article.source, 0) + 1

        # Get top symbols mentioned
        all_symbols = []
        for article in recent_articles:
            if article.symbols:
                all_symbols.extend(article.symbols)

        symbol_counts = {}
        for symbol in all_symbols:
            symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1

        top_symbols = sorted(
            symbol_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]

        return {
            'total_articles': len(recent_articles),
            'time_range_hours': hours_back,
            'by_source': by_source,
            'top_symbols': [{'symbol': s, 'mentions': c} for s, c in top_symbols],
            'latest_articles': recent_articles[:5]
        }
