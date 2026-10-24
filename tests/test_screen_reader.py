from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "freeq_port"))

from screen_reader import ScreenReader  # noqa: E402


class ScreenReaderTests(unittest.TestCase):
    def test_prism_best_backend_speaks(self) -> None:
        calls = []

        class FakeBackend:
            features = SimpleNamespace(supports_speak=True)

            def speak(self, text, interrupt=False):
                calls.append((text, interrupt))

        backend = FakeBackend()

        class FakeContext:
            def create_best(self):
                return backend

        fake_prism = SimpleNamespace(Context=FakeContext)
        with patch.dict(sys.modules, {"prism": fake_prism}):
            reader = ScreenReader()

        self.assertIs(reader.output, backend)
        self.assertTrue(reader.speak("Credits", interrupt=True))
        self.assertEqual(calls, [("Credits", True)])

    def test_prism_failure_keeps_speech_optional(self) -> None:
        class FailingContext:
            def __init__(self):
                raise RuntimeError("No speech backend")

        fake_prism = SimpleNamespace(Context=FailingContext)
        with patch.dict(sys.modules, {"prism": fake_prism}):
            reader = ScreenReader()

        self.assertFalse(reader.speak("Credits"))


if __name__ == "__main__":
    unittest.main()
