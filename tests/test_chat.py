"""Tests for the chat module."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chat import _build_system_prompt, _web_search


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


def test_build_system_prompt_followup_mode():
    """Verify system prompt includes articles and summary in follow-up mode."""
    from chat import _build_system_prompt

    articles = [
        {"title": "AAPL Earnings Beat", "source": "Reuters", "date": "2026-07-01", "snippet": "Strong Q2 results."},
    ]
    summary = "Apple shows strong earnings."

    prompt = _build_system_prompt("AAPL", articles, summary)

    assert "AAPL" in prompt
    assert "Apple shows strong earnings" in prompt
    assert "AAPL Earnings Beat" in prompt
    assert "web_search" in prompt


def test_build_system_prompt_standalone_mode():
    """Verify system prompt omits article context in standalone mode."""
    from chat import _build_system_prompt

    prompt = _build_system_prompt("TSLA", None, None)

    assert "TSLA" in prompt
    assert "INITIAL SUMMARY" not in prompt
    assert "ARTICLES" not in prompt
    assert "web_search" in prompt


def test_ask_followup_returns_text_response():
    """Verify ask_followup returns LLM text response and updated history."""
    from chat import ask_followup

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Based on the articles, AAPL shows strong earnings growth."
    mock_response.choices[0].message.tool_calls = None

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("chat.OpenAI", return_value=mock_client) as mock_openai:
        result = ask_followup(
            question="How are AAPL earnings?",
            ticker="AAPL",
            history=[],
            llm_url="http://localhost:8080/v1",
            model="qwen",
            articles=[{"title": "Earnings Beat", "source": "Reuters", "date": "2026-07-01", "snippet": "Strong results."}],
            summary="AAPL shows strong earnings.",
        )

    assert "earnings growth" in result["answer"]
    assert len(result["history"]) == 2  # user + assistant
    assert result["history"][0]["role"] == "user"
    assert result["history"][1]["role"] == "assistant"

    # Verify LLM was called with tools parameter
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert "tools" in call_kwargs
    assert len(call_kwargs["tools"]) == 1
    assert call_kwargs["tools"][0]["function"]["name"] == "web_search"


def test_ask_followup_executes_tool_calls():
    """Verify ask_followup executes web_search tool calls and loops back."""
    from chat import ask_followup

    # First call: LLM requests web search
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_123"
    mock_tool_call.type = "function"
    mock_tool_call.function.name = "web_search"
    mock_tool_call.function.arguments = '{"query": "AAPL latest news"}'

    mock_response_tool = MagicMock()
    mock_response_tool.choices[0].message.content = None
    mock_response_tool.choices[0].message.tool_calls = [mock_tool_call]

    # Second call: LLM returns text answer after seeing search results
    mock_response_text = MagicMock()
    mock_response_text.choices[0].message.content = "Based on recent news, AAPL announced new products."
    mock_response_text.choices[0].message.tool_calls = None

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [mock_response_tool, mock_response_text]

    with patch("chat.OpenAI", return_value=mock_client):
        with patch("chat._web_search", return_value="[1] AAPL New Product Launch\n    URL: https://example.com\n    Apple announces new lineup."):
            result = ask_followup(
                question="What's new with AAPL?",
                ticker="AAPL",
                history=[],
                llm_url="http://localhost:8080/v1",
                model="qwen",
            )

    # Verify LLM was called twice (tool call + final answer)
    assert mock_client.chat.completions.create.call_count == 2
    assert "new products" in result["answer"]
