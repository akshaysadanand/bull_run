"""Unit tests for scraper module with mocked Playwright."""

from unittest.mock import MagicMock, patch

import pytest

from scraper import scrape_news


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_mock_chain(articles: list[dict] | None, raise_goto: bool = False,
                     raise_selector: bool = False):
    """Build a mock Playwright object hierarchy.

    Returns (mock_pw, mock_page, mock_browser) so tests can assert on
    specific objects without traversing a fragile 6-level chain.
    """
    mock_page = MagicMock()
    mock_page.goto.side_effect = Exception("navigation failed") if raise_goto else None
    mock_page.wait_for_selector.side_effect = (
        Exception("selector not found") if raise_selector else None
    )
    mock_page.evaluate.return_value = articles

    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page

    mock_browser = MagicMock()
    mock_browser.new_context.return_value = mock_context

    mock_chromium = MagicMock()
    mock_chromium.launch.return_value = mock_browser

    mock_pw = MagicMock()
    mock_pw.__enter__ = MagicMock(return_value=mock_pw)
    mock_pw.__exit__ = MagicMock(return_value=False)
    mock_pw.chromium = mock_chromium

    return mock_pw, mock_page, mock_browser


def _sample_articles(count: int) -> list[dict]:
    return [
        {
            "title": f"Article {i}",
            "source": f"Source {i}",
            "date": f"{i}h ago",
            "url": f"https://example.com/article{i}",
            "snippet": "",
        }
        for i in range(count)
    ]


# ── Tests ────────────────────────────────────────────────────────────────

class TestScrapeNewsSuccess:
    """Happy-path: valid ticker, page loads, articles returned."""

    def test_returns_list_of_dicts_with_correct_keys(self):
        expected = _sample_articles(3)
        mock_pw, _page, _browser = _make_mock_chain(expected)

        with patch("scraper.sync_playwright", return_value=mock_pw):
            result = scrape_news("AAPL")

        assert isinstance(result, list)
        assert len(result) == 3
        for article in result:
            assert set(article.keys()) == {"title", "source", "date", "url", "snippet"}

    def test_returns_all_articles_when_fewer_than_15(self):
        expected = _sample_articles(5)
        mock_pw, _page, _browser = _make_mock_chain(expected)

        with patch("scraper.sync_playwright", return_value=mock_pw):
            result = scrape_news("AAPL")

        assert len(result) == 5

    def test_normalizes_ticker_to_uppercase(self):
        mock_pw, mock_page, _browser = _make_mock_chain(_sample_articles(1))

        with patch("scraper.sync_playwright", return_value=mock_pw):
            scrape_news("aapl")

        mock_page.goto.assert_called_once()
        assert "AAPL" in mock_page.goto.call_args[0][0]

    def test_strips_whitespace_from_ticker(self):
        mock_pw, mock_page, _browser = _make_mock_chain(_sample_articles(1))

        with patch("scraper.sync_playwright", return_value=mock_pw):
            scrape_news("  AAPL  ")

        mock_page.goto.assert_called_once()
        assert "AAPL" in mock_page.goto.call_args[0][0]

    def test_closes_browser_on_success(self):
        mock_pw, _page, mock_browser = _make_mock_chain(_sample_articles(1))

        with patch("scraper.sync_playwright", return_value=mock_pw):
            scrape_news("AAPL")

        mock_browser.close.assert_called_once()


class TestScrapeNewsInputValidation:
    """Empty or whitespace-only tickers should return [] immediately."""

    def test_empty_string_returns_empty_list(self):
        result = scrape_news("")
        assert result == []

    def test_whitespace_only_returns_empty_list(self):
        result = scrape_news("   ")
        assert result == []


class TestScrapeNewsNavigationFailure:
    """When page.goto raises, return [] and close browser."""

    def test_navigation_error_returns_empty_list(self):
        mock_pw, _page, _browser = _make_mock_chain([], raise_goto=True)

        with patch("scraper.sync_playwright", return_value=mock_pw):
            result = scrape_news("AAPL")

        assert result == []

    def test_navigation_error_closes_browser(self):
        mock_pw, _page, mock_browser = _make_mock_chain([], raise_goto=True)

        with patch("scraper.sync_playwright", return_value=mock_pw):
            scrape_news("AAPL")

        mock_browser.close.assert_called_once()


class TestScrapeNewsSelectorFailure:
    """When news-stream selector is not found, return []."""

    def test_selector_not_found_returns_empty_list(self):
        mock_pw, _page, _browser = _make_mock_chain([], raise_selector=True)

        with patch("scraper.sync_playwright", return_value=mock_pw):
            result = scrape_news("AAPL")

        assert result == []

    def test_selector_not_found_closes_browser(self):
        mock_pw, _page, mock_browser = _make_mock_chain([], raise_selector=True)

        with patch("scraper.sync_playwright", return_value=mock_pw):
            scrape_news("AAPL")

        mock_browser.close.assert_called_once()


class TestScrapeNewsEdgeCases:
    """Edge cases for page.evaluate return values."""

    def test_evaluate_none_returns_empty_list(self):
        mock_pw, _page, _browser = _make_mock_chain(None)

        with patch("scraper.sync_playwright", return_value=mock_pw):
            result = scrape_news("AAPL")

        assert result == []

    def test_evaluate_empty_list_returns_empty_list(self):
        mock_pw, _page, _browser = _make_mock_chain([])

        with patch("scraper.sync_playwright", return_value=mock_pw):
            result = scrape_news("AAPL")

        assert result == []
