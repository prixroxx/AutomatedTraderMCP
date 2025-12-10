"""
Tests for News Fetcher.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from src.trader.data.news_fetcher import NewsFetcher, NewsArticle


@pytest.fixture
def news_fetcher():
    """Create a news fetcher instance."""
    return NewsFetcher(cache_duration_minutes=15)


@pytest.fixture
def sample_articles():
    """Create sample news articles."""
    now = datetime.now()
    return [
        NewsArticle(
            title="Reliance Industries Q4 results beat expectations",
            link="https://example.com/1",
            published=now - timedelta(hours=1),
            summary="Reliance Industries reported strong Q4 results...",
            source="MoneyControl",
            symbols=["RELIANCE"]
        ),
        NewsArticle(
            title="TCS announces share buyback",
            link="https://example.com/2",
            published=now - timedelta(hours=2),
            summary="Tata Consultancy Services announces buyback...",
            source="Economic Times",
            symbols=["TCS"]
        ),
        NewsArticle(
            title="Indian markets reach new high",
            link="https://example.com/3",
            published=now - timedelta(hours=3),
            summary="Indian equity markets touched new highs...",
            source="LiveMint",
            symbols=[]
        )
    ]


def test_fetcher_initialization(news_fetcher):
    """Test news fetcher initializes correctly."""
    assert news_fetcher.cache_duration == timedelta(minutes=15)
    assert len(news_fetcher._cache) == 0
    assert len(news_fetcher._cache_timestamp) == 0


def test_available_sources(news_fetcher):
    """Test getting available news sources."""
    sources = news_fetcher.get_available_sources()

    assert len(sources) > 0
    assert "MoneyControl" in sources or "Economic Times" in sources


def test_add_custom_source(news_fetcher):
    """Test adding custom news source."""
    news_fetcher.add_custom_source("CustomSource", "https://example.com/rss")

    sources = news_fetcher.get_available_sources()
    assert "CustomSource" in sources


def test_extract_symbols():
    """Test symbol extraction from text."""
    fetcher = NewsFetcher()

    text = "RELIANCE reported strong results. TCS and INFY also performed well."
    symbols = fetcher._extract_symbols(text)

    assert "RELIANCE" in symbols
    assert "TCS" in symbols
    assert "INFY" in symbols


def test_article_mentions_symbol(sample_articles):
    """Test checking if article mentions a symbol."""
    fetcher = NewsFetcher()

    article = sample_articles[0]
    assert fetcher._article_mentions_symbol(article, "RELIANCE") is True
    assert fetcher._article_mentions_symbol(article, "TCS") is False


def test_clear_cache(news_fetcher, sample_articles):
    """Test cache clearing."""
    # Add to cache
    news_fetcher._cache["MoneyControl"] = sample_articles
    news_fetcher._cache_timestamp["MoneyControl"] = datetime.now()

    # Clear cache
    news_fetcher.clear_cache()

    assert len(news_fetcher._cache) == 0
    assert len(news_fetcher._cache_timestamp) == 0


def test_cache_validation(news_fetcher, sample_articles):
    """Test cache validity checking."""
    source = "MoneyControl"

    # No cache
    assert news_fetcher._is_cache_valid(source) is False

    # Fresh cache
    news_fetcher._cache[source] = sample_articles
    news_fetcher._cache_timestamp[source] = datetime.now()
    assert news_fetcher._is_cache_valid(source) is True

    # Expired cache
    news_fetcher._cache_timestamp[source] = datetime.now() - timedelta(hours=1)
    assert news_fetcher._is_cache_valid(source) is False


@patch('feedparser.parse')
def test_fetch_from_source(mock_parse, news_fetcher):
    """Test fetching from a specific source."""
    # Mock feedparser response
    mock_parse.return_value = Mock(
        entries=[
            {
                'title': 'Test Article',
                'link': 'https://example.com/test',
                'summary': 'Test summary with RELIANCE mentioned',
                'published_parsed': None
            }
        ]
    )

    articles = news_fetcher._fetch_from_source("MoneyControl")

    assert len(articles) > 0
    assert articles[0].title == 'Test Article'
    assert articles[0].source == "MoneyControl"


def test_parse_published_date():
    """Test date parsing from feed entry."""
    fetcher = NewsFetcher()

    # Entry with no date
    entry = {}
    parsed_date = fetcher._parse_published_date(entry)
    assert isinstance(parsed_date, datetime)

    # Entry with published_parsed
    import time
    now = datetime.now()
    entry_with_date = {
        'published_parsed': time.struct_time(now.timetuple())
    }
    parsed_date = fetcher._parse_published_date(entry_with_date)
    assert isinstance(parsed_date, datetime)


def test_news_summary_structure():
    """Test news summary structure."""
    fetcher = NewsFetcher()

    # Mock fetch_latest_news to return sample data
    with patch.object(fetcher, 'fetch_latest_news') as mock_fetch:
        now = datetime.now()
        mock_fetch.return_value = [
            NewsArticle(
                title="Test 1",
                link="http://example.com/1",
                published=now,
                summary="Test",
                source="Source1",
                symbols=["RELIANCE", "TCS"]
            ),
            NewsArticle(
                title="Test 2",
                link="http://example.com/2",
                published=now - timedelta(hours=1),
                summary="Test",
                source="Source2",
                symbols=["RELIANCE"]
            )
        ]

        summary = fetcher.get_news_summary(hours_back=24)

        assert 'total_articles' in summary
        assert 'by_source' in summary
        assert 'top_symbols' in summary
        assert 'latest_articles' in summary

        # Check top symbols
        assert len(summary['top_symbols']) > 0
        top_symbol = summary['top_symbols'][0]
        assert 'symbol' in top_symbol
        assert 'mentions' in top_symbol


def test_fetch_news_for_symbol():
    """Test fetching news for specific symbol."""
    fetcher = NewsFetcher()

    with patch.object(fetcher, 'fetch_latest_news') as mock_fetch:
        now = datetime.now()
        mock_fetch.return_value = [
            NewsArticle(
                title="Reliance results",
                link="http://example.com/1",
                published=now,
                summary="RELIANCE reported strong results",
                source="Source1",
                symbols=["RELIANCE"]
            ),
            NewsArticle(
                title="TCS buyback",
                link="http://example.com/2",
                published=now,
                summary="TCS announces buyback",
                source="Source2",
                symbols=["TCS"]
            )
        ]

        reliance_news = fetcher.fetch_news_for_symbol("RELIANCE")

        assert len(reliance_news) > 0
        assert all("RELIANCE" in article.symbols for article in reliance_news)


def test_html_tag_removal():
    """Test HTML tag removal from summary."""
    fetcher = NewsFetcher()

    with patch('feedparser.parse') as mock_parse:
        mock_parse.return_value = Mock(
            entries=[
                {
                    'title': 'Test',
                    'link': 'http://example.com',
                    'summary': '<p>This is a <strong>test</strong> summary</p>',
                    'published_parsed': None
                }
            ]
        )

        articles = fetcher._fetch_from_source("TestSource")
        assert len(articles) > 0
        # HTML tags should be removed
        assert '<' not in articles[0].summary
        assert '>' not in articles[0].summary
