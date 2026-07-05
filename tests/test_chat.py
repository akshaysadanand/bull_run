"""Tests for the chat module."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chat import _web_search


def test_web_search_returns_formatted_results():
    """Verify web_search formats SearXNG results into readable text."""
    mock_json = {
        "results": [
            {
                "title": "AAPL Earnings Beat",
                "url": "https://example.com/aapl-earnings",
                "content": "Apple reported strong Q2 results beating expectations.",
            },
            {
                "title": "AAPL Stock Analysis",
                "url": "https://example.com/aapl-analysis",
                "content": "Analysts raise price target on strong iPhone sales.",
            },
        ]
    }

    with patch("chat.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_json).encode()
        mock_response.getheader.return_value = "application/json"
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = _web_search("AAPL earnings")

    assert "AAPL Earnings Beat" in result
    assert "AAPL Stock Analysis" in result
    assert "example.com/aapl-earnings" in result


def test_web_search_handles_error():
    """Verify web_search returns error message when urlopen raises an exception."""
    with patch("chat.urlopen", side_effect=Exception("Connection refused")):
        result = _web_search("AAPL")

    assert result.startswith("Search failed:")
    assert "Connection refused" in result


def test_web_search_handles_empty_results():
    """Verify web_search returns 'No results found.' when results list is empty."""
    mock_json = {"results": []}

    with patch("chat.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_json).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = _web_search("AAPL")

    assert result == "No results found."


def test_web_search_truncates_long_content():
    """Verify web_search truncates content over 300 chars and appends ellipsis."""
    long_content = "x" * 350
    mock_json = {
        "results": [
            {
                "title": "Long Article",
                "url": "https://example.com/long",
                "content": long_content,
            }
        ]
    }

    with patch("chat.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_json).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = _web_search("AAPL")

    assert "xxx..." in result
    assert "x" * 350 not in result
