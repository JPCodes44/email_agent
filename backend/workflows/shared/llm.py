"""Shared LLM client using OpenAI-compatible API (Ollama by default) + Anthropic + Perplexity."""

from openai import OpenAI
import anthropic
from shared import config

CLAUDE_MODEL = "claude-sonnet-4-6"
PERPLEXITY_MODEL = "sonar-pro"


def create_client() -> OpenAI:
    """Return an OpenAI client pointing at the configured LLM provider."""
    return OpenAI(
        base_url=config.LLM_BASE_URL,
        api_key=config.LLM_API_KEY,
    )


def create_claude_client() -> anthropic.Anthropic:
    """Return an Anthropic client for Claude API calls."""
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def chat(client: OpenAI, prompt: str, max_tokens: int = 2048) -> str:
    """Send a single-turn chat and return the assistant's text."""
    resp = client.chat.completions.create(
        model=config.LLM_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content


def chat_claude(client: anthropic.Anthropic, prompt: str, max_tokens: int = 2048) -> str:
    """Send a single-turn chat to Claude and return the assistant's text."""
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


def create_perplexity_client() -> OpenAI:
    """Return an OpenAI client for Perplexity API (uses OpenAI-compatible interface)."""
    return OpenAI(
        base_url="https://api.perplexity.ai",
        api_key=config.PERPLEXITY_API_KEY,
    )


def chat_perplexity(client: OpenAI, prompt: str, max_tokens: int = 4096) -> str:
    """Send a single-turn chat to Perplexity and return the assistant's text."""
    resp = client.chat.completions.create(
        model=PERPLEXITY_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content
