import unittest

try:
    from .hermes_e2e_runner import main
except ImportError:
    from hermes_e2e_runner import main


class HermesRuntimeE2ETest(unittest.TestCase):
    def test_real_hermes_tool_executor_returns_native_shape(self):
        main()
        main()


if __name__ == "__main__":
    unittest.main()
