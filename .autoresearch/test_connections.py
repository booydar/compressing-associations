"""
Test all LLM provider connections configured in config.yaml.

Usage (from repo root):
    python .autoresearch/test_connections.py

Sends a minimal 1-token completion to each configured provider and also
probes both local servers (LMStudio :1234 and llama.cpp :8117) regardless
of whether they are active in config.yaml.

Output:
    [OK]   provider/model — X.Xs
    [FAIL] provider/model — <reason>
"""
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# Allow importing llm_client from this directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402 — installed via requirements


REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = Path(__file__).resolve().parent / "config.yaml"
ENV_FILE = REPO_ROOT / ".autoresearch" / ".env"

PROBE_MESSAGES = [
    {"role": "user", "content": "Reply with exactly the single word: pong"},
]


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


def _load_config() -> dict:
    with open(CONFIG_FILE) as f:
        cfg = yaml.safe_load(f)
    _load_dotenv(ENV_FILE)
    return cfg


def _http_alive(host: str, port: int, path: str = "/health", timeout: int = 3) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}{path}", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _test_provider(label: str, provider_cfg: dict, max_tokens: int = 8) -> tuple[bool, str]:
    from llm_client import call_llm
    t0 = time.time()
    try:
        reply = call_llm(provider_cfg, PROBE_MESSAGES, max_tokens=max_tokens)
        elapsed = time.time() - t0
        return True, f"{elapsed:.1f}s  reply: {reply.strip()[:60]!r}"
    except Exception as e:
        elapsed = time.time() - t0
        return False, f"{elapsed:.1f}s  {type(e).__name__}: {e}"


def _fmt(ok: bool, label: str, detail: str) -> str:
    tag = "[OK]  " if ok else "[FAIL]"
    return f"  {tag} {label:<50} {detail}"


def main() -> None:
    cfg = _load_config()
    llm_cfg = cfg.get("llm", {})
    bridge_cfg = cfg.get("cursor_bridge", {})

    results: list[str] = []
    any_fail = False

    # ── Configured providers (planner + executor, deduplicated by identity) ───
    seen: set[str] = set()
    for role in ("planner", "executor"):
        p = llm_cfg.get(role)
        if not p or not isinstance(p, dict):
            continue
        key = f"{p['provider']}/{p['model']}/{p.get('host','')}/{p.get('port','')}"
        if key in seen:
            continue
        seen.add(key)

        provider = p["provider"]
        model = p["model"]
        label = f"{role:<8} {provider}/{model}"

        if provider in ("local", "cursor"):
            host = p.get("host", "127.0.0.1")
            port = p.get("port")
            alive = _http_alive(host, int(port)) if port else False
            if not alive:
                results.append(_fmt(False, label, f"server not reachable at {host}:{port}"))
                any_fail = True
                continue

        ok, detail = _test_provider(label, p)
        results.append(_fmt(ok, label, detail))
        if not ok:
            any_fail = True

    # ── Always probe both local servers, regardless of config ─────────────────
    local_servers = [
        ("LMStudio",    "127.0.0.1", 1234, "qwen3.5-9b"),
        ("llama.cpp",   "127.0.0.1", 8117, "unsloth/Qwen3.5-27B-Q6K"),
    ]
    for name, host, port, model in local_servers:
        label = f"local    {name} ({host}:{port})"
        if not _http_alive(host, port):
            results.append(_fmt(False, label, "server not reachable (not running?)"))
            # not a hard failure — server may simply not be started
            continue
        p = {"provider": "local", "model": model, "host": host, "port": port}
        ok, detail = _test_provider(label, p)
        results.append(_fmt(ok, label, detail))
        if not ok:
            any_fail = True

    # ── cursor-openai-bridge probe ─────────────────────────────────────────────
    bridge_host = bridge_cfg.get("host", "127.0.0.1")
    bridge_port = bridge_cfg.get("port", 8765)
    bridge_label = f"cursor   cursor-openai-bridge ({bridge_host}:{bridge_port})"
    if _http_alive(bridge_host, bridge_port):
        # Attempt a completion with whatever model the bridge defaults to
        p = {
            "provider": "cursor",
            "model": "claude-sonnet-4-5",
            "host": bridge_host,
            "port": bridge_port,
        }
        ok, detail = _test_provider(bridge_label, p)
        results.append(_fmt(ok, bridge_label, detail))
        if not ok:
            any_fail = True
    else:
        results.append(
            _fmt(False, bridge_label,
                 "not running — start with: node "
                 f"{bridge_cfg.get('bin', '<cursor_bridge.bin>')}")
        )

    # ── Print summary ──────────────────────────────────────────────────────────
    print("\nLLM connection test")
    print("=" * 80)
    for line in results:
        print(line)
    print("=" * 80)

    if any_fail:
        print("\nSome providers failed. Check config.yaml and .env.\n")
        sys.exit(1)
    else:
        print("\nAll configured providers OK.\n")


if __name__ == "__main__":
    main()
