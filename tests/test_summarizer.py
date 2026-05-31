"""Tests for the summarizer module."""

from unittest.mock import MagicMock, patch

from summarizer import summarize_news


def test_summarize_news_returns_llm_response():
    """Verify summarize_news sends correct prompt and returns LLM output."""
    articles = [
        {"title": "AAPL Beats Earnings", "source": "Reuters", "date": "2026-05-29", "snippet": "Apple reported strong Q2 results."},
        {"title": "Supply Chain Concerns", "source": "Bloomberg", "date": "2026-05-28", "snippet": "Component shortages may impact production."},
    ]

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "## Summary\n\nApple shows strong earnings but faces supply chain headwinds."

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("summarizer.OpenAI", return_value=mock_client) as mock_openai:
        result = summarize_news(articles, "http://localhost:8080/v1", "llama3")

    # Verify client was configured with correct base URL
    mock_openai.assert_called_once_with(base_url="http://localhost:8080/v1", api_key="not-needed")

    # Verify the API call included both articles
    call_args = mock_client.chat.completions.create.call_args
    assert call_args.kwargs["model"] == "llama3"
    assert len(call_args.kwargs["messages"]) == 2
    assert "AAPL Beats Earnings" in call_args.kwargs["messages"][1]["content"]
    assert "Supply Chain Concerns" in call_args.kwargs["messages"][1]["content"]

    assert "Summary" in result["summary"]


def test_summarize_news_handles_empty_articles():
    """Verify summarize_news handles empty article list gracefully."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "No articles to summarize."

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("summarizer.OpenAI", return_value=mock_client):
        result = summarize_news([], "http://localhost:8080/v1", "llama3")

    assert isinstance(result, dict)
    assert "summary" in result
    assert "thinking" in result


def test_summarize_news_handles_empty_llm_response():
    """Verify summarize_news returns empty dict values when LLM returns None content."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = None

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("summarizer.OpenAI", return_value=mock_client):
        result = summarize_news([{"title": "Test", "source": "", "date": "", "snippet": ""}], "http://localhost:8080/v1", "llama3")

    assert result == {"summary": "", "thinking": ""}
