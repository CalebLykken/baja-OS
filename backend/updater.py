"""Updates Baja OS from GitHub, for Settings > System > Software update.

Check for updates runs `git fetch` and lists the new commits' subjects.
Update fast-forwards to exactly the commit the check found (`git merge
--ff-only`, no network, so nothing unseen slips in) and then restarts the
dashboard; the baja-os service starts it again on the new code.

It needs a git checkout on a branch that follows one on GitHub (the
README's `git clone`). A copy made by deploy/push.sh has no .git and is
updated from the Mac instead.

It won't update with tracked files changed here or commits made here
(sort that out over SSH), nor while the truck is moving or directions are
on. The restart waits for the same.

Git is never allowed to ask for anything: no terminal, no askpass, so a
private repo without a key fails at once with a sentence saying so. A
fetch that takes too long is stopped with SIGTERM, which lets git remove
its lock files; the fast-forward is never stopped, since cut off halfway it
would leave a mix of old and new files.

The read-only root (#36) isn't in place yet. Until then a read-only file
system is just reported as such. Once it is, a checkout on the root needs
to move to the writable /data (or the overlay be switched off) first.

The git work is plain functions taking the checkout's path and returning
plain dicts (the tests run them on throwaway repos); `Updater` runs them
on a background thread for QML.
"""

import os
import signal
import subprocess
import threading
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot

from backend import safe_emit

ROOT = Path(__file__).resolve().parent.parent
LOCAL_TIMEOUT_S = 20        # git on the SD card
FETCH_TIMEOUT_S = 120       # over Wi-Fi
STOP_WAIT_S = 5             # after SIGTERM, before SIGKILL
MAX_LISTED = 8              # commit subjects shown; `count` says how many in all
MOVING_MPH = 3.0            # as backend/ignition.py: walking pace counts as stopped
MPH_TO_MS = 0.44704
RESTART_DELAY_MS = 3000     # long enough to read "Updated"

NOT_A_CHECKOUT = ("This copy has no git history (deploy/push.sh copies without it), "
                  "so it can't update itself: push from the Mac instead.")

# What git says, and what to tell the driver. The first match wins, so the
# network comes before "Could not read from remote repository", which
# follows most ssh failures.
_PROBLEMS = (
    (("could not resolve host", "temporary failure in name resolution",
      "name or service not known", "nodename nor servname", "network is unreachable",
      "no route to host", "failed to connect", "couldn't connect", "connection timed out",
      "connection refused", "operation timed out"),
     "Couldn't reach GitHub: is the Pi online?"),
    (("could not read username", "could not read password", "terminal prompts disabled",
      "authentication failed", "permission denied (publickey", "repository not found",
      "host key verification failed", "invalid username or password",
      "returned error: 401", "returned error: 403"),
     "GitHub didn't let this Pi in (the repo is private): give it a key or token over SSH."),
    (("read-only file system",),
     "The Pi's storage is read-only, so git can't write the update."),
    (("no space left on device",),
     "The Pi's storage is full."),
    (("dubious ownership",),
     "Git doesn't trust this folder (another user owns it): fix that over SSH."),
    ((".lock': file exists",),
     "Another git command is running here, or one was cut off and left a lock file "
     "in .git: check over SSH."),
    (("would be overwritten",),
     "Files here are in the way of the update: sort that out over SSH."),
    (("not possible to fast-forward",),
     "This copy has commits of its own, so it can't simply move ahead: sort that out over SSH."),
    (("does not point to a branch",),
     "This copy isn't on a branch, so there's nothing to update from: check out main over SSH."),
    (("no upstream",),
     "This branch doesn't follow one on GitHub, so there's nothing to update from."),
    (("not a git repository",), NOT_A_CHECKOUT),
)


class GitError(Exception):
    """A git command failed: str() is a sentence for the screen."""

    stderr = ""                  # what git said, for callers that look for something


def explain(stderr):
    """A short sentence for what went wrong, from git's error output."""
    low = stderr.lower()
    for needles, sentence in _PROBLEMS:
        if any(n in low for n in needles):
            return sentence
    lines = [x.strip() for x in stderr.splitlines() if x.strip() and not x.startswith("hint:")]
    line = lines[-1].removeprefix("fatal:").removeprefix("error:").strip() if lines else ""
    return "Git: " + (line[:117] + "..." if len(line) > 120 else line) if line \
        else "Git failed without saying why."


def git(root, *args, timeout=LOCAL_TIMEOUT_S):
    """git's output, or GitError. timeout=None waits as long as it takes."""
    # Nothing from the environment that points git elsewhere or lets it ask
    # for a password.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "SSH_ASKPASS"}
    env.update(LC_ALL="C", GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="",
               SSH_ASKPASS_REQUIRE="never", GIT_OPTIONAL_LOCKS="0")
    try:
        # Its own session: no terminal, so ssh can't ask about host keys either.
        p = subprocess.Popen(["git", "-C", str(root), *args], stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                             encoding="utf-8", errors="replace", start_new_session=True)
    except FileNotFoundError:
        raise GitError("Git isn't installed here.") from None
    except OSError as e:
        raise GitError(f"Couldn't run git: {e}") from None
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _stop(p)
        raise GitError("GitHub took too long to answer: try again on better Wi-Fi."
                       if args[0] == "fetch" else f"Git took more than {timeout} s.") from None
    if p.returncode != 0:
        e = GitError(explain(err))
        e.stderr = err
        raise e
    return out


def _stop(p):
    """Stops git and whatever it started (ssh): SIGTERM first, which git
    cleans up its lock files on, then SIGKILL."""
    for sig, wait in ((signal.SIGTERM, STOP_WAIT_S), (signal.SIGKILL, None)):
        try:
            os.killpg(p.pid, sig)
        except OSError:
            pass                            # already gone
        try:
            p.communicate(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            pass


def _plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _blocker(root):
    """Why this checkout can't simply move ahead ('' if it can)."""
    changed = [x[3:] for x in git(root, "status", "--porcelain",
                                  "--untracked-files=no").splitlines() if x.strip()]
    if changed:
        names = ", ".join(changed[:2]) + (f" and {len(changed) - 2} more" if len(changed) > 2 else "")
        return f"files were changed here ({names}): commit or undo that over SSH first."
    own = int(git(root, "rev-list", "--count", "@{u}..HEAD"))
    if own:
        return (f"this copy has {_plural(own, 'commit')} of its own, so it can't simply "
                f"move ahead: sort that out over SSH.")
    return ""


def _result(state, message, commits=(), count=0, target="", can_update=False):
    return {"state": state, "message": message, "commits": list(commits), "count": count,
            "target": target, "can_update": can_update}


def check_for_updates(root):
    """Fetches and compares. Returns a dict:
        state       "current", "available" or "failed"
        message     a sentence for the screen
        commits     the new commits' subjects, newest first (at most MAX_LISTED)
        count       how many new commits there are in all
        target      the commit Update moves to
        can_update  True when Update can fast-forward to it
    """
    try:
        if not (Path(root) / ".git").exists():      # a file, in a git worktree
            raise GitError(NOT_A_CHECKOUT)
        try:
            git(root, "rev-parse", "--abbrev-ref", "HEAD@{u}")   # detached or not following: says so
        except GitError as e:
            if "unknown revision" not in e.stderr.lower():
                raise                       # a missing tracking ref is what the fetch restores
        git(root, "fetch", timeout=FETCH_TIMEOUT_S)
        try:
            target = git(root, "rev-parse", "--verify", "--quiet", "@{u}^{commit}").strip()
        except GitError:
            return _result("failed", "The branch this copy follows isn't on GitHub any more.")
        count = int(git(root, "rev-list", "--count", f"HEAD..{target}"))
        if not count:
            return _result("current", "Up to date.")
        commits = git(root, "log", f"-{MAX_LISTED}", "--format=%s", f"HEAD..{target}").splitlines()
        new = _plural(count, "new change") + " on GitHub"
        blocker = _blocker(root)
        if blocker:
            return _result("available", f"{new}, but {blocker}", commits, count, target)
        return _result("available", new + ".", commits, count, target, can_update=True)
    except GitError as e:
        return _result("failed", str(e))
    except ValueError as e:                         # a count that isn't a number
        return _result("failed", f"Couldn't check: {e}")


def update_to(root, target):
    """Fast-forwards to target (from check_for_updates), after making sure
    again that nothing's in the way. Returns a dict with state "updated"
    (restart now), "current" (already there) or "failed"."""
    try:
        blocker = _blocker(root)
        if blocker:
            return _result("failed", blocker[0].upper() + blocker[1:])
        before = git(root, "rev-parse", "HEAD").strip()
        git(root, "merge", "--ff-only", target, timeout=None)
        after = git(root, "rev-parse", "HEAD").strip()
        if after == before:
            return _result("current", "Up to date.")
        return _result("updated", f"Updated to {after[:7]}. Restarting the dashboard.")
    except GitError as e:
        return _result("failed", str(e))
    except ValueError as e:
        return _result("failed", f"Couldn't update: {e}")


def driving_reason(car_mph, gps_ms, guiding):
    """'' when it's all right to update now, else why not. car_mph and
    gps_ms are None unless they're real: the simulated drive must never
    stop an update."""
    if guiding:
        return "Not while directions are on: tap End on the Maps page first."
    if (car_mph is not None and car_mph > MOVING_MPH) or \
            (gps_ms is not None and gps_ms > MOVING_MPH * MPH_TO_MS):
        return "Not while driving: stop the truck first."
    return ""


class Updater(QObject):
    """Check for updates and Update, for QML.

    vehicle, gps and routing are read on the UI thread to tell whether the
    truck is moving. restart is called once the update is in
    (SystemInfo.restartDashboard). root is the checkout.

    state: "idle", "checking", "current", "available", "updating",
    "updated" (restarting soon) or "failed"; message is a sentence for it;
    commits the new subjects and count how many in all; busy means the keys
    do nothing; canUpdate something new with nothing in git's way.
    """
    changed = pyqtSignal()
    _done = pyqtSignal(dict)

    def __init__(self, vehicle, gps, routing, restart, root=ROOT, parent=None):
        super().__init__(parent)
        self._vehicle = vehicle
        self._gps = gps
        self._routing = routing
        self._restart = restart
        self._root = Path(root)
        self._v = _result("idle", "")
        self._seen_moving = False           # the last real speed was above walking pace
        self._done.connect(self._apply)

    def _why_not_now(self):
        try:
            car = self._vehicle.speed if self._vehicle.live else None
            gps = self._gps.speed if self._gps.realFix else None
            why = driving_reason(car, gps, self._routing.active)
            if car is not None or gps is not None:
                self._seen_moving = "driving" in why
            elif self._seen_moving:         # no speed any more (tunnel, OBD silent): still moving
                return "Not while driving: stop the truck first."
            return why
        except Exception as e:              # can't tell: don't risk it
            return f"Couldn't tell whether the truck is moving ({e})."

    def _run(self, v, job):
        """Shows v and runs job on a worker thread; its result comes back
        to _apply on the UI thread."""
        self._v = v
        self.changed.emit()

        def work():
            try:
                result = job()
            except Exception as e:          # never leave it stuck busy
                result = _result("failed", f"Something went wrong: {e}")
            safe_emit(self, "_done", result)
        threading.Thread(target=work, name="updater", daemon=True).start()

    def _apply(self, result):
        self._v = result
        print(f"Update: {result['state']}: {result['message']}", flush=True)
        self.changed.emit()
        if result["state"] == "updated":
            QTimer.singleShot(RESTART_DELAY_MS, self._restart_when_stopped)

    def _restart_when_stopped(self):
        if self._why_not_now():
            message = "Updated. The dashboard restarts once the truck has stopped and directions are off."
            if self._v["message"] != message:
                self._v = dict(self._v, message=message)
                self.changed.emit()
            QTimer.singleShot(RESTART_DELAY_MS, self._restart_when_stopped)
            return
        print("Update: restarting the dashboard", flush=True)
        self._restart()

    @pyqtSlot()
    def check(self):
        if not self.busy:
            root = self._root
            self._run(_result("checking", "Checking GitHub"), lambda: check_for_updates(root))

    @pyqtSlot()
    def update(self):
        if self.busy or not self.canUpdate:
            return
        why = self._why_not_now()
        if why:
            self._v = dict(self._v, message=why)
            self.changed.emit()
            return
        root, target = self._root, self._v["target"]
        print(f"Update: moving to {target[:7]}", flush=True)
        self._run(dict(self._v, state="updating", message="Updating", can_update=False),
                  lambda: update_to(root, target))

    @pyqtProperty(str, notify=changed)
    def state(self):
        return self._v["state"]

    @pyqtProperty(str, notify=changed)
    def message(self):
        return self._v["message"]

    @pyqtProperty("QStringList", notify=changed)
    def commits(self):
        return self._v["commits"]

    @pyqtProperty(int, notify=changed)
    def count(self):
        return self._v["count"]

    @pyqtProperty(bool, notify=changed)
    def busy(self):
        return self._v["state"] in ("checking", "updating", "updated")

    @pyqtProperty(bool, notify=changed)
    def canUpdate(self):
        return self._v["state"] == "available" and self._v["can_update"]
