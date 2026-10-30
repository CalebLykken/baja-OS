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
        self.mixer = {}                     # node -> volume, what wpctl reports and sets
        self.sets = []                      # (node, volume) in order
        self.played = []                    # each pw-play command line

        def fake_run(argv, **kwargs):
            out = ""
            if argv[:2] == ["wpctl", "get-volume"]:
                node = int(argv[2]) if argv[2].isdigit() else argv[2]   # or the default sink
                if node not in self.mixer:
                    return subprocess.CompletedProcess(argv, 1, stdout="", stderr="no such node")
                out = f"Volume: {self.mixer[node]:.2f}\n"
            elif argv[:2] == ["wpctl", "set-volume"]:
                self.mixer[int(argv[2]) if argv[2].isdigit() else argv[2]] = float(argv[3])
                self.sets.append((argv[2], float(argv[3])))
            elif argv[0] == "pw-play":
                self.played.append(argv)
                self.spoken.put(Path(argv[-1]).read_text())
            elif argv[0] == "pw-dump":
                out = "[]"
            return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

        # Every node id looks like the same app, so a put-back finds its stream by id.
        for p in (mock.patch.object(voice, "_stream_names",
                                    side_effect=lambda: {n: "app" for n in range(100)}),
                  mock.patch.object(voice, "MODEL", self.dir / "model.onnx"),
                  mock.patch.object(voice, "PYTHON", Path(sys.executable)),
                  mock.patch.object(voice, "WORKER", self.dir / "worker.py"),
                  mock.patch.object(voice, "READY_S", 1.5),
                  mock.patch.object(voice, "REPLY_S", 0.6),
                  mock.patch.object(voice.shutil, "which", return_value="/usr/bin/pw-play"),
                  mock.patch.object(voice.subprocess, "run", side_effect=fake_run),
                  mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.dir),
                                               "FAKE_DIR": str(self.dir),
                                               "XDG_STATE_HOME": str(self.dir / "state")}),
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

    def duck_and_play(self, fail_on, expect=4):
        """Speak "turn left" over streams 7 and 8. The wpctl set-volume calls
        are numbered from 0 (duck 7, duck 8, put back 7, put back 8; a stream whose duck failed
        is not put back); those in `fail_on` time out. Returns what the ones that went through set."""
        self.mixer.update({7: 1.0, 8: 0.8})
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
            while len(calls) < expect and time.monotonic() < deadline:
                time.sleep(0.01)
        self.assertEqual(len(calls), expect)
        return done

    def test_one_stream_that_will_not_duck_does_not_leave_the_others(self):
        # Stream 8's duck times out: 7 is still ducked, and both are put back.
        done = self.duck_and_play({1}, 3)
        self.assertEqual(done, [("7", "0.300"), ("7", "1.000")])
        self.assertEqual(self.log.getvalue(), "")

    def test_the_first_stream_failing_does_not_skip_the_rest(self):
        done = self.duck_and_play({0}, 3)
        self.assertEqual(done, [("8", "0.240"), ("8", "0.800")])

    def test_one_stream_that_will_not_be_put_back_does_not_leave_the_others(self):
        done = self.duck_and_play({2})
        self.assertEqual(done, [("7", "0.300"), ("8", "0.240"), ("8", "0.800")])


    # ---- spoken directions volume
    SINK = "@DEFAULT_AUDIO_SINK@"

    def say_with(self, sink, settings=None, music=1.0, names=None, streams=None):
        """Say a line; `names` and `streams` are what pw-dump and wpctl show of
        the other streams (default: just stream 7, readable)."""
        settings = settings or {}
        self.mixer[self.SINK] = sink
        self.mixer[7] = music
        names = {7: "app"} if names is None else names
        streams = {7: music} if streams is None else streams
        v = self.start("ok")
        v._settings = mock.Mock(get=lambda k, d=None: settings.get(k, d))
        v._level = voice.clamp_level(settings.get("voiceVolume", 70))
        with mock.patch.object(voice, "_output_streams", return_value=streams), \
                mock.patch.object(voice, "_stream_names", return_value=names):
            v.say("turn left")
            self.next_spoken()
            time.sleep(0.3)                  # the put-back after pw-play
        argv = self.played[0]
        return float(argv[argv.index("--volume") + 1])

    def sink_sets(self):
        return [v for n, v in self.sets if n == self.SINK]

    def test_with_the_output_at_full_the_stream_plays_at_the_level(self):
        # Spotify: the output sits at the ceiling.
        self.assertAlmostEqual(self.say_with(1.0, {"voiceVolume": 60}), 0.6 ** 3, places=3)
        self.assertEqual(self.sink_sets(), [])

    def test_the_ceiling_scales_the_level(self):
        # Headphones: ceiling 50%, output at 0.5, level 80% -> 0.4 at the speaker. wpctl's
        # volume is cubic, pw-play's linear: the stream gets the ratio cubed.
        vol = self.say_with(0.5, {"voiceVolume": 80, "maxVolume": 50})
        self.assertAlmostEqual(vol, 0.8 ** 3, places=3)

    def test_quiet_local_music_does_not_make_directions_quiet(self):
        # Output at 0.1 (music turned down): raised to the target for the line, then put back.
        vol = self.say_with(0.1, {"voiceVolume": 70})
        self.assertAlmostEqual(vol, 1.0)
        self.assertEqual([round(x, 3) for x in self.sink_sets()], [0.7, 0.1])
        # The music went to 0.3 x (0.1 / 0.7), not 0.3: it stays as quiet as it was.
        music = [v for n, v in self.sets if n == "7"]
        self.assertAlmostEqual(music[0], 0.3 * 0.1 / 0.7, places=3)
        self.assertAlmostEqual(self.mixer[7], 1.0)

    def test_music_at_zero_does_not_mute_directions(self):
        vol = self.say_with(0.0, {"voiceVolume": 70})
        self.assertAlmostEqual(vol, 1.0)
        self.assertEqual(self.sink_sets(), [0.7, 0.0])
        self.assertEqual([v for n, v in self.sets if n == "7"][0], 0.0)    # music stays silent

    def test_an_output_moved_during_the_line_is_left_alone(self):
        v = self.start("ok")
        self.mixer[self.SINK] = 0.1
        real = voice.subprocess.run

        def run(argv, **kwargs):
            if argv[0] == "pw-play":
                self.mixer[self.SINK] = 0.4          # the knob
            return real(argv, **kwargs)
        with mock.patch.object(voice.subprocess, "run", side_effect=run), \
                mock.patch.object(voice, "_output_streams", return_value={}), \
                mock.patch.object(voice, "_stream_names", return_value={}):
            v.say("turn left")
            self.next_spoken()
            time.sleep(0.3)
        self.assertEqual(self.mixer[self.SINK], 0.4)

    def test_no_raise_when_pw_dump_fails(self):
        v = self.start("ok")
        v._level = 70
        self.mixer[self.SINK] = 0.1
        with mock.patch.object(voice, "_output_streams", return_value={}), \
                mock.patch.object(voice, "_stream_names", return_value=None):
            v.say("turn left")
            self.next_spoken()
            time.sleep(0.3)
        self.assertEqual(self.sink_sets(), [])

    def test_no_raise_when_a_stream_cannot_be_read(self):
        # Stream 8 is there but wpctl won't say its volume, so it can't be ducked.
        self.say_with(0.1, {"voiceVolume": 70}, names={7: "app", 8: "other"}, streams={7: 1.0})
        self.assertEqual(self.sink_sets(), [])

    def test_no_raise_when_a_stream_will_not_duck(self):
        real = voice.subprocess.run

        def run(argv, **kwargs):
            if argv[:3] == ["wpctl", "set-volume", "7"]:
                raise subprocess.TimeoutExpired(argv, 2)
            return real(argv, **kwargs)
        with mock.patch.object(voice.subprocess, "run", side_effect=run):
            self.say_with(0.1, {"voiceVolume": 70})
        self.assertEqual(self.sink_sets(), [])

    def test_an_output_that_cannot_be_read_afterwards_is_still_put_back(self):
        v = self.start("ok")
        v._level = 70
        self.mixer[self.SINK] = 0.1
        self.mixer[7] = 1.0
        reads = []
        real = voice._volume

        def volume(node):
            if node == self.SINK:
                reads.append(1)
                return real(node) if len(reads) == 1 else None    # the plan reads it; the put-back can't
            return real(node)
        with mock.patch.object(voice, "_volume", side_effect=volume), \
                mock.patch.object(voice, "_output_streams", return_value={7: 1.0}), \
                mock.patch.object(voice, "_stream_names", return_value={7: "app"}):
            v.say("turn left")
            self.next_spoken()
            time.sleep(0.3)
        self.assertEqual([round(x, 3) for x in self.sink_sets()], [0.7, 0.1])

    def test_the_level_is_saved_and_never_below_the_minimum(self):
        saved = {}
        settings = FakeSettings()
        settings.set = lambda k, val: saved.update({k: val})
        v = voice.Voice(settings)
        v.setLevel(0)
        self.assertEqual(v.level, voice.VOICE_LEVEL[0])
        self.assertEqual(saved["voiceVolume"], voice.VOICE_LEVEL[0])
        v.setLevel(500)
        self.assertEqual(v.level, 100)
        self.assertEqual(voice.clamp_level("junk"), voice.VOICE_LEVEL_DEFAULT)


class FakeMixer:
    """pw-dump and wpctl over a dict of node -> volume, for the Ducker."""

    def __init__(self, volumes):
        self.volumes = dict(volumes)
        self.names = {n: f"app{n}/App {n}" for n in volumes}
        self.sets = []
        self.dump_fails = False
        self.get_fails = set()          # nodes whose get-volume times out
        self.set_fails = set()          # and whose set-volume does

    def add(self, node, volume, name=None):
        self.volumes[node] = volume
        self.names[node] = name or f"app{node}/App {node}"

    def remove(self, node):
        self.volumes.pop(node)
        self.names.pop(node)

    def renumber(self, old, new):
        """The node comes back under another id, as after a reboot."""
        self.volumes[new] = self.volumes.pop(old)
        self.names[new] = self.names.pop(old)

    def streams(self):
        return {} if self.dump_fails else dict(self.volumes)

    def stream_names(self):
        return None if self.dump_fails else dict(self.names)

    def run(self, argv, **kwargs):
        node = int(argv[2]) if len(argv) > 2 else None
        if argv[:2] == ["wpctl", "get-volume"]:
            if node in self.get_fails:
                raise subprocess.TimeoutExpired(argv, 2)
            if node not in self.volumes:
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr="")
            return subprocess.CompletedProcess(argv, 0, stdout=f"Volume: {self.volumes[node]:.2f}\n", stderr="")
        if argv[:2] == ["wpctl", "set-volume"]:
            if node in self.set_fails:
                raise subprocess.TimeoutExpired(argv, 2)
            self.sets.append((node, float(argv[3])))
            if node in self.volumes:
                self.volumes[node] = float(argv[3])
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


class DuckerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "state" / "duck.json"
        self.mixer = FakeMixer({7: 1.0, 8: 0.8})
        self.now = [1000.0]                 # the clock the Ducker's deadlines use
        self.log = io.StringIO()
        for p in (mock.patch.object(voice.time, "monotonic", side_effect=lambda: self.now[0]),
                  contextlib.redirect_stdout(self.log),
                  mock.patch.object(voice.subprocess, "run", side_effect=self.mixer.run),
                  mock.patch.object(voice, "_output_streams", side_effect=self.mixer.streams),
                  mock.patch.object(voice, "_stream_names", side_effect=self.mixer.stream_names)):
            p.__enter__()
            self.addCleanup(p.__exit__, None, None, None)

    def ducker(self):
        return voice.Ducker(self.path)

    def test_streams_go_back_to_exactly_what_they_were(self):
        d = self.ducker()
        d.duck()
        self.assertEqual(self.mixer.volumes, {7: 0.3, 8: 0.24})
        self.assertTrue(self.path.exists())             # saved before the volumes moved
        d.release()
        self.assertEqual(self.mixer.volumes, {7: 1.0, 8: 0.8})
        self.assertFalse(self.path.exists())

    def test_a_second_line_while_ducked_does_not_save_the_ducked_level(self):
        d = self.ducker()
        d.duck()
        d.duck()
        d.release()
        self.assertEqual(self.mixer.volumes, {7: 0.3, 8: 0.24})     # still ducked: one line to go
        d.release()
        self.assertEqual(self.mixer.volumes, {7: 1.0, 8: 0.8})

    def test_a_stream_that_appears_while_ducked_is_ducked_and_restored(self):
        d = self.ducker()
        d.duck()
        self.mixer.add(9, 0.5)
        d.duck()
        self.assertEqual(self.mixer.volumes[9], 0.15)
        self.assertEqual(self.mixer.volumes[7], 0.3)                 # not ducked twice
        d.release()
        d.release()
        self.assertEqual(self.mixer.volumes, {7: 1.0, 8: 0.8, 9: 0.5})

    def test_a_stream_that_vanishes_while_ducked_is_dropped(self):
        d = self.ducker()
        d.duck()
        self.mixer.remove(7)
        d.release()
        self.assertEqual(self.mixer.volumes, {8: 0.8})
        self.assertNotIn(7, [n for n, _ in self.mixer.sets[2:]])     # nothing set on the dead node
        self.assertFalse(d.pending)
        self.assertFalse(self.path.exists())

    def test_a_stream_moved_during_the_line_keeps_its_new_volume(self):
        d = self.ducker()
        d.duck()
        self.mixer.volumes[7] = 0.6                                  # the phone's slider
        d.release()
        self.assertEqual(self.mixer.volumes, {7: 0.6, 8: 0.8})

    def test_a_volume_read_that_times_out_is_retried_not_forgotten(self):
        d = self.ducker()
        d.duck()
        self.mixer.get_fails = {7}
        d.release()
        self.assertEqual(self.mixer.volumes, {7: 0.3, 8: 0.8})       # 7 still ducked
        self.assertTrue(d.pending)
        self.assertTrue(self.path.exists())                          # and still in the file
        self.mixer.get_fails = set()
        d.retry()
        self.assertEqual(self.mixer.volumes, {7: 1.0, 8: 0.8})
        self.assertFalse(d.pending)
        self.assertFalse(self.path.exists())

    def test_a_set_that_times_out_is_retried_not_forgotten(self):
        d = self.ducker()
        d.duck()
        self.mixer.set_fails = {8}
        d.release()
        self.assertEqual(self.mixer.volumes, {7: 1.0, 8: 0.24})
        self.assertTrue(d.pending)
        self.mixer.set_fails = set()
        d.retry()
        self.assertEqual(self.mixer.volumes, {7: 1.0, 8: 0.8})
        self.assertFalse(self.path.exists())

    def test_pw_dump_failing_keeps_everything_for_later(self):
        d = self.ducker()
        d.duck()
        self.mixer.dump_fails = True
        d.release()
        self.assertTrue(d.pending)
        self.assertTrue(self.path.exists())
        self.mixer.dump_fails = False
        d.retry()
        self.assertEqual(self.mixer.volumes, {7: 1.0, 8: 0.8})

    def test_a_restart_while_ducked_puts_the_streams_back(self):
        self.ducker().duck()                                        # ...and the dashboard dies here
        self.assertEqual(self.mixer.volumes, {7: 0.3, 8: 0.24})
        self.ducker().recover()                                     # the next start
        self.assertEqual(self.mixer.volumes, {7: 1.0, 8: 0.8})
        self.assertFalse(self.path.exists())

    def test_after_a_reboot_streams_are_matched_by_name_not_id(self):
        self.ducker().duck()
        self.mixer.renumber(7, 31)                                  # PipeWire gave new ids
        self.mixer.renumber(8, 32)
        self.mixer.add(7, 0.3, "other/Some other app")              # old id 7 is a different stream at 30%
        d = self.ducker()
        d.recover()
        self.assertEqual(self.mixer.volumes, {31: 1.0, 32: 0.8, 7: 0.3})
        self.assertFalse(self.path.exists())

    def test_recovery_leaves_streams_that_were_changed_or_are_gone(self):
        self.ducker().duck()
        self.mixer.volumes[7] = 0.9                                 # moved since
        self.mixer.remove(8)                                        # closed since
        self.mixer.add(10, 0.3)                                     # someone's own 30%, not in the file
        d = self.ducker()
        d.recover()
        self.assertEqual(self.mixer.volumes, {7: 0.9, 10: 0.3})
        self.assertTrue(d.pending)                                  # 8 may still come up...
        self.now[0] += voice.RECOVER_S + 1
        d.retry()
        self.assertFalse(d.pending)                                 # ...but not for ever
        self.assertFalse(self.path.exists())

    def test_recovery_waits_for_pipewire_and_keeps_the_file_meanwhile(self):
        self.ducker().duck()
        self.mixer.dump_fails = True
        d = self.ducker()
        d.recover()
        self.assertTrue(self.path.exists())
        self.assertEqual(self.mixer.volumes, {7: 0.3, 8: 0.24})
        self.mixer.dump_fails = False
        d.retry()
        self.assertEqual(self.mixer.volumes, {7: 1.0, 8: 0.8})
        self.assertFalse(self.path.exists())

    def test_a_stream_that_comes_up_ducked_after_a_restart_is_put_back(self):
        # WirePlumber bringing the app's stream back at 30% under a new id.
        self.ducker().duck()
        self.mixer.remove(7)
        d = self.ducker()
        d.recover()
        self.assertTrue(d.pending)
        self.mixer.add(41, 0.3, "app7/App 7")
        d.retry()
        self.assertEqual(self.mixer.volumes[41], 1.0)

    def test_the_wait_for_a_stream_starts_when_pipewire_first_answers(self):
        self.ducker().duck()
        self.mixer.remove(7)
        self.mixer.remove(8)
        self.mixer.dump_fails = True                                # boot: PipeWire not up yet
        d = self.ducker()
        d.recover()
        self.now[0] += 500                                          # within PIPEWIRE_WAIT_S
        d.retry()
        self.mixer.dump_fails = False                               # now it answers: no streams yet
        d.retry()
        self.assertTrue(d.pending)
        self.now[0] += voice.RECOVER_S - 60                         # Soloist starts playing, much later
        self.mixer.add(51, 0.3, "app7/App 7")                       # and WirePlumber brings it back at 30%
        d.retry()
        self.assertEqual(self.mixer.volumes, {51: 1.0})
        self.assertTrue(d.pending)                                  # 8 never came; still waiting
        self.now[0] += 120
        d.retry()
        self.assertFalse(d.pending)
        self.assertFalse(self.path.exists())

    def test_pipewire_that_never_answers_is_given_up_on_once(self):
        self.ducker().duck()
        self.mixer.dump_fails = True
        d = self.ducker()
        d.recover()
        self.now[0] += voice.PIPEWIRE_WAIT_S + 1
        d.retry()
        self.assertFalse(d.pending)
        self.assertFalse(self.path.exists())
        d.retry()
        self.assertEqual(self.log.getvalue().count("gave up"), 2)   # one line per entry, 7 and 8

    def test_a_volume_that_cannot_be_read_is_given_up_on(self):
        d = self.ducker()
        d.duck()
        self.mixer.get_fails = {7}
        d.release()
        self.now[0] += 60
        d.retry()
        self.assertTrue(d.pending)
        self.now[0] += voice.GIVE_UP_S
        d.retry()
        d.retry()
        self.assertFalse(d.pending)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.log.getvalue().count("gave up"), 1)

    def test_a_volume_that_cannot_be_set_is_given_up_on(self):
        d = self.ducker()
        d.duck()
        self.mixer.set_fails = {8}
        d.release()
        self.assertTrue(d.pending)
        self.now[0] += voice.GIVE_UP_S + 1
        d.retry()
        self.assertFalse(d.pending)
        self.assertEqual(self.mixer.volumes, {7: 1.0, 8: 0.24})
        self.assertEqual(self.log.getvalue().count("gave up"), 1)

    def test_a_line_spoken_while_a_last_run_entry_waits_keeps_its_real_before(self):
        self.ducker().duck()
        self.mixer.remove(7)
        d = self.ducker()
        d.recover()
        self.mixer.add(41, 0.3, "app7/App 7")                       # back at 30%, not yet retried
        d.duck()                                                    # a new line starts
        self.assertEqual(self.mixer.volumes[41], 0.3)               # not ducked to 9%
        d.release()
        self.assertEqual(self.mixer.volumes[41], 1.0)               # the file's "before", not 0.3

    def test_recovery_with_no_file_or_a_broken_one_does_nothing(self):
        self.ducker().recover()
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json")
        self.ducker().recover()
        self.assertEqual(self.mixer.sets, [])
        self.assertFalse(self.path.exists())

    def test_a_file_that_cannot_be_written_does_not_stop_the_duck(self):
        self.path.parent.write_text("a file where the folder should be")
        d = self.ducker()
        with contextlib.redirect_stdout(io.StringIO()):
            d.duck()
            d.release()
        self.assertEqual(self.mixer.volumes, {7: 1.0, 8: 0.8})


if __name__ == "__main__":
    unittest.main()
