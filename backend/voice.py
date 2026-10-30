"""Spoken directions: turns a line of text into speech with Piper and plays
it over the music, which dips while it speaks.

Piper runs in its own process (voice_worker.py, under the Piper install's
Python from deploy/audio/install-voice.sh), started on first use and kept
loaded. Playback is `pw-play`; the other audio streams are turned down
with `wpctl` for the length of the line and put back afterwards, so
Spotify's own volume (and the phone's slider) never moves. Directions have
their own level (Settings > Sound), a share of the output ceiling that does
not depend on the music: the voice stream is turned down to it, or if the
output is quieter than that (music at 0, say) the output is raised for the
length of the line, with the music ducked further to stay as quiet as it
was. The volumes to go back to are written to a file first, so a dashboard that dies mid-line
puts them back on its next start instead of leaving the music at 30%.

A Piper that stops answering, or exits, is killed and started again for the
next line (the line it was stuck on is dropped), so spoken directions can't
end for good.
"""

import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot

ROOT = Path(__file__).resolve().parent.parent
VOICE_DIR = Path(os.environ.get("BAJA_VOICE_DIR", "~/.local/share/baja-os/voice")).expanduser()
MODEL = VOICE_DIR / "en_US-kristin-medium.onnx"
PYTHON = VOICE_DIR / "venv" / "bin" / "python"
WORKER = ROOT / "backend" / "voice_worker.py"
NODE_NAME = "baja-voice"
# The equalizer's own output carries everything, the voice included; leave it.
NOT_DUCKED = {NODE_NAME, "baja_eq.output"}
DUCK_TO = 0.3           # other audio drops to this share of its volume while speaking
STALE_S = 8             # a line not spoken within this long is dropped
READY_S = 30            # Piper has this long to load the voice (~2 s on the Pi)
REPLY_S = 15            # and this long to turn a line into speech (~0.5 s)
PIPEWIRE_WAIT_S = 600   # after a restart, PipeWire has this long to start answering
RECOVER_S = 1800        # then a stream from the last run has this long to appear (Soloist's
                        # only does once playback starts); the level check keeps waiting safe
GIVE_UP_S = 120         # a put-back that keeps failing is dropped after this long
RETRY_S = 2             # between tries at putting back what wpctl would not
VOICE_LEVEL = (30, 100)  # Settings > Sound > Spoken directions volume, % of the ceiling; never muted
VOICE_LEVEL_DEFAULT = 70
SINK = "@DEFAULT_AUDIO_SINK@"
DUCK_TOL = 0.02         # wpctl prints two decimals; a stream within this of the duck level is still ducked


def _dump_streams():
    """[(node id, name)] of the other audio streams, None if pw-dump failed.
    The name is what survives a restart (node ids are new after a reboot)."""
    try:
        out = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=3).stdout
        objects = json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    streams = []
    for o in objects:
        props = ((o.get("info") or {}).get("props") or {})
        if props.get("media.class") != "Stream/Output/Audio" or props.get("node.name") in NOT_DUCKED:
            continue
        streams.append((o["id"], f"{props.get('node.name', '')}/{props.get('application.name', '')}"))
    return streams


def _stream_names():
    """{node id: name} of the other streams, None if pw-dump failed."""
    streams = _dump_streams()
    return None if streams is None else dict(streams)


def _output_streams():
    """{node id: volume} of the other audio streams playing right now."""
    streams = {}
    for node, _ in _dump_streams() or []:
        vol = _volume(node)
        if vol is not None:
            streams[node] = vol
    return streams


def _volume(node):
    """The stream's volume now, None if wpctl won't say."""
    try:
        r = subprocess.run(["wpctl", "get-volume", str(node)], capture_output=True,
                           text=True, timeout=2)
        m = re.search(r"Volume: ([\d.]+)", r.stdout or "")
        return float(m[1]) if r.returncode == 0 and m else None
    except (OSError, subprocess.SubprocessError):
        return None


def _set_volumes(volumes):
    """One stream failing (wpctl timing out) doesn't leave the rest as they
    were. Returns the nodes that were set."""
    done = set()
    for node, vol in volumes.items():
        try:
            r = subprocess.run(["wpctl", "set-volume", str(node), f"{vol:.3f}"],
                               capture_output=True, timeout=2)
            if r.returncode == 0:
                done.add(node)
        except (OSError, subprocess.SubprocessError):
            pass
    return done


def clamp_level(value):
    """A saved spoken-directions level as a whole % within VOICE_LEVEL."""
    try:
        value = int(float(str(value)))
    except (TypeError, ValueError):
        value = VOICE_LEVEL_DEFAULT
    return max(VOICE_LEVEL[0], min(VOICE_LEVEL[1], value))


def _state_file():
    base = os.environ.get("XDG_STATE_HOME") or "~/.local/state"
    return Path(base).expanduser() / "baja-os" / "duck.json"


class Ducker:
    """Turns the other streams down and puts back exactly what it took.

    The volume each stream had before is saved (in memory and in a file, with
    the stream's name) before anything is turned down. A stream is put back
    only if it is still at the level we set: one that is gone is dropped, and
    one somebody moved meanwhile (the phone's slider, say) keeps its new
    volume. If PipeWire or wpctl just doesn't answer, that is not "gone": the
    entry stays (and in the file) and is tried again. Ducks nest: a second
    line while ducked saves only the streams that weren't ducked yet, never
    the ducked level as a "before", and the restore waits for the last."""

    def __init__(self, path=None):
        self._path = path or _state_file()
        self._lock = threading.Lock()
        self._saved = []            # {"id", "name", "before", "ducked", "until"}
        self._depth = 0

    @property
    def pending(self):
        """Something still to put back, and nobody speaking: call retry()."""
        return bool(self._saved) and self._depth == 0

    def _write(self):
        try:
            if not self._saved:
                self._path.unlink(missing_ok=True)
                return
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(self._path.name + ".tmp")
            tmp.write_text(json.dumps([{k: e[k] for k in ("id", "name", "before", "ducked")}
                                       for e in self._saved]))
            os.replace(tmp, self._path)
        except OSError as e:
            print(f"Voice: couldn't update {self._path} ({e!r})", flush=True)

    def duck(self, scale=1.0):
        """Turn down every stream not already ducked, to DUCK_TO of what it
        was times `scale` (<1 while the output is raised for the voice, so
        the music stays as quiet as it was). True if every stream was read
        and turned down."""
        with self._lock:
            self._depth += 1
            dumped = _stream_names()
            names = dumped or {}
            held = {e["id"] for e in self._saved if names.get(e["id"]) == e["name"]}
            # A stream the last run left ducked, now back at that level, already has
            # its real "before" on file: don't save the ducked level as a new one.
            waiting = {e["name"] for e in self._saved if e["recovered"] and e["name"]}
            new = {n: v for n, v in _output_streams().items()
                   if n not in held and names.get(n) not in waiting}
            for n, v in new.items():
                self._saved.append({"id": n, "name": names.get(n, ""), "before": v,
                                    "ducked": v * DUCK_TO * scale, "give_up": None, "started": True,
                                    "failing": False, "recovered": False})
            self._write()               # before any volume moves
            done = _set_volumes({n: v * DUCK_TO * scale for n, v in new.items()})
            unread = set(names) - set(new) - held   # streams wpctl wouldn't read
            return dumped is not None and not unread and done == set(new)

    def release(self):
        with self._lock:
            self._depth = max(0, self._depth - 1)
            if self._depth == 0:
                self._put_back()

    def retry(self):
        """Another go at what couldn't be put back."""
        with self._lock:
            if self._depth == 0 and self._saved:
                self._put_back()

    def recover(self):
        """On start: take on what a dashboard that died while ducked left, and
        put it back. Nodes have new ids after a reboot, so streams are matched
        by name. A stream that hasn't come up yet is waited for, RECOVER_S from
        the first time PipeWire answers (WirePlumber may bring it up at the
        ducked level, and Soloist's only exists once playback starts); if
        PipeWire never answers it's given up on after PIPEWIRE_WAIT_S. Only streams still
        at the level we set are touched, so nothing the user changed since is
        overwritten, and streams not in the file are left alone: guessing
        "everything at 30%" would also move ones set to 30% on purpose. If
        PipeWire isn't answering the file is kept for the retries."""
        try:
            data = json.loads(self._path.read_text())
            left = [{"id": int(e["id"]), "name": str(e["name"]), "before": float(e["before"]),
                     "ducked": float(e["ducked"]), "give_up": time.monotonic() + PIPEWIRE_WAIT_S,
                     "started": False, "failing": False, "recovered": True}
                    for e in data]
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            left = []
        with self._lock:
            self._saved.extend(left)
            if self._saved and self._depth == 0:
                self._put_back()
            else:
                self._write()

    @staticmethod
    def _fail(e, now):
        """This entry couldn't be put back this time; it gets GIVE_UP_S of tries."""
        if not e["failing"]:
            e["failing"] = True
            e["give_up"] = min(e["give_up"] or now + GIVE_UP_S, now + GIVE_UP_S)

    def _put_back(self):
        now = time.monotonic()
        names = _stream_names()
        if names is not None:
            for e in self._saved:
                if e["recovered"] and not e["started"]:
                    e["started"] = True     # PipeWire answers: the wait for the stream starts now
                    e["give_up"] = now + RECOVER_S
        else:                               # pw-dump isn't answering
            for e in self._saved:
                if not e["recovered"]:
                    self._fail(e, now)
        live = []
        for e in self._saved:
            if e["give_up"] is not None and now > e["give_up"]:
                print(f"Voice: gave up putting back {e['name'] or e['id']} to {e['before']:.2f}", flush=True)
            else:
                live.append(e)
        self._saved = live
        if names is None:                   # keep the rest for later
            self._write()
            return
        by_id = {e["id"] for e in self._saved if names.get(e["id"]) == e["name"]}
        keep, todo = [], {}
        for e in self._saved:
            if e["id"] in by_id and names.get(e["id"]) == e["name"]:
                node = e["id"]
            else:
                same = [n for n, nm in names.items() if nm == e["name"] and n not in by_id]
                node = same[0] if e["name"] and len(same) == 1 else None
            if node is None:
                if e["recovered"]:
                    keep.append(e)          # recovering: it may yet appear
                continue                    # gone
            now_vol = _volume(node)
            if now_vol is None:
                self._fail(e, now)
                keep.append(e)              # wpctl didn't answer: not the same as gone
            elif abs(now_vol - e["ducked"]) <= DUCK_TOL:
                todo[node] = e              # else: moved since; leave it
        done = _set_volumes({n: e["before"] for n, e in todo.items()})
        for n, e in todo.items():
            if n not in done:
                self._fail(e, now)
                keep.append(e)
        self._saved = keep
        self._write()


class _Piper:
    """One voice_worker.py process. A thread reads its stdout into a queue so
    that waiting for an answer can time out: readline() on the pipe itself
    can't, and select() on a buffered text pipe can say "nothing" while Python
    is already holding the line."""

    def __init__(self):
        self._proc = subprocess.Popen(
            # -I: nothing in backend/ can shadow what Piper imports.
            [str(PYTHON), "-I", str(WORKER), str(MODEL)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1)
        self._lines = queue.Queue()
        threading.Thread(target=self._read, name="voice-reader", daemon=True).start()

    def _read(self):
        try:
            for line in self._proc.stdout:
                self._lines.put(line)
        except (OSError, ValueError):
            pass                                    # the pipe went away under us
        self._lines.put(None)                       # the end: it exited or was killed
        try:
            self._proc.stdout.close()
        except OSError:
            pass

    def exited(self):
        return self._proc.poll() is not None

    def send(self, line):
        self._proc.stdin.write(line)                # line-buffered: out at the newline

    def readline(self, timeout):
        """The next line Piper wrote. TimeoutError if it takes longer than
        `timeout` seconds, EOFError if it has exited."""
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"no answer in {timeout:g} s") from None
        if line is None:
            self._lines.put(None)                   # it stays at the end
            raise EOFError("it exited")
        return line

    def kill(self):
        """Stop it, whatever it's doing, and reap it."""
        self._proc.kill()
        try:
            self._proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        try:
            self._proc.stdin.close()
        except OSError:
            pass


class Voice(QObject):
    changed = pyqtSignal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        # Off unless turned on (Settings > Sound, or the speaker key while navigating).
        self._enabled = str(settings.get("voice", "false")) == "true"
        self._available = MODEL.is_file() and PYTHON.is_file() and bool(shutil.which("pw-play"))
        self._jobs = queue.Queue()
        self._piper = None
        self._ducker = Ducker()
        self._level = clamp_level(settings.get("voiceVolume", VOICE_LEVEL_DEFAULT))
        self._tmp = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
        if self._available:
            threading.Thread(target=self._run, name="voice", daemon=True).start()

    # ---- the worker ------------------------------------------------------------------
    def _worker(self):
        if self._piper is not None and self._piper.exited():
            self._drop_worker()                     # it died between lines
        if self._piper is None:
            self._piper = _Piper()
            ready = json.loads(self._piper.readline(READY_S))   # {"ready": true} once the voice is loaded
            if not (isinstance(ready, dict) and ready.get("ready") is True):
                raise ValueError(f"unexpected first line {ready!r}")
        return self._piper

    def _drop_worker(self):
        piper, self._piper = self._piper, None
        if piper is not None:
            piper.kill()

    def _synthesize(self, text, out):
        """Have Piper write the WAV `out`; True if it did. A Piper that
        doesn't answer in time, exits or says something unreadable is killed
        and a fresh one starts with the next line; this line is dropped. One
        that answers {"error": ...} is fine, only that line is dropped."""
        try:
            piper = self._worker()
            piper.send(json.dumps({"text": text, "out": out}) + "\n")
            reply = json.loads(piper.readline(REPLY_S))
            # Its own {"out": this line's WAV} or {"error": ...}; anything else
            # (another line's WAV, say) means it's out of step.
            if not isinstance(reply, dict) or (reply.get("out") != out and "error" not in reply):
                raise ValueError(f"unexpected reply {reply!r}")
        except Exception as e:
            print(f"Voice: Piper failed ({e!r}); starting it again for the next line", flush=True)
            self._drop_worker()
            return False
        if "out" not in reply:
            print(f"Voice: Piper couldn't say that line ({reply.get('error')})", flush=True)
            return False
        return True

    def _target(self):
        """How loud a line should be at the speaker, 0-1: the voice level
        as a share of the output ceiling (Settings > Sound > Loudest volume)."""
        try:
            ceiling = max(30, min(100, int(float(str(self._settings.get("maxVolume", 100)))))) / 100
        except (TypeError, ValueError):
            ceiling = 1.0
        return self._level / 100 * ceiling

    def _plan_levels(self):
        """(stream volume for pw-play, output level to raise to or None, scale
        for ducking the music). The stream is only ever turned down, never
        amplified (Piper's WAVs are near full scale), so an output quieter
        than the target is raised instead. Without a reading of the output
        the stream just plays at the level. wpctl volumes are cubic in amplitude
        and pw-play's is linear, so the stream gets the ratio cubed."""
        target = self._target()
        sink = _volume(SINK)
        if sink is None:
            return (self._level / 100) ** 3, None, 1.0
        if sink >= target:
            return (target / sink) ** 3, None, 1.0
        return 1.0, target, sink / target

    def _run(self):
        n = 0
        try:
            self._ducker.recover()
        except Exception as e:
            print(f"Voice: couldn't put back volumes from a last run ({e!r})", flush=True)
        while True:
            try:
                text, queued_at = self._jobs.get(timeout=RETRY_S if self._ducker.pending else None)
            except queue.Empty:
                try:
                    self._ducker.retry()
                except Exception as e:
                    print(f"Voice: couldn't put volumes back ({e!r})", flush=True)
                continue
            if time.monotonic() - queued_at > STALE_S:
                continue                            # the moment has passed
            try:
                n += 1
                out = str(self._tmp / f"baja-voice-{n % 4}.wav")
                if not self._synthesize(text, out):
                    continue
                gain, raise_to, scale = self._plan_levels()
                raised = None
                try:
                    ducked = self._ducker.duck(scale)
                    # Raising the output with music not turned down would blast it.
                    if raise_to is not None and ducked and _set_volumes({SINK: raise_to}):
                        raised = raise_to
                    subprocess.run(["pw-play", "--media-role", "Navigation",
                                    "--volume", f"{gain:.3f}",
                                    "--properties", '{ node.name = "%s" }' % NODE_NAME, out],
                                   capture_output=True, timeout=30)
                finally:
                    # The output first, while the music is still ducked, then the music.
                    self._put_back_output(raised, scale)
                    self._ducker.release()
            except Exception as e:                  # never end this thread
                print(f"Voice: couldn't speak a line ({e!r}); on to the next", flush=True)

    def _put_back_output(self, raised, scale):
        """Lower the output again, unless something (the knob) moved it meanwhile.
        Only when the music is back to its own level does it matter: with another
        line queued the next one raises it again."""
        if raised is None:
            return
        now = _volume(SINK)
        if now is None or abs(now - raised) <= DUCK_TOL:     # unreadable: put it back anyway
            _set_volumes({SINK: raised * scale})

    # ---- what QML and the router use -----------------------------------------------
    @pyqtSlot(str)
    def say(self, text):
        if self._available and self._enabled and text:
            self._jobs.put((text, time.monotonic()))

    @pyqtSlot()
    def test(self):
        """Say a sample line, even if spoken directions are off."""
        if self._available:
            self._jobs.put(("In a quarter mile, turn right onto Broad Street.", time.monotonic()))

    @pyqtProperty(bool, constant=True)
    def available(self):
        return self._available

    @pyqtProperty(bool, notify=changed)
    def enabled(self):
        return self._enabled

    @pyqtProperty(int, notify=changed)
    def level(self):
        """Spoken directions volume, 30-100 (% of the loudest volume)."""
        return self._level

    @pyqtSlot(int)
    def setLevel(self, value):
        value = clamp_level(value)
        if value != self._level:
            self._level = value
            self._settings.set("voiceVolume", value)
            self.changed.emit()

    @pyqtSlot(bool)
    def setEnabled(self, on):
        if on != self._enabled:
            self._enabled = on
            self._settings.set("voice", "true" if on else "false")
            self.changed.emit()
