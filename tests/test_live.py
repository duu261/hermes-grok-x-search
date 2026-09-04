import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_provider():
    spec = importlib.util.spec_from_file_location(
        "grok_x_search_live_provider", ROOT / "provider.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(os.getenv("GROK_X_SEARCH_LIVE_TESTS") == "1", "live tests disabled")
class GrokXSearchLiveTests(unittest.TestCase):
    def test_citation_backed_x_search(self):
        provider = load_provider()
        base_url = os.getenv("GROK_X_SEARCH_LIVE_BASE_URL", "").strip()
        self.assertTrue(base_url, "GROK_X_SEARCH_LIVE_BASE_URL is required")
        config = {
            "base_url": base_url,
            "model": os.getenv("GROK_X_SEARCH_LIVE_MODEL", "grok-4.6"),
            "timeout_seconds": 180,
            "retries": 1,
        }

        with patch.object(provider, "_load_config", return_value=config):
            result = provider.grok_x_search(
                "Find one recent public post from @xai about Grok. "
                "Return its exact x.com status URL.",
                allowed_x_handles=["xai"],
            )

        self.assertTrue(result.get("success"), result.get("error_type"))
        self.assertFalse(result.get("degraded"), "gateway returned no citations")
        urls = result.get("citation_urls") or []
        self.assertTrue(any("x.com/" in url for url in urls), "no X citation URL returned")


if __name__ == "__main__":
    unittest.main()
