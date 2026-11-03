"""Off-Pi tests for the Piper worker (backend/voice_worker.py): what it answers
for each line, and that a failed line leaves no WAV behind. Piper is a fake
voice, injected as the `piper` module, so no model is loaded.

    python3 -m unittest tests.test_voice_worker
"""

import io
import json
import os
import sys
import tempfile
import types
import unittest
import wave
from unittest import mock

from backend import voice_worker


class FakeVoice:
    """Good text gives a short mono WAV, "boom" raises before any audio,
    and "silence" writes nothing at all."""

    def synthesize_wav(self, text, w):
        if text == "boom":
            raise RuntimeError("model exploded")
        if text == "silence":
            return
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x00\x00" * 100)


class VoiceWorkerTest(unittest.TestCase):
    def setUp(self):
        fake = types.ModuleType("piper")
        fake.PiperVoice = mock.Mock()
        fake.PiperVoice.load.return_value = FakeVoice()
        self._saved_piper = sys.modules.get("piper")
        sys.modules["piper"] = fake
        self.addCleanup(self._restore_piper)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _restore_piper(self):
        if self._saved_piper is None:
            sys.modules.pop("piper", None)
        else:
            sys.modules["piper"] = self._saved_piper

    def run_worker(self, lines):
        """Feed `lines` (strings, newline included) to main(); the replies, parsed."""
        stdin = io.StringIO("".join(lines))
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", ["voice_worker.py", "model.onnx"]), \
                mock.patch.object(sys, "stdin", stdin), \
                mock.patch.object(sys, "stdout", stdout):
            voice_worker.main()
        return [json.loads(line) for line in stdout.getvalue().splitlines()]

    def job(self, name, text):
        return json.dumps({"text": text, "out": self.path(name)}) + "\n"

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def test_ready_then_good_job_writes_a_wav(self):
        replies = self.run_worker([self.job("good.wav", "Turn right.")])
        self.assertEqual(replies[0], {"ready": True})
        self.assertEqual(replies[1], {"out": self.path("good.wav")})
        with wave.open(self.path("good.wav"), "rb") as r:
            self.assertGreater(r.getnframes(), 0)

    def test_piper_error_is_reported_and_no_file_is_left(self):
        replies = self.run_worker([self.job("boom.wav", "boom")])
        error = replies[1]["error"]
        self.assertIn("model exploded", error)
        self.assertNotIn("channels", error)
        self.assertFalse(os.path.exists(self.path("boom.wav")))

    def test_no_audio_is_reported_and_no_file_is_left(self):
        replies = self.run_worker([self.job("silence.wav", "silence")])
        self.assertIn("error", replies[1])
        self.assertFalse(os.path.exists(self.path("silence.wav")))

    def test_bad_lines_get_an_error_and_the_next_job_still_works(self):
        replies = self.run_worker([
            "not json\n",
            json.dumps([1, 2]) + "\n",
            json.dumps({"text": "no out here"}) + "\n",
            self.job("after.wav", "Turn left."),
        ])
        self.assertEqual(len(replies), 5)
        for reply in replies[1:4]:
            self.assertIn("error", reply)
        self.assertEqual(replies[4], {"out": self.path("after.wav")})

    def test_one_reply_per_input_line(self):
        lines = [
            self.job("a.wav", "Turn right."),
            self.job("b.wav", "boom"),
            self.job("c.wav", "silence"),
            "\n",
            "not json\n",
            self.job("d.wav", "Stay left."),
        ]
        replies = self.run_worker(lines)
        # The ready line, then exactly one reply for each input line.
        self.assertEqual(len(replies), len(lines) + 1)
        self.assertEqual(replies[0], {"ready": True})
        self.assertEqual(replies[1], {"out": self.path("a.wav")})
        self.assertIn("error", replies[2])
        self.assertIn("error", replies[3])
        self.assertIn("error", replies[4])
        self.assertIn("error", replies[5])
        self.assertEqual(replies[6], {"out": self.path("d.wav")})


if __name__ == "__main__":
    unittest.main()
