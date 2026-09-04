"""Real Hermes runtime probe used by test_hermes_e2e."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
ENV_KEYS = ("HERMES_HOME", "HERMES_BUNDLED_PLUGINS", "GROK_X_SEARCH_API_KEY")
EXPECTED_KEYS = {
    "success",
    "provider",
    "credential_source",
    "tool",
    "model",
    "query",
    "answer",
    "citations",
    "inline_citations",
    "degraded",
    "degraded_reason",
}


def _run_probe(home: Path, bundled: Path) -> None:
    (home / "plugins" / "grok-x-search").mkdir(parents=True)
    shutil.copytree(REPO, home / "plugins" / "grok-x-search", dirs_exist_ok=True)
    (home / "logs").mkdir()
    (home / "config.yaml").write_text(
        "plugins:\n  enabled:\n    - grok-x-search\n"
        "grok_x_search:\n"
        "  base_url: https://gateway.example/v1\n"
        "  model: grok-4.5\n",
        encoding="utf-8",
    )

    from hermes_cli.plugins import PluginManager
    from run_agent import AIAgent
    from tools.registry import registry

    manager = PluginManager()
    manager.discover_and_load()
    loaded = manager._plugins["grok-x-search"]
    assert loaded.enabled and loaded.error is None

    class Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, limit=None):
            payload = {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Found one post.",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url": "https://x.com/OpenAI/status/1",
                                        "title": "OpenAI",
                                        "start_index": 0,
                                        "end_index": 5,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
            raw = json.dumps(payload).encode("utf-8")
            return raw if limit is None else raw[:limit]

    agent = AIAgent(
        base_url="https://model.example/v1",
        api_key="k",
        provider="openai",
        model="gpt-5.4-mini",
        quiet_mode=True,
        skip_memory=True,
        skip_background_review=True,
        skip_context_files=True,
        platform="cli",
    )
    entry = registry.get_entry("grok_x_search")
    assert entry is not None
    search_function = entry.handler.__globals__["grok_x_search"]
    provider_globals = search_function.__globals__
    original_open_request = provider_globals["_open_request"]
    provider_globals["_open_request"] = lambda *_args, **_kwargs: Response()
    try:
        function = SimpleNamespace(
            name="grok_x_search",
            arguments=json.dumps(
                {
                    "query": "Find official OpenAI posts",
                    "allowed_x_handles": ["OpenAI"],
                }
            ),
        )
        tool_call = SimpleNamespace(id="call-1", function=function)
        messages: list[dict] = []
        agent._execute_tool_calls_sequential(
            SimpleNamespace(tool_calls=[tool_call]), messages, "e2e"
        )
        result = json.loads(messages[-1]["content"])

        assert set(result) == EXPECTED_KEYS, result
        assert result["success"] is True
        assert result["degraded"] is False
        assert result["inline_citations"][0]["url"] == "https://x.com/OpenAI/status/1"
    finally:
        provider_globals["_open_request"] = original_open_request
        manager.unload("grok-x-search")
        registry.deregister("grok_x_search", scope=str(home))
        assert registry.snapshot_registration("grok_x_search", scope=str(home)) is None


def main() -> None:
    previous_env = {key: os.environ.get(key) for key in ENV_KEYS}
    root_logger = logging.getLogger()
    previous_handlers = tuple(root_logger.handlers)
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "hermes"
            bundled = root / "bundled"
            bundled.mkdir()
            os.environ.update(
                {
                    "HERMES_HOME": str(home),
                    "HERMES_BUNDLED_PLUGINS": str(bundled),
                    "GROK_X_SEARCH_API_KEY": "k",
                }
            )
            _run_probe(home, bundled)
    finally:
        for handler in tuple(root_logger.handlers):
            if handler not in previous_handlers:
                root_logger.removeHandler(handler)
                handler.close()
        for handler in tuple(root_logger.handlers):
            root_logger.removeHandler(handler)
        for handler in previous_handlers:
            root_logger.addHandler(handler)
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    main()
