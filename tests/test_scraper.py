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


def _sample_articles(count: int, ticker: str = "AAPL") -> list[dict]:
    return [
        {
            "title": f"{ticker} Article {i}",
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


class TestScrapeUrlsEmptyInput:
    """Empty or invalid inputs should return [] immediately."""

    def test_empty_url_list_returns_empty_list(self):
        from scraper import scrape_urls
        result = scrape_urls([], "AAPL", "http://localhost:8080/v1", "model")
        assert result == []

    def test_none_url_in_list_returns_empty_list(self):
        from scraper import scrape_urls
        result = scrape_urls([None], "AAPL", "http://localhost:8080/v1", "model")
        assert result == []

    def test_whitespace_only_urls_returns_empty_list(self):
        from scraper import scrape_urls
        result = scrape_urls(["  ", ""], "AAPL", "http://localhost:8080/v1", "model")
        assert result == []


def _make_mock_pw(articles_eval=None, goto_side_effect=None,
                  content_return=None, title_return=None, evaluate_return=None):
    """Build a mock Playwright chain for scrape_urls tests."""
    mock_page = MagicMock()
    if goto_side_effect is not None:
        mock_page.goto.side_effect = goto_side_effect
    else:
        mock_page.goto.return_value = None
    mock_page.content.return_value = content_return or "<html><body><h1>Article</h1><p>Content.</p></body></html>"
    mock_page.title.return_value = title_return or "Article"
    mock_page.inner_text.return_value = "Article\nContent."
    mock_page.evaluate.return_value = evaluate_return if evaluate_return is not None else []

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


class TestScrapeUrlsHappyPath:
    """scrape_urls visits pages, extracts content, follows child links."""

    def test_returns_articles_from_single_url(self):
        """Verify scrape_urls returns article dicts from a single URL."""
        from scraper import scrape_urls

        mock_pw, mock_page, _browser = _make_mock_pw(
            evaluate_return=[{"url": "https://example.com/child", "text": "Child Page"}]
        )

        with patch("scraper.sync_playwright", return_value=mock_pw), \
             patch("scraper._score_links", return_value=[]):
            result = scrape_urls(["https://example.com"], "AAPL", "http://localhost:8080/v1", "model")

        assert isinstance(result, list)
        assert len(result) == 1
        assert set(result[0].keys()) == {"title", "source", "date", "url", "snippet"}
        assert result[0]["url"] == "https://example.com"

    def test_respects_max_pages_limit(self):
        """Verify scrape_urls stops at max_pages."""
        from scraper import scrape_urls

        mock_pw, _page, _browser = _make_mock_pw()

        urls = [f"https://example.com/page{i}" for i in range(10)]

        with patch("scraper.sync_playwright", return_value=mock_pw), \
             patch("scraper._score_links", return_value=[]):
            result = scrape_urls(urls, "AAPL", "http://localhost:8080/v1", "model", max_pages=3)

        assert len(result) == 3

    def test_skips_already_visited_urls(self):
        """Verify duplicate URLs are not visited twice."""
        from scraper import scrape_urls

        mock_pw, _page, _browser = _make_mock_pw()

        with patch("scraper.sync_playwright", return_value=mock_pw), \
             patch("scraper._score_links", return_value=[]):
            result = scrape_urls(
                ["https://example.com", "https://example.com"],
                "AAPL", "http://localhost:8080/v1", "model"
            )

        assert len(result) == 1

    def test_skips_pdf_urls(self):
        """Verify PDF URLs are skipped without attempting navigation."""
        from scraper import scrape_urls

        mock_pw, mock_page, _browser = _make_mock_pw()

        with patch("scraper.sync_playwright", return_value=mock_pw), \
             patch("scraper._score_links", return_value=[]):
            result = scrape_urls(
                ["https://example.com/report.pdf", "https://example.com/page"],
                "AAPL", "http://localhost:8080/v1", "model"
            )

        assert len(result) == 1
        assert result[0]["url"] == "https://example.com/page"
        # PDF URL should not have triggered navigation
        assert mock_page.goto.call_count == 1


class TestScrapeUrlsNavigationFailure:
    """When page.goto raises, skip that page and continue."""

    def test_navigation_error_skips_page(self):
        from scraper import scrape_urls

        mock_pw, mock_page, _browser = _make_mock_pw(
            goto_side_effect=[Exception("timeout"), None]
        )

        with patch("scraper.sync_playwright", return_value=mock_pw), \
             patch("scraper._score_links", return_value=[]):
            result = scrape_urls(
                ["https://example.com/fail", "https://example.com/ok"],
                "AAPL", "http://localhost:8080/v1", "model"
            )

        assert len(result) == 1
        assert result[0]["url"] == "https://example.com/ok"


class TestScoreLinks:
    """LLM-based link scoring and fallback behavior."""

    def test_scores_links_with_llm(self):
        from scraper import _score_links

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "https://example.com/relevant1\nhttps://example.com/relevant2"

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        links = [
            {"url": "https://example.com/relevant1", "text": "AAPL earnings report"},
            {"url": "https://example.com/relevant2", "text": "Apple stock analysis"},
            {"url": "https://example.com/irrelevant", "text": "Weather forecast"},
        ]

        with patch("scraper.OpenAI", return_value=mock_client):
            result = _score_links(links, "AAPL", "http://localhost:8080/v1", "model")

        assert "https://example.com/relevant1" in result
        assert "https://example.com/relevant2" in result

    def test_fallback_to_first_links_on_llm_error(self):
        from scraper import _score_links

        links = [
            {"url": "https://example.com/link1", "text": "Link 1"},
            {"url": "https://example.com/link2", "text": "Link 2"},
        ]

        with patch("scraper.OpenAI", side_effect=Exception("LLM error")):
            result = _score_links(links, "AAPL", "http://localhost:8080/v1", "model")

        assert len(result) == 2
        assert result[0] == "https://example.com/link1"

    def test_empty_links_returns_empty(self):
        from scraper import _score_links
        result = _score_links([], "AAPL", "http://localhost:8080/v1", "model")
        assert result == []
