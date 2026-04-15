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
import time
from typing import Any

_MAX_RETRIES = 3
_RETRY_BACKOFF_SEC = 5


def call_llm(provider_cfg: dict, messages: list[dict], max_tokens: int = 32000) -> str:
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

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            if provider == "anthropic":
                api_key = os.environ.get(provider_cfg["api_key_env"], "")
                return _call_anthropic(model, api_key, messages, max_tokens)

            elif provider == "openai":
                api_key = os.environ.get(provider_cfg["api_key_env"], "")
                return _call_openai_compat(model, api_key, messages, max_tokens, base_url=None)

            elif provider == "local":
                base_url = _build_base_url(provider_cfg)
                api_key = os.environ.get(provider_cfg.get("api_key_env", ""), "no-key") or "no-key"
                return _call_openai_compat(model, api_key, messages, max_tokens, base_url=base_url)

            elif provider == "cursor":
                base_url = _build_base_url(provider_cfg)
                api_key = os.environ.get(provider_cfg.get("api_key_env", ""), "no-key") or "no-key"
                return _call_openai_compat(model, api_key, messages, max_tokens, base_url=base_url)

            else:
                raise ValueError(
                    f"Unknown LLM provider: {provider!r}. "
                    "Use 'anthropic', 'openai', 'local', or 'cursor'."
                )
        except ValueError:
            raise  # don't retry config/programming errors
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                print(f"[llm] attempt {attempt} failed ({exc}), retrying in {_RETRY_BACKOFF_SEC}s...")
                time.sleep(_RETRY_BACKOFF_SEC)
            else:
                print(f"[llm] all {_MAX_RETRIES} attempts failed.")

    raise RuntimeError(f"LLM call failed after {_MAX_RETRIES} retries: {last_exc}") from last_exc


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
    msg = response.choices[0].message
    content = msg.content

    # Qwen3.5 / thinking models: prefer content over reasoning_content
    # reasoning_content is typically the "thinking" part, content is the actual response
    reasoning = getattr(msg, "reasoning_content", None)
    
    # If we have actual content, use it (it may include embedded thinking)
    if content and content.strip():
        return content
    
    # Fall back to reasoning_content if content is empty
    if reasoning and reasoning.strip():
        return reasoning

    if not content:
        raise RuntimeError(
            f"Model returned empty content (finish_reason={response.choices[0].finish_reason!r}). "
            "Check that the model is loaded and max_tokens is sufficient."
        )
    return content


def _build_base_url(provider_cfg: dict) -> str:
    if "base_url" in provider_cfg:
        return provider_cfg["base_url"]
    host = provider_cfg.get("host", "localhost")
    port = provider_cfg.get("port")
    if port is None:
        raise ValueError(
            f"Provider '{provider_cfg.get('provider')}' requires 'port' in config."
        )
    return f"http://{host}:{port}/v1"
