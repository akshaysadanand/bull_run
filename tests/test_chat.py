"""Tests for the chat module."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_web_search_returns_formatted_results():
    """Verify web_search formats SearXNG results into readable text."""
    from chat import _web_search

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
        mock_response.read.return_value = str(mock_json).encode()
        mock_response.getheader.return_value = "application/json"
        mock_urlopen.return_value.__enter__.return_value = mock_response

        # We need to mock json.loads since urlopen returns bytes
        with patch("chat.json.loads", return_value=mock_json):
            result = _web_search("AAPL earnings")

    assert "AAPL Earnings Beat" in result
    assert "AAPL Stock Analysis" in result
    assert "example.com/aapl-earnings" in result
