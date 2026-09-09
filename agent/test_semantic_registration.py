import os
import subprocess
import sys
import unittest
from pathlib import Path


class SemanticRegistrationTests(unittest.TestCase):
    def _registered_runners(self, *, streaming):
        env = os.environ.copy()
        env.pop("LIVEKIT_REMOTE_EOT_URL", None)
        if streaming:
            env["STREAMING_STT_URL"] = "ws://127.0.0.1:8913/asr?mode=full"
        else:
            env.pop("STREAMING_STT_URL", None)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from livekit.agents.inference_runner import _InferenceRunner; "
                "import main; print(','.join(sorted(_InferenceRunner.registered_runners)))",
            ],
            cwd=Path(__file__).parent,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip().split(",") if result.stdout.strip() else []

    def test_streaming_import_registers_local_multilingual_runner(self):
        self.assertIn(
            "lk_end_of_utterance_multilingual",
            self._registered_runners(streaming=True),
        )

    def test_batch_import_does_not_register_turn_detector_runner(self):
        self.assertNotIn(
            "lk_end_of_utterance_multilingual",
            self._registered_runners(streaming=False),
        )


if __name__ == "__main__":
    unittest.main()
