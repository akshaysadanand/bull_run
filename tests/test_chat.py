"""Tests for the chat module."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chat import _build_system_prompt, _web_search, _web_scrape


def test_web_search_calls_mcp():
    """Verify web_search delegates to MCP client searxng_search tool."""
    with patch("chat._MCPClient.get") as mock_mcp_get:
        mock_client = MagicMock()
        mock_client.call_tool.return_value = "Search Results for \"AAPL\"\n1. AAPL Earnings Beat"
        mock_mcp_get.return_value = mock_client

        result = _web_search("AAPL earnings")

    mock_client.call_tool.assert_called_once_with("searxng_search", {"query": "AAPL earnings"})
    assert "AAPL Earnings Beat" in result


def test_web_search_handles_mcp_error():
    """Verify web_search returns error message when MCP call fails."""
    with patch("chat._MCPClient.get") as mock_mcp_get:
        mock_client = MagicMock()
        mock_client.call_tool.return_value = "MCP call failed: Connection refused"
        mock_mcp_get.return_value = mock_client

        result = _web_search("AAPL")

    assert "MCP call failed" in result


def test_web_scrape_calls_mcp():
    """Verify web_scrape delegates to MCP client web_scrape tool."""
    with patch("chat._MCPClient.get") as mock_mcp_get:
        mock_client = MagicMock()
        mock_client.call_tool.return_value = "Title: Test Article\n\nThis is the article content."
        mock_mcp_get.return_value = mock_client

        result = _web_scrape("https://example.com/article")

    mock_client.call_tool.assert_called_once_with("web_scrape", {"url": "https://example.com/article"})
    assert "Test Article" in result


def test_web_scrape_handles_mcp_error():
    """Verify web_scrape returns error message when MCP call fails."""
    with patch("chat._MCPClient.get") as mock_mcp_get:
        mock_client = MagicMock()
        mock_client.call_tool.return_value = "MCP call failed: Timeout"
        mock_mcp_get.return_value = mock_client

        result = _web_scrape("https://example.com/slow")

    assert "MCP call failed" in result


def test_build_system_prompt_followup_mode():
    """Verify system prompt includes articles and summary in follow-up mode."""
    articles = [
        {"title": "AAPL Earnings Beat", "source": "Reuters", "date": "2026-07-01", "snippet": "Strong Q2 results."},
    ]
    summary = "Apple shows strong earnings."

    prompt = _build_system_prompt("AAPL", articles, summary)

    assert "AAPL" in prompt
    assert "Apple shows strong earnings" in prompt
    assert "AAPL Earnings Beat" in prompt
    assert "searxng_search" in prompt
    assert "web_scrape" in prompt


def test_build_system_prompt_standalone_mode():
    """Verify system prompt omits article context in standalone mode."""
    prompt = _build_system_prompt("TSLA", None, None)

    assert "TSLA" in prompt
    assert "INITIAL SUMMARY" not in prompt
    assert "ARTICLES" not in prompt
    assert "searxng_search" in prompt
    assert "web_scrape" in prompt


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
    tool_names = [t["function"]["name"] for t in call_kwargs["tools"]]
    assert "searxng_search" in tool_names
    assert "web_scrape" in tool_names


def test_ask_followup_executes_tool_calls():
    """Verify ask_followup executes searxng_search tool calls and loops back."""
    from chat import ask_followup

    # First call: LLM requests web search via MCP
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_123"
    mock_tool_call.type = "function"
    mock_tool_call.function.name = "searxng_search"
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
        with patch("chat._web_search", return_value="Search Results for \"AAPL latest news\"\n1. AAPL New Product Launch") as mock_search:
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
    mock_search.assert_called_once_with("AAPL latest news")


def test_ask_followup_executes_web_scrape_tool_calls():
    """Verify ask_followup executes web_scrape tool calls and loops back."""
    from chat import ask_followup

    # First call: LLM requests web scrape
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_456"
    mock_tool_call.type = "function"
    mock_tool_call.function.name = "web_scrape"
    mock_tool_call.function.arguments = '{"url": "https://example.com/article"}'

    mock_response_tool = MagicMock()
    mock_response_tool.choices[0].message.content = None
    mock_response_tool.choices[0].message.tool_calls = [mock_tool_call]

    # Second call: LLM returns text answer after seeing scraped content
    mock_response_text = MagicMock()
    mock_response_text.choices[0].message.content = "Based on the article, AAPL has strong fundamentals."
    mock_response_text.choices[0].message.tool_calls = None

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [mock_response_tool, mock_response_text]

    with patch("chat.OpenAI", return_value=mock_client):
        with patch("chat._web_scrape", return_value="Title: AAPL Analysis\n\nStrong fundamentals reported.") as mock_scrape:
            result = ask_followup(
                question="What does the article say?",
                ticker="AAPL",
                history=[],
                llm_url="http://localhost:8080/v1",
                model="qwen",
            )

    # Verify LLM was called twice (tool call + final answer)
    assert mock_client.chat.completions.create.call_count == 2
    assert "strong fundamentals" in result["answer"]
    mock_scrape.assert_called_once_with("https://example.com/article")


def test_ask_followup_rejects_empty_question():
    """Verify ask_followup returns early on empty question."""
    from chat import ask_followup

    result = ask_followup(
        question="",
        ticker="AAPL",
        history=[],
        llm_url="http://localhost:8080/v1",
        model="qwen",
    )

    assert result["answer"] == ""
    assert result["history"] == []


def test_ask_followup_rejects_whitespace_question():
    """Verify ask_followup returns early on whitespace-only question."""
    from chat import ask_followup

    result = ask_followup(
        question="   ",
        ticker="AAPL",
        history=[],
        llm_url="http://localhost:8080/v1",
        model="qwen",
    )

    assert result["answer"] == ""


def test_ask_followup_handles_max_iterations():
    """Verify ask_followup stops after MAX_SEARCH_ITERATIONS tool calls."""
    from chat import ask_followup, MAX_SEARCH_ITERATIONS

    # LLM keeps requesting searches every time
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_123"
    mock_tool_call.type = "function"
    mock_tool_call.function.name = "searxng_search"
    mock_tool_call.function.arguments = '{"query": "test"}'

    mock_response = MagicMock()
    mock_response.choices[0].message.content = None
    mock_response.choices[0].message.tool_calls = [mock_tool_call]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("chat.OpenAI", return_value=mock_client):
        with patch("chat._web_search", return_value="Search results"):
            result = ask_followup(
                question="Test question",
                ticker="AAPL",
                history=[],
                llm_url="http://localhost:8080/v1",
                model="qwen",
            )

    # Should have made MAX_SEARCH_ITERATIONS tool calls + 1 final call without tools
    assert mock_client.chat.completions.create.call_count == MAX_SEARCH_ITERATIONS + 1
    assert result["answer"] != ""
