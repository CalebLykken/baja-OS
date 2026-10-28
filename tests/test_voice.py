"""Off-Pi tests for spoken directions (backend/voice.py): a Piper that hangs,
never gets ready or dies must not end the voice. Piper is a tiny stand-in
script, and pw-play, wpctl and pw-dump are faked, so nothing really plays.

    python3 -m unittest tests.test_voice
"""

import contextlib
import io
import os
import queue
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    from backend import voice
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")

# Stands in for voice_worker.py. Each time it's started it takes the next mode
# from $FAKE_PLAN (the last one repeats):
#   ok         answers every line
#   no-ready   never says it's ready
#   bad-ready  says {"ready": false}, then would answer every line
#   hang       ready, then never answers a line
#   die        ready, then exits when it gets a line
#   garbage    ready, then answers a line with a JSON number (not a reply)
#   list       the same, but with ["out"]
#   string     the same, but with "out"
#   wrong-out  answers with {"out": ...} for some other WAV
#   empty      answers with {}: neither "out" nor "error"
#   error-1st  answers its first line {"error": ...}, then every other normally
# "Answering" writes "<pid>:<text>" to the WAV path, so a test can see who spoke.
# The sleeps are only there to be killed; they end by themselves after a minute.
FAKE_WORKER = '''
import json, os, sys, time
d = os.environ["FAKE_DIR"]
with open(os.path.join(d, "starts"), "a") as f:
    f.write(f"{os.getpid()}\\n")
with open(os.path.join(d, "starts")) as f:
    start = len(f.read().split())
plan = os.environ["FAKE_PLAN"].split(",")
mode = plan[min(start, len(plan)) - 1]
if mode == "no-ready":
    time.sleep(60)
print(json.dumps({"ready": mode != "bad-ready"}), flush=True)
lines = 0
for line in sys.stdin:
    job = json.loads(line)
    lines += 1
    if mode == "hang":
        time.sleep(60)
    if mode == "die":
        sys.exit(3)
    if mode in ("garbage", "list", "string", "wrong-out", "empty"):
        print({"garbage": "42", "list": '["out"]', "string": '"out"',
               "wrong-out": '{"out": "/elsewhere.wav"}', "empty": "{}"}[mode], flush=True)
        continue
    if mode == "error-1st" and lines == 1:
        print(json.dumps({"error": "no such voice"}), flush=True)
        continue
    with open(job["out"], "w") as f:
        f.write(f"{os.getpid()}:{job['text']}")
    print(json.dumps({"out": job["out"]}), flush=True)
'''


class FakeSettings:
    def get(self, key, default=None):
        return "true" if key == "voice" else default

    def set(self, key, value):
        pass


class VoiceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "worker.py").write_text(FAKE_WORKER)
        (self.dir / "model.onnx").write_text("")
        self.spoken = queue.Queue()         # "<pid>:<text>" of each WAV pw-play was handed
        self.log = io.StringIO()

        def fake_run(argv, **kwargs):
            out = ""
            if argv[0] == "pw-play":
                self.spoken.put(Path(argv[-1]).read_text())
            elif argv[0] == "pw-dump":
                out = "[]"
            return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

        for p in (mock.patch.object(voice, "MODEL", self.dir / "model.onnx"),
                  mock.patch.object(voice, "PYTHON", Path(sys.executable)),
                  mock.patch.object(voice, "WORKER", self.dir / "worker.py"),
                  mock.patch.object(voice, "READY_S", 1.5),
                  mock.patch.object(voice, "REPLY_S", 0.6),
                  mock.patch.object(voice.shutil, "which", return_value="/usr/bin/pw-play"),
                  mock.patch.object(voice.subprocess, "run", side_effect=fake_run),
                  mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.dir),
                                               "FAKE_DIR": str(self.dir)}),
                  contextlib.redirect_stdout(self.log)):
            p.__enter__()
            self.addCleanup(p.__exit__, None, None, None)
        self.addCleanup(self._no_stray_processes)
        self.voice = None

    def _no_stray_processes(self):
        if self.voice is not None and self.voice._piper is not None:
            self.voice._piper.kill()        # the one that was left running, reaped
        try:
            pids = [int(p) for p in (self.dir / "starts").read_text().split()]
        except OSError:
            pids = []
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)    # only if something got away
            except ProcessLookupError:
                pass

    def start(self, plan):
        os.environ["FAKE_PLAN"] = plan
        self.voice = voice.Voice(FakeSettings())
        self.assertTrue(self.voice._available)
        return self.voice

    def starts(self):
        return [int(p) for p in (self.dir / "starts").read_text().split()]

    def next_spoken(self, timeout=10):
        pid, _, text = self.spoken.get(timeout=timeout).partition(":")
        return int(pid), text

    def assertGone(self, pid):
        with self.assertRaises(ProcessLookupError):     # killed and reaped, not a zombie
            os.kill(pid, 0)

    def assertNothingElseSpoken(self):
        with self.assertRaises(queue.Empty):
            self.spoken.get(timeout=0.3)

    def test_a_line_is_spoken_and_piper_is_kept(self):
        v = self.start("ok")
        v.say("turn left")
        v.say("turn right")
        first, second = self.next_spoken(), self.next_spoken()
        self.assertEqual((first[1], second[1]), ("turn left", "turn right"))
        self.assertEqual(first[0], second[0])           # the same loaded Piper
        self.assertEqual(self.starts(), [first[0]])

    def test_a_piper_that_never_gets_ready_is_replaced(self):
        v = self.start("no-ready,ok")
        t = time.monotonic()
        v.say("stuck behind a slow start")
        v.say("turn left")
        pid, text = self.next_spoken()
        self.assertEqual(text, "turn left")             # the first line is dropped
        self.assertGreaterEqual(time.monotonic() - t, voice.READY_S)
        stuck, fresh = self.starts()
        self.assertEqual(pid, fresh)
        self.assertGone(stuck)
        self.assertNothingElseSpoken()
        self.assertEqual(self.log.getvalue().count("Voice:"), 1)

    def test_a_piper_whose_first_line_is_not_ready_is_replaced(self):
        v = self.start("bad-ready,ok")
        v.say("this one says it isn't ready")
        v.say("turn left")
        pid, text = self.next_spoken()
        self.assertEqual(text, "turn left")             # the first line is dropped
        bad, fresh = self.starts()
        self.assertEqual(pid, fresh)
        self.assertGone(bad)
        self.assertEqual(self.log.getvalue().count("Voice:"), 1)

    def test_a_piper_that_stops_answering_is_replaced(self):
        v = self.start("hang,ok")
        v.say("this one hangs")
        v.say("turn left")
        pid, text = self.next_spoken()
        self.assertEqual(text, "turn left")
        hung, fresh = self.starts()
        self.assertEqual(pid, fresh)
        self.assertGone(hung)
        v.say("turn right")                             # and the fresh one carries on
        self.assertEqual(self.next_spoken(), (fresh, "turn right"))
        self.assertEqual(self.starts(), [hung, fresh])
        self.assertNothingElseSpoken()
        out = self.log.getvalue()
        self.assertEqual(out.count("Voice:"), 1)
        self.assertIn("no answer", out)

    def test_a_piper_that_dies_is_started_again(self):
        v = self.start("die,ok")
        v.say("this one kills it")
        v.say("turn left")
        pid, text = self.next_spoken()
        self.assertEqual(text, "turn left")
        died, fresh = self.starts()
        self.assertEqual(pid, fresh)
        self.assertGone(died)
        self.assertEqual(self.log.getvalue().count("Voice:"), 1)

    def test_a_piper_that_died_while_idle_is_started_again(self):
        v = self.start("ok")
        v.say("turn left")
        old, _ = self.next_spoken()
        os.kill(old, signal.SIGKILL)
        deadline = time.monotonic() + 5
        while not v._piper.exited() and time.monotonic() < deadline:
            time.sleep(0.01)
        v.say("turn right")
        pid, text = self.next_spoken()
        self.assertEqual(text, "turn right")            # no line lost, nothing to log
        self.assertNotEqual(pid, old)
        self.assertEqual(self.log.getvalue(), "")

    def restarts_after_a_bad_reply(self, mode):
        v = self.start(f"{mode},ok")
        v.say("this one gets a bad reply")
        v.say("turn left")
        pid, text = self.next_spoken()
        self.assertEqual(text, "turn left")
        bad, fresh = self.starts()
        self.assertEqual(pid, fresh)
        self.assertGone(bad)
        self.assertEqual(self.log.getvalue().count("Voice:"), 1)

    def test_a_reply_that_is_not_json_restarts_piper(self):
        self.restarts_after_a_bad_reply("garbage")

    def test_a_reply_that_is_a_list_restarts_piper(self):
        self.restarts_after_a_bad_reply("list")          # ["out"] has "out" in it

    def test_a_reply_that_is_a_string_restarts_piper(self):
        self.restarts_after_a_bad_reply("string")        # and so does "out"

    def test_a_reply_for_some_other_wav_restarts_piper(self):
        self.restarts_after_a_bad_reply("wrong-out")

    def test_a_reply_with_neither_out_nor_error_restarts_piper(self):
        self.restarts_after_a_bad_reply("empty")

    def test_an_error_reply_drops_the_line_but_keeps_piper(self):
        v = self.start("error-1st")
        v.say("this one is refused")
        v.say("turn left")
        pid, text = self.next_spoken()
        self.assertEqual(text, "turn left")
        self.assertEqual(self.starts(), [pid])            # not killed, not started again
        out = self.log.getvalue()
        self.assertEqual(out.count("Voice:"), 1)
        self.assertIn("no such voice", out)
        self.assertNotIn("starting it again", out)

    def test_a_piper_that_cannot_be_started_does_not_end_the_voice(self):
        v = self.start("ok")
        v.say("turn left")
        old, _ = self.next_spoken()
        v._piper.kill()                                  # so the next line needs a new one
        with mock.patch.object(voice, "PYTHON", self.dir / "no-such-python"):
            v.say("one")
            v.say("two")
            deadline = time.monotonic() + 10
            while self.log.getvalue().count("Voice:") < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(self.log.getvalue().count("Voice:"), 2)    # one for each line
            self.assertIsNone(v._piper)
        self.assertNothingElseSpoken()
        v.say("turn right")                              # it works again once it can
        pid, text = self.next_spoken()
        self.assertEqual(text, "turn right")
        self.assertNotEqual(pid, old)
        self.assertEqual(self.log.getvalue().count("Voice:"), 2)

    def test_a_job_that_fails_does_not_end_the_voice(self):
        v = self.start("ok")
        with mock.patch.object(voice, "_output_streams",
                               side_effect=[RuntimeError("pw-dump gave nonsense"), {}]):
            v.say("this one fails while ducking")
            v.say("turn left")
            pid, text = self.next_spoken()
            self.assertEqual(text, "turn left")
        out = self.log.getvalue()
        self.assertEqual(out.count("Voice:"), 1)        # logged once
        self.assertIn("pw-dump gave nonsense", out)
        v.say("turn right")                             # the same Piper: it wasn't to blame
        self.assertEqual(self.next_spoken(), (pid, "turn right"))
        self.assertEqual(len(self.starts()), 1)

    def test_a_playback_that_times_out_does_not_end_the_voice(self):
        v = self.start("ok")
        real = voice.subprocess.run
        fail = [True]
        volumes = []                                     # what wpctl was told

        def run(argv, **kwargs):
            if argv[:2] == ["wpctl", "set-volume"]:
                volumes.append(argv[2:])
            if argv[0] == "pw-play" and fail:
                fail.pop()
                raise subprocess.TimeoutExpired(argv, 30)
            return real(argv, **kwargs)

        with mock.patch.object(voice.subprocess, "run", side_effect=run), \
                mock.patch.object(voice, "_output_streams", return_value={7: 1.0}):
            v.say("pw-play hangs on this one")
            v.say("turn left")
            self.assertEqual(self.next_spoken()[1], "turn left")
        self.assertEqual(self.log.getvalue().count("Voice:"), 1)
        # Ducked, and put back even though pw-play raised.
        self.assertEqual(volumes[:2], [["7", "0.300"], ["7", "1.000"]])

    def duck_and_play(self, fail_on):
        """Speak "turn left" over streams 7 and 8. The wpctl set-volume calls
        are numbered from 0 (duck 7, duck 8, put back 7, put back 8); those in
        `fail_on` time out. Returns what the ones that went through set."""
        v = self.start("ok")
        real = voice.subprocess.run
        calls = []                                       # (node, volume) in order, failures too
        done = []

        def run(argv, **kwargs):
            if argv[:2] == ["wpctl", "set-volume"]:
                calls.append(tuple(argv[2:]))
                if len(calls) - 1 in fail_on:
                    raise subprocess.TimeoutExpired(argv, 2)
                done.append(tuple(argv[2:]))
            return real(argv, **kwargs)

        with mock.patch.object(voice.subprocess, "run", side_effect=run), \
                mock.patch.object(voice, "_output_streams", return_value={7: 1.0, 8: 0.8}):
            v.say("turn left")
            self.assertEqual(self.next_spoken()[1], "turn left")
            deadline = time.monotonic() + 5
            while len(calls) < 4 and time.monotonic() < deadline:
                time.sleep(0.01)
        self.assertEqual(len(calls), 4)
        return done

    def test_one_stream_that_will_not_duck_does_not_leave_the_others(self):
        # Stream 8's duck times out: 7 is still ducked, and both are put back.
        done = self.duck_and_play({1})
        self.assertEqual(done, [("7", "0.300"), ("7", "1.000"), ("8", "0.800")])
        self.assertEqual(self.log.getvalue(), "")

    def test_the_first_stream_failing_does_not_skip_the_rest(self):
        done = self.duck_and_play({0, 2})
        self.assertEqual(done, [("8", "0.240"), ("8", "0.800")])

    def test_one_stream_that_will_not_be_put_back_does_not_leave_the_others(self):
        done = self.duck_and_play({2})
        self.assertEqual(done, [("7", "0.300"), ("8", "0.240"), ("8", "0.800")])


if __name__ == "__main__":
    unittest.main()
