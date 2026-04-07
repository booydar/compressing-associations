"""
Unified LLM client.

Supported providers (set in config.yaml):
  anthropic  — Anthropic Claude via the anthropic SDK
  openai     — OpenAI via the openai SDK
  local      — Any OpenAI-compatible local server (LMStudio, llama.cpp, etc.)
               Requires host + port in the provider config block. No API key needed.
  cursor     — cursor-openai-bridge (exposes Cursor IDE models as OpenAI-compatible API)
               Requires host + port (default 127.0.0.1:8765). No API key needed.
               Start the bridge first: node <cursor_bridge.bin>
"""
import os
from typing import Any


def call_llm(provider_cfg: dict, messages: list[dict], max_tokens: int = 4096) -> str:
    """
    Send a chat completion request and return the assistant reply as a string.

    provider_cfg keys:
      provider        : "anthropic" | "openai" | "local" | "cursor"
      model           : model name/id string
      api_key_env     : (anthropic/openai only) name of the env var holding the API key
      host            : (local/cursor only) hostname, default "localhost"
      port            : (local/cursor only) port number
    """
    provider = provider_cfg["provider"]
    model = provider_cfg["model"]

    if provider == "anthropic":
        api_key = os.environ.get(provider_cfg["api_key_env"], "")
        return _call_anthropic(model, api_key, messages, max_tokens)

    elif provider == "openai":
        api_key = os.environ.get(provider_cfg["api_key_env"], "")
        return _call_openai_compat(model, api_key, messages, max_tokens, base_url=None)

    elif provider == "local":
        base_url = _build_base_url(provider_cfg)
        # Local servers accept any non-empty string as the key
        api_key = os.environ.get(provider_cfg.get("api_key_env", ""), "no-key") or "no-key"
        return _call_openai_compat(model, api_key, messages, max_tokens, base_url=base_url)

    elif provider == "cursor":
        base_url = _build_base_url(provider_cfg)
        # cursor-openai-bridge requires no key by default (unless CURSOR_BRIDGE_API_KEY is set)
        api_key = os.environ.get(provider_cfg.get("api_key_env", ""), "no-key") or "no-key"
        return _call_openai_compat(model, api_key, messages, max_tokens, base_url=base_url)

    else:
        raise ValueError(
            f"Unknown LLM provider: {provider!r}. "
            "Use 'anthropic', 'openai', 'local', or 'cursor'."
        )


def _call_anthropic(model: str, api_key: str, messages: list[dict], max_tokens: int) -> str:
    try:
        import anthropic
    except ImportError:
        raise ImportError("pip install anthropic")

    system_msg = None
    chat_messages = []
    for m in messages:
        if m["role"] == "system":
            system_msg = m["content"]
        else:
            chat_messages.append(m)

    client = anthropic.Anthropic(api_key=api_key)
    kwargs: dict[str, Any] = dict(model=model, max_tokens=max_tokens, messages=chat_messages)
    if system_msg:
        kwargs["system"] = system_msg

    response = client.messages.create(**kwargs)
    return response.content[0].text


def _call_openai_compat(
    model: str,
    api_key: str,
    messages: list[dict],
    max_tokens: int,
    base_url: str | None,
) -> str:
    try:
        import openai
    except ImportError:
        raise ImportError("pip install openai")

    kwargs: dict[str, Any] = dict(api_key=api_key)
    if base_url:
        kwargs["base_url"] = base_url

    client = openai.OpenAI(**kwargs)
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content


def _build_base_url(provider_cfg: dict) -> str:
    host = provider_cfg.get("host", "localhost")
    port = provider_cfg.get("port")
    if port is None:
        raise ValueError(
            f"Provider '{provider_cfg.get('provider')}' requires 'port' in config."
        )
    return f"http://{host}:{port}/v1"
