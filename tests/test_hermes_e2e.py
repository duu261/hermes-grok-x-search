import importlib.util
import unittest

HERMES_AVAILABLE = importlib.util.find_spec("hermes_cli") is not None

try:
    from .hermes_e2e_runner import main
except ImportError:
    from hermes_e2e_runner import main


class HermesRuntimeE2ETest(unittest.TestCase):
    @unittest.skipUnless(
        HERMES_AVAILABLE,
        "Hermes runtime is not installed; run this probe in an Hermes environment",
    )
    def test_real_hermes_tool_executor_returns_native_shape(self):
        main()
        main()


if __name__ == "__main__":
    unittest.main()
