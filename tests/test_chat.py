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


# --- Tests for strip_thinking_tags ---

from chat import strip_thinking_tags


def test_strip_thinking_tags_extracts_think():
    """Verify strip_thinking_tags extracts and strips <think> blocks."""
    text = "<think>Let me reason about this.</think>Here is the answer."
    cleaned, thinking = strip_thinking_tags(text)
    assert cleaned == "Here is the answer."
    assert "Let me reason" in thinking


def test_strip_thinking_tags_extracts_thinking():
    """Verify strip_thinking_tags extracts and strips <thinking> blocks."""
    text = "<thinking>Step by step analysis.</thinking>\n\nThe result is 42."
    cleaned, thinking = strip_thinking_tags(text)
    assert "The result is 42" in cleaned
    assert "Step by step" in thinking
    assert "<thinking>" not in cleaned


def test_strip_thinking_tags_handles_trailing_think():
    """Verify strip_thinking_tags handles unclosed trailing <think> blocks."""
    text = "Partial answer. <think>Still thinking about this"
    cleaned, thinking = strip_thinking_tags(text)
    assert "Partial answer" in cleaned
    assert "<think>" not in cleaned
    assert "Still thinking" in thinking


def test_strip_thinking_tags_no_tags():
    """Verify strip_thinking_tags returns text unchanged when no tags present."""
    text = "Just a plain answer with no thinking."
    cleaned, thinking = strip_thinking_tags(text)
    assert cleaned == text
    assert thinking == ""


# --- Tests for _strip_tool_call_xml ---

from chat import _strip_tool_call_xml


def test_strip_tool_call_xml_strips_sentinels():
    """Verify _strip_tool_call_xml strips Unicode sentinel tool call markers."""
    text = "Some text \u2458{\"name\": \"web_search\"}\u2459 more text"
    result = _strip_tool_call_xml(text)
    assert "Some text" in result
    assert "more text" in result
    assert "\u2458" not in result
    assert "web_search" not in result


def test_strip_tool_call_xml_strips_trailing():
    """Verify _strip_tool_call_xml strips unclosed trailing sentinel."""
    text = "Answer text \u2458{\"name\": \"web_search\""
    result = _strip_tool_call_xml(text)
    assert "Answer text" in result
    assert "\u2458" not in result


def test_strip_tool_call_xml_no_sentinels():
    """Verify _strip_tool_call_xml returns text unchanged when no sentinels."""
    text = "Just a normal answer."
    result = _strip_tool_call_xml(text)
    assert result == text


# --- Tests for _run_tool_loop ---

def test_run_tool_loop_returns_text_answer():
    """Verify _run_tool_loop returns answer when LLM gives text response."""
    from chat import _run_tool_loop

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "AAPL looks strong."
    mock_response.choices[0].message.tool_calls = None

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("chat.OpenAI", return_value=mock_client):
        result = _run_tool_loop(
            question="How is AAPL?",
            ticker="AAPL",
            history=[],
            llm_url="http://localhost:8080/v1",
            model="qwen",
        )

    assert result["needs_final_call"] is False
    assert "AAPL looks strong" in result["answer"]
    assert result["tool_calls"] == []


def test_run_tool_loop_needs_final_call_after_max_iterations():
    """Verify _run_tool_loop sets needs_final_call when loop exhausts."""
    from chat import _run_tool_loop, MAX_SEARCH_ITERATIONS

    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_999"
    mock_tool_call.type = "function"
    mock_tool_call.function.name = "web_scrape"
    mock_tool_call.function.arguments = '{"url": "https://example.com"}'

    mock_response = MagicMock()
    mock_response.choices[0].message.content = None
    mock_response.choices[0].message.tool_calls = [mock_tool_call]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("chat.OpenAI", return_value=mock_client):
        with patch("chat._web_scrape", return_value="Scraped content"):
            result = _run_tool_loop(
                question="Read this article",
                ticker="AAPL",
                history=[],
                llm_url="http://localhost:8080/v1",
                model="qwen",
            )

    assert result["needs_final_call"] is True
    assert result["answer"] is None
    assert mock_client.chat.completions.create.call_count == MAX_SEARCH_ITERATIONS


# --- Tests for stream_final_answer ---

def test_stream_final_answer_yields_chunks():
    """Verify stream_final_answer yields text chunks from streaming response."""
    from chat import stream_final_answer

    # Mock a streaming response
    chunk1 = MagicMock()
    chunk1.choices[0].delta.content = "Hello "
    chunk2 = MagicMock()
    chunk2.choices[0].delta.content = "world!"
    chunk3 = MagicMock()
    chunk3.choices[0].delta.content = None  # Empty delta at end

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = iter([chunk1, chunk2, chunk3])

    with patch("chat.OpenAI", return_value=mock_client):
        chunks = list(stream_final_answer(
            messages=[{"role": "user", "content": "test"}],
            llm_url="http://localhost:8080/v1",
            model="qwen",
        ))

    assert chunks == ["Hello ", "world!"]


# --- Tests for scrape content truncation ---

def test_web_scrape_truncates_long_content():
    """Verify _web_scrape truncates content exceeding MAX_SCRAPE_CONTENT_LENGTH."""
    from chat import _web_scrape, MAX_SCRAPE_CONTENT_LENGTH

    long_content = "A" * (MAX_SCRAPE_CONTENT_LENGTH + 1000)

    with patch("chat._MCPClient.get") as mock_mcp_get:
        mock_client = MagicMock()
        mock_client.call_tool.return_value = long_content
        mock_mcp_get.return_value = mock_client

        result = _web_scrape("https://example.com/long-article")

    assert len(result) < len(long_content)
    assert "[Content truncated" in result
