"""Off-Pi tests for updating Baja OS from Settings (backend/updater.py), on
throwaway git repos in a tempdir: a bare "origin", the Pi's clone being
updated and a second clone that pushes new commits. Never the network or
the real repo.

    python3 -m unittest tests.test_updater
"""

import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from PyQt6.QtCore import QCoreApplication, QEventLoop, QObject, QTimer, pyqtSignal

from backend import updater
from backend.updater import (CLEAN_MARK, MARKER, NO_SPEED, NOT_A_CHECKOUT, Updater, check_for_updates,
                             confirm_healthy, driving_reason, explain, marker_notice,
                             mark_clean_exit, read_marker, update_to, write_marker)

app = QCoreApplication.instance() or QCoreApplication([])
HERE = Path(__file__).resolve().parent.parent
GUARD = HERE / "deploy" / "update-guard.sh"


def spin(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_for(cond, seconds=10):
    end = time.monotonic() + seconds
    while not cond():
        if time.monotonic() > end:
            raise AssertionError("timed out")
        spin(10)


class Repos(unittest.TestCase):
    """origin (bare), the Pi's clone and a second clone to push from."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="baja-updater-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        home = self.tmp / "home"
        home.mkdir()
        # None of the user's own git settings in here.
        p = mock.patch.dict(os.environ, {"HOME": str(home), "XDG_CONFIG_HOME": str(home)})
        p.start()
        self.addCleanup(p.stop)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        self.origin, self.mac, self.pi = self.tmp / "origin.git", self.tmp / "mac", self.tmp / "pi"
        self.git(self.tmp, "init", "-q", "--bare", "-b", "main", "origin.git")
        self.git(self.tmp, "clone", "-q", "origin.git", "mac")
        self.git(self.mac, "symbolic-ref", "HEAD", "refs/heads/main")
        self.commit(self.mac, "First")
        self.git(self.mac, "push", "-q", "-u", "origin", "main")
        self.git(self.tmp, "clone", "-q", "origin.git", "pi")

    def git(self, repo, *args):
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                           env=self.env)
        if p.returncode:
            raise AssertionError(f"git {' '.join(args)}: {p.stderr}")
        return p.stdout.strip()

    def commit(self, repo, subject, name="app.py"):
        (repo / name).write_text(subject + "\n")
        self.git(repo, "add", name)
        self.git(repo, "commit", "-q", "-m", subject)

    def push(self, *subjects):
        for s in subjects:
            self.commit(self.mac, s)
        self.git(self.mac, "push", "-q")
        return self.git(self.mac, "rev-parse", "HEAD")

    def head(self):
        return self.git(self.pi, "rev-parse", "HEAD")


class CheckTest(Repos):
    def test_up_to_date(self):
        r = check_for_updates(self.pi)
        self.assertEqual((r["state"], r["message"], r["can_update"]), ("current", "Up to date.", False))

    def test_available_lists_newest_first(self):
        before = self.head()
        target = self.push("One", "Two", "Three")
        r = check_for_updates(self.pi)
        self.assertEqual(r["state"], "available")
        self.assertTrue(r["can_update"])
        self.assertEqual(r["commits"], ["Three", "Two", "One"])
        self.assertEqual((r["count"], r["target"]), (3, target))
        self.assertEqual(self.head(), before)       # a check moves nothing

    def test_list_is_capped_but_counted(self):
        self.push("One", "Two", "Three")
        with mock.patch.object(updater, "MAX_LISTED", 2):
            r = check_for_updates(self.pi)
        self.assertEqual((r["commits"], r["count"]), (["Three", "Two"], 3))

    def test_dirty_tree_is_refused(self):
        self.push("One")
        (self.pi / "app.py").write_text("edited here\n")
        r = check_for_updates(self.pi)
        self.assertEqual(r["state"], "available")
        self.assertFalse(r["can_update"])
        self.assertIn("app.py", r["message"])

    def test_untracked_files_do_not_block(self):
        self.push("One")
        (self.pi / "notes.txt").write_text("x\n")
        self.assertTrue(check_for_updates(self.pi)["can_update"])

    def test_local_commits_are_refused(self):
        self.push("One")
        self.commit(self.pi, "Mine", name="mine.py")
        r = check_for_updates(self.pi)
        self.assertFalse(r["can_update"])
        self.assertIn("1 commit of its own", r["message"])

    def test_no_git_dir(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        r = check_for_updates(plain)
        self.assertEqual((r["state"], r["message"]), ("failed", NOT_A_CHECKOUT))

    def test_fetch_from_a_deleted_origin_fails_clearly(self):
        shutil.rmtree(self.origin)
        r = check_for_updates(self.pi)
        self.assertEqual(r["state"], "failed")
        self.assertFalse(r["can_update"])
        self.assertTrue(r["message"])

    def test_no_upstream(self):
        self.git(self.pi, "branch", "--unset-upstream")
        r = check_for_updates(self.pi)
        self.assertEqual(r["state"], "failed")
        self.assertIn("doesn't follow", r["message"])

    def test_stalled_fetch_is_stopped(self):
        # A "remote" that never answers: the fetch must be cut off, not hang.
        self.git(self.pi, "config", "core.sshCommand", "sleep 30; false")
        self.git(self.pi, "remote", "set-url", "origin", "ssh://nowhere/x.git")
        with mock.patch.object(updater, "FETCH_TIMEOUT_S", 1), \
                mock.patch.object(updater, "STOP_WAIT_S", 2):
            start = time.monotonic()
            r = check_for_updates(self.pi)
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual(r["state"], "failed")
        self.assertIn("too long", r["message"])


class UpdateTest(Repos):
    def test_fast_forward(self):
        target = self.push("One", "Two")
        check_for_updates(self.pi)                  # fetches it, as the Check key does
        r = update_to(self.pi, target)
        self.assertEqual(r["state"], "updated")
        self.assertEqual(self.head(), target)
        self.assertEqual((self.pi / "app.py").read_text(), "Two\n")

    def test_already_there(self):
        self.assertEqual(update_to(self.pi, self.head())["state"], "current")

    def test_refuses_dirty_tree_and_changes_nothing(self):
        before = self.head()
        self.push("One")
        check_for_updates(self.pi)
        (self.pi / "app.py").write_text("edited here\n")
        r = update_to(self.pi, self.git(self.pi, "rev-parse", "@{u}"))
        self.assertEqual(r["state"], "failed")
        self.assertEqual(self.head(), before)

    def test_refuses_local_commits(self):
        self.push("One")
        check_for_updates(self.pi)
        self.commit(self.pi, "Mine", name="mine.py")
        mine = self.head()
        r = update_to(self.pi, self.git(self.pi, "rev-parse", "@{u}"))
        self.assertEqual(r["state"], "failed")
        self.assertEqual(self.head(), mine)

    def test_stays_on_the_checked_target(self):
        # Commits pushed after the check aren't pulled in by Update.
        target = self.push("One")
        check_for_updates(self.pi)
        self.push("Two")
        self.assertEqual(update_to(self.pi, target)["state"], "updated")
        self.assertEqual(self.head(), target)

    def test_a_failed_merge_puts_the_tree_back_and_can_be_retried(self):
        # The merge writes top.py, then can't write into a read-only folder.
        (self.mac / "sub").mkdir()
        (self.mac / "sub" / "x.py").write_text("old\n")
        self.git(self.mac, "add", "sub")
        self.git(self.mac, "commit", "-q", "-m", "Folder")
        self.git(self.mac, "push", "-q")
        check_for_updates(self.pi)
        update_to(self.pi, self.git(self.pi, "rev-parse", "@{u}"))
        before = self.head()
        (self.mac / "sub" / "x.py").write_text("new\n")
        (self.mac / "top.py").write_text("new\n")
        (self.mac / "z.py").write_text("new\n")
        self.git(self.mac, "add", ".")
        self.git(self.mac, "commit", "-q", "-m", "Both")
        self.git(self.mac, "push", "-q")
        target = self.git(self.mac, "rev-parse", "HEAD")
        check_for_updates(self.pi)
        (self.pi / "sub").chmod(0o555)
        self.addCleanup((self.pi / "sub").chmod, 0o755)

        r = update_to(self.pi, target)

        self.assertEqual(r["state"], "failed")
        self.assertIn("put back", r["message"])
        self.assertEqual(self.head(), before)
        self.assertEqual(self.git(self.pi, "status", "--porcelain", "--untracked-files=no"), "")
        self.assertFalse((self.pi / "top.py").exists())
        self.assertEqual(read_marker(self.pi), {})
        (self.pi / "sub").chmod(0o755)
        self.assertEqual(update_to(self.pi, target)["state"], "updated")   # not "local changes"

    def test_a_file_of_yours_in_the_way_is_not_touched(self):
        (self.mac / "new.py").write_text("theirs\n")
        self.git(self.mac, "add", "new.py")
        self.git(self.mac, "commit", "-q", "-m", "New")
        self.git(self.mac, "push", "-q")
        target = self.git(self.mac, "rev-parse", "HEAD")
        check_for_updates(self.pi)
        (self.pi / "new.py").write_text("mine\n")
        r = update_to(self.pi, target)
        self.assertEqual(r["state"], "failed")
        self.assertIn("in the way", r["message"])
        self.assertEqual((self.pi / "new.py").read_text(), "mine\n")
        self.assertEqual(read_marker(self.pi), {})

    def test_if_putting_back_fails_the_marker_stays_for_the_next_start(self):
        target = self.push("One")
        check_for_updates(self.pi)
        real = updater.git

        def broken(root, *args, **kw):
            if args[0] in ("merge", "reset"):
                raise updater.GitError("No.")
            return real(root, *args, **kw)
        with mock.patch.object(updater, "git", broken):
            r = update_to(self.pi, target)
        self.assertEqual(r["state"], "failed")
        self.assertIn("next start", r["message"])
        self.assertEqual(read_marker(self.pi)["phase"], "merging")

    def test_a_slow_rev_parse_after_the_merge_still_counts_as_updated(self):
        target = self.push("One")
        check_for_updates(self.pi)
        real = updater.git
        heads = []

        def slow(root, *args, **kw):
            if args[:2] == ("rev-parse", "HEAD"):
                heads.append(1)
                if len(heads) == 2:
                    raise updater.GitError("Git took more than 20 s.")
            return real(root, *args, **kw)
        with mock.patch.object(updater, "git", slow):
            r = update_to(self.pi, target)
        self.assertEqual(r["state"], "updated")
        self.assertIn(target[:7], r["message"])
        self.assertEqual(read_marker(self.pi)["target"], target)

    def test_the_marker_is_written_before_the_merge(self):
        target = self.push("One")
        before = self.head()
        check_for_updates(self.pi)
        real = updater.git
        seen = []

        def spy(root, *args, **kw):
            if args[0] == "merge":
                seen.append(read_marker(root))
            return real(root, *args, **kw)
        with mock.patch.object(updater, "git", spy):
            update_to(self.pi, target)
        self.assertEqual((seen[0]["phase"], seen[0]["before"]), ("merging", before))
        m = read_marker(self.pi)
        self.assertEqual((m["phase"], m["before"], m["target"], m["starts"]),
                         ("pending", before, target, "0"))

    def test_a_truck_that_moved_before_the_merge_leaves_the_files_alone(self):
        before = self.head()
        target = self.push("One")
        check_for_updates(self.pi)
        seen = []

        def why_not():
            seen.append(read_marker(self.pi)["phase"])
            return "Not while driving: stop the truck first."
        r = update_to(self.pi, target, why_not)
        self.assertEqual(r["state"], "deferred")
        self.assertFalse(r["can_update"])
        self.assertEqual(seen, ["merging"])         # asked with the marker down, right before the merge
        self.assertEqual(self.head(), before)
        self.assertEqual((self.pi / "app.py").read_text(), "First\n")
        m = read_marker(self.pi)
        self.assertEqual((m["phase"], m["before"], m["target"]), ("deferred", before, target))
        # Nothing in the way of trying again.
        self.assertTrue(check_for_updates(self.pi)["can_update"])
        self.assertEqual(update_to(self.pi, target, lambda: "")["state"], "updated")
        self.assertEqual(read_marker(self.pi)["phase"], "pending")

    def test_nothing_to_do_leaves_no_marker(self):
        update_to(self.pi, self.head())
        self.assertEqual(read_marker(self.pi), {})

    def test_the_marker_does_not_count_as_a_change(self):
        self.push("One")
        write_marker(self.pi, "fell-back", self.head(), "abc")
        self.assertEqual(self.git(self.pi, "rev-parse", "HEAD"), self.head())
        self.assertTrue(check_for_updates(self.pi)["can_update"])

    def test_read_only_message(self):
        self.assertIn("read-only", explain("error: unable to create file: Read-only file system"))


class DrivingTest(unittest.TestCase):
    def test_stopped_is_fine(self):
        self.assertEqual(driving_reason(0.0, 0.0, False), "")

    def test_no_speed_is_not_known_to_be_stopped(self):
        self.assertEqual(driving_reason(None, None, False), NO_SPEED)

    def test_a_lost_speed_keeps_what_it_last_said(self):
        self.assertIn("driving", driving_reason(None, None, False, was_moving=True, ever_known=True))
        self.assertEqual(driving_reason(None, None, False, ever_known=True), "")

    def test_walking_pace_counts_as_stopped(self):
        self.assertEqual(driving_reason(2.0, 0.5, False), "")

    def test_car_speed_refuses(self):
        self.assertIn("driving", driving_reason(30.0, None, False))

    def test_gps_speed_refuses(self):
        self.assertIn("driving", driving_reason(None, 10.0, False))

    def test_routing_refuses(self):
        self.assertIn("directions", driving_reason(0.0, 0.0, True))


class Fake(QObject):
    changed = pyqtSignal()

    def __init__(self, **kw):
        super().__init__()
        self.__dict__.update(kw)


class UpdaterTest(Repos):
    def make(self, **kw):
        veh = Fake(live=kw.get("live", True), speed=kw.get("mph", 0.0))
        gps = Fake(realFix=False, speed=0.0)
        routing = Fake(active=kw.get("guiding", False))
        self.restarts = []
        return Updater(veh, gps, routing, lambda: self.restarts.append(1), root=self.pi)

    def test_check_then_update_restarts(self):
        u = self.make()
        target = self.push("One")
        u.check()
        wait_for(lambda: u.state == "available")
        self.assertEqual(list(u.commits), ["One"])
        self.assertTrue(u.canUpdate)
        with mock.patch.object(updater, "RESTART_DELAY_MS", 10):
            u.update()
            wait_for(lambda: bool(self.restarts))
        self.assertEqual(u.state, "updated")
        self.assertEqual(self.head(), target)

    def test_update_refused_while_driving(self):
        u = self.make(mph=40.0)
        before = self.head()
        self.push("One")
        u.check()
        wait_for(lambda: u.state == "available")
        u.update()
        self.assertEqual(u.state, "available")
        self.assertIn("driving", u.message)
        self.assertEqual(self.head(), before)

    def test_update_refused_while_guiding(self):
        u = self.make(guiding=True)
        self.push("One")
        u.check()
        wait_for(lambda: u.state == "available")
        u.update()
        self.assertIn("directions", u.message)

    def test_moving_before_the_merge_defers_it_to_the_next_start(self):
        # The truck sets off between Update being pressed and the merge:
        # no new file may land under the running process.
        u = self.make()
        before = self.head()
        target = self.push("One")
        u.check()
        wait_for(lambda: u.state == "available")
        gate = threading.Event()
        real = updater.update_to

        def held(root, t, why_not):
            gate.wait(10)
            return real(root, t, why_not)
        with mock.patch.object(updater, "RESTART_DELAY_MS", 10), \
                mock.patch.object(updater, "RESTART_SETTLE_MS", 10), \
                mock.patch.object(updater, "update_to", held):
            u.update()
            self.assertTrue(u.updating)
            u._vehicle.speed = 40.0
            u._vehicle.changed.emit()
            gate.set()
            wait_for(lambda: u.state == "deferred")
            u._vehicle.speed = 0.0                  # a red light, after the fact
            u._vehicle.changed.emit()
            spin(100)
        self.assertEqual(self.restarts, [])
        self.assertEqual(self.head(), before)
        self.assertEqual((self.pi / "app.py").read_text(), "First\n")
        self.assertIn("next time the dashboard starts", u.message)
        self.assertEqual(read_marker(self.pi)["phase"], "deferred")
        self.assertEqual(read_marker(self.pi)["target"], target)
        self.assertFalse(u.busy)
        self.assertFalse(u.updating)

    def test_directions_starting_before_the_merge_defer_it_too(self):
        u = self.make()
        before = self.head()
        self.push("One")
        u.check()
        wait_for(lambda: u.state == "available")
        gate = threading.Event()
        real = updater.update_to

        def held(root, t, why_not):
            gate.wait(10)
            return real(root, t, why_not)
        with mock.patch.object(updater, "update_to", held):
            u.update()
            u._routing.active = True
            gate.set()
            wait_for(lambda: u.state == "deferred")
        self.assertEqual(self.head(), before)

    def test_a_truck_that_stays_stopped_is_merged_and_restarted_at_once(self):
        u = self.make()
        target = self.push("One")
        u.check()
        wait_for(lambda: u.state == "available")
        start = time.monotonic()
        u.update()
        wait_for(lambda: bool(self.restarts))
        self.assertLess(time.monotonic() - start, updater.RESTART_DELAY_MS / 1000)
        self.assertEqual(self.head(), target)

    def test_moving_after_the_update_waits_for_the_next_boot(self):
        # Moving after the merge (it was in before this could be known) still
        # never restarts; the merge itself is stubbed so the timing is fixed.
        u = self.make()
        self.push("One")
        u.check()
        wait_for(lambda: u.state == "available")
        with mock.patch.object(updater, "RESTART_DELAY_MS", 10), \
                mock.patch.object(updater, "RESTART_SETTLE_MS", 10), \
                mock.patch.object(updater, "update_to", lambda r, t, w: updater._result("updated", "x")):
            u.update()
            u._vehicle.speed = 40.0         # sets off right after Update
            u._vehicle.changed.emit()
            wait_for(lambda: u.state == "updated")
            u._vehicle.speed = 0.0          # a red light
            u._vehicle.changed.emit()
            wait_for(lambda: "next time" in u.message)
            spin(100)
        self.assertEqual(self.restarts, [])

    def test_restart_waits_for_directions_to_end(self):
        u = self.make()
        self.push("One")
        u.check()
        wait_for(lambda: u.state == "available")
        with mock.patch.object(updater, "RESTART_DELAY_MS", 10), \
                mock.patch.object(updater, "RESTART_SETTLE_MS", 10), \
                mock.patch.object(updater, "update_to", lambda r, t, w: updater._result("updated", "x")):
            u.update()
            u._routing.active = True
            wait_for(lambda: u.state == "updated")
            spin(60)
            self.assertEqual(self.restarts, [])
            u._routing.active = False
            wait_for(lambda: bool(self.restarts))

    def test_moving_is_followed_without_being_asked(self):
        u = self.make()
        u._vehicle.speed = 40.0
        u._vehicle.changed.emit()
        u._vehicle.live = False             # OBD silent, and no GPS fix, unasked till now
        self.assertIn("driving", u._why_not_now())
        u._vehicle.live = True
        u._vehicle.speed = 0.0              # a real reading at rest clears it
        u._vehicle.changed.emit()
        u._vehicle.live = False
        self.assertEqual(u._why_not_now(), "")

    def test_the_gps_counts_too(self):
        u = self.make(live=False)
        u._gps.realFix, u._gps.speed = True, 20.0
        u._gps.changed.emit()
        u._gps.realFix = False
        self.assertIn("driving", u._why_not_now())

    def test_directions_do_not_hide_moving(self):
        u = self.make(guiding=True, mph=40.0)
        self.assertIn("directions", u._why_not_now())
        u._routing.active = False
        u._vehicle.live = False
        self.assertIn("driving", u._why_not_now())

    def test_never_a_speed_refuses_and_says_so(self):
        u = self.make(live=False)
        before = self.head()
        self.push("One")
        u.check()
        wait_for(lambda: u.state == "available")
        u.update()
        self.assertEqual(u.message, NO_SPEED)
        self.assertEqual(self.head(), before)

    def test_updating_only_while_the_merge_runs(self):
        u = self.make()
        self.assertFalse(u.updating)
        self.push("One")
        u.check()
        wait_for(lambda: u.state == "available")
        self.assertFalse(u.updating)
        with mock.patch.object(updater, "RESTART_DELAY_MS", 10), \
                mock.patch.object(updater, "update_to", lambda r, t, w: updater._result("updated", "x")):
            u.update()
            self.assertTrue(u.updating)
            wait_for(lambda: u.state == "updated")
        self.assertFalse(u.updating)
        wait_for(lambda: bool(self.restarts))

    def test_start_shows_what_was_taken_back_until_ok(self):
        write_marker(self.pi, "fell-back", "a" * 40, "b" * 40)
        u = self.make()
        with mock.patch.object(updater, "HEALTHY_AFTER_MS", 10):
            u.start()
            self.assertIn("went back to aaaaaaa", u.notice)
            spin(40)
        self.assertIn("aaaaaaa", u.notice)          # still up, marker kept
        self.assertTrue((self.pi / MARKER).exists())
        u.dismissNotice()
        self.assertEqual(u.notice, "")
        self.assertFalse((self.pi / MARKER).exists())

    def test_start_confirms_a_new_version_only_after_a_while(self):
        write_marker(self.pi, "pending", "a" * 40, "b" * 40)
        (self.pi / MARKER).write_text((self.pi / MARKER).read_text().replace("starts 0", "starts 1"))
        u = self.make()
        with mock.patch.object(updater, "HEALTHY_AFTER_MS", 30):
            u.start()
            self.assertTrue((self.pi / MARKER).exists())
            wait_for(lambda: not (self.pi / MARKER).exists())

    def test_an_update_waiting_for_its_restart_is_not_confirmed(self):
        # Updated within the first minute of a run: the timer from that
        # run's start must not vouch for code that hasn't run yet.
        write_marker(self.pi, "pending", "a" * 40, "b" * 40)
        self.assertFalse(confirm_healthy(self.pi))
        self.assertTrue((self.pi / MARKER).exists())

    def test_a_missing_tracking_ref_is_fetched_back(self):
        subprocess.run(["git", "-C", str(self.pi), "update-ref", "-d", "refs/remotes/origin/main"],
                       check=True, capture_output=True)
        u = self.make()
        self.push("One")
        u.check()
        wait_for(lambda: u.state == "available")

    def test_update_does_nothing_unchecked(self):
        u = self.make()
        u.update()
        self.assertEqual(u.state, "idle")


class GuardTest(Repos):
    """deploy/update-guard.sh on its own, and through a real run.sh."""

    def guard(self):
        return subprocess.run(["sh", str(GUARD)], cwd=self.pi, env=self.env,
                              capture_output=True, text=True).returncode

    def updated(self):
        """The Pi on a new commit, waiting for its restart. Returns (old, new)."""
        before = self.head()
        target = self.push("One")
        check_for_updates(self.pi)
        self.assertEqual(update_to(self.pi, target)["state"], "updated")
        return before, target

    def test_no_marker_does_nothing(self):
        self.assertEqual(self.guard(), 0)

    def test_starts_are_counted_then_it_falls_back(self):
        before, target = self.updated()
        for n in ("1", "2", "3"):
            self.assertEqual(self.guard(), 0)
            self.assertEqual(read_marker(self.pi)["starts"], n)
            self.assertEqual(self.head(), target)
        self.assertEqual(self.guard(), 75)
        self.assertEqual(self.head(), before)
        self.assertEqual((self.pi / "app.py").read_text(), "First\n")
        self.assertEqual(read_marker(self.pi)["phase"], "fell-back")
        self.assertIn(before[:7], marker_notice(self.pi))
        self.assertEqual(self.guard(), 0)           # once only
        self.assertTrue(check_for_updates(self.pi)["can_update"])   # may be tried again

    def test_confirmed_version_is_left_alone(self):
        _, target = self.updated()
        self.guard()
        self.assertTrue(confirm_healthy(self.pi))
        for _ in range(5):
            self.assertEqual(self.guard(), 0)
        self.assertEqual(self.head(), target)

    def test_short_clean_trips_never_add_up_to_a_fall_back(self):
        _, target = self.updated()
        for _ in range(10):                         # key on, 25 s, key off
            self.assertEqual(self.guard(), 0)
            mark_clean_exit(self.pi)
        self.assertEqual(self.head(), target)
        self.assertEqual(read_marker(self.pi)["phase"], "pending")
        self.assertEqual(read_marker(self.pi)["starts"], "1")

    def test_the_first_start_of_a_new_version_always_counts(self):
        self.updated()
        (self.pi / CLEAN_MARK).write_text("")       # left by the old version's last run
        self.assertEqual(self.guard(), 0)
        self.assertEqual(read_marker(self.pi)["starts"], "1")

    def test_crashes_still_fall_back_among_clean_trips(self):
        before, target = self.updated()
        self.guard()                                # 1, crashes
        self.guard()                                # 2, crashes
        self.guard()                                # 3, ends cleanly
        mark_clean_exit(self.pi)
        self.assertEqual(self.guard(), 0)           # not counted: still 3
        self.assertEqual(read_marker(self.pi)["starts"], "3")
        self.assertEqual(self.guard(), 75)          # that run crashed
        self.assertEqual(self.head(), before)

    def test_a_clean_end_is_only_marked_for_a_version_on_trial(self):
        mark_clean_exit(self.pi)
        self.assertFalse((self.pi / CLEAN_MARK).exists())
        self.updated()
        mark_clean_exit(self.pi)
        self.assertTrue((self.pi / CLEAN_MARK).exists())

    def test_the_mark_is_used_up_by_one_start(self):
        self.updated()
        self.guard()
        mark_clean_exit(self.pi)
        self.guard()
        self.assertFalse((self.pi / CLEAN_MARK).exists())
        self.guard()
        self.assertEqual(read_marker(self.pi)["starts"], "2")

    def test_head_moved_by_hand_is_left_alone(self):
        _, target = self.updated()
        for _ in range(3):
            self.guard()
        self.commit(self.pi, "Fixed over SSH", name="fix.py")
        fixed = self.head()
        self.assertEqual(self.guard(), 0)
        self.assertEqual(self.head(), fixed)
        self.assertFalse((self.pi / MARKER).exists())

    def cut_off(self):
        """A merge killed halfway: some new files, HEAD old, a lock left."""
        before = self.head()
        (self.mac / "new.py").write_text("x\n")
        self.git(self.mac, "add", "new.py")
        target = self.push("One")
        check_for_updates(self.pi)
        write_marker(self.pi, "merging", before, target)
        (self.pi / "app.py").write_text("half writ")
        (self.pi / "new.py").write_text("x\n")
        (self.pi / ".git" / "index.lock").write_text("")
        return before, target

    def test_a_cut_off_merge_is_put_back(self):
        before, target = self.cut_off()
        self.assertEqual(self.guard(), 75)
        self.assertEqual(self.head(), before)
        self.assertEqual((self.pi / "app.py").read_text(), "First\n")
        self.assertEqual(self.git(self.pi, "status", "--porcelain", "--untracked-files=no"), "")
        self.assertFalse((self.pi / ".git" / "index.lock").exists())
        self.assertEqual(read_marker(self.pi)["phase"], "cut-off")
        self.assertIn("cut off", marker_notice(self.pi))
        self.assertFalse((self.pi / "new.py").exists())     # or it's "in the way" next time
        self.assertEqual(update_to(self.pi, target)["state"], "updated")

    def test_a_broken_index_is_rebuilt(self):
        before, _ = self.cut_off()
        (self.pi / ".git" / "index").write_bytes(b"not an index")
        self.assertEqual(self.guard(), 75)
        self.assertEqual(self.head(), before)
        self.assertEqual(self.git(self.pi, "status", "--porcelain", "--untracked-files=no"), "")

    def test_a_merge_that_never_began_ends_the_same(self):
        before = self.head()
        write_marker(self.pi, "merging", before, "c" * 40)
        self.assertEqual(self.guard(), 75)
        self.assertEqual(self.head(), before)

    def test_merge_finished_but_never_confirmed_goes_back_too(self):
        before = self.head()
        target = self.push("One")
        check_for_updates(self.pi)
        write_marker(self.pi, "merging", before, target)
        self.git(self.pi, "merge", "-q", "--ff-only", target)
        self.assertEqual(self.guard(), 75)
        self.assertEqual(self.head(), before)

    def deferred(self):
        """An update the truck's moving kept from being merged. Returns (old, new)."""
        before = self.head()
        target = self.push("One")
        check_for_updates(self.pi)
        self.assertEqual(update_to(self.pi, target, lambda: "Not while driving.")["state"], "deferred")
        return before, target

    def test_a_deferred_update_is_merged_at_the_next_start(self):
        before, target = self.deferred()
        self.assertEqual(self.head(), before)
        self.assertEqual(self.guard(), 75)          # run.sh starts over on the new code
        self.assertEqual(self.head(), target)
        self.assertEqual((self.pi / "app.py").read_text(), "One\n")
        m = read_marker(self.pi)
        self.assertEqual((m["phase"], m["before"], m["target"], m["starts"]),
                         ("pending", before, target, "0"))
        self.assertEqual(self.guard(), 0)           # then it's an ordinary new version
        self.assertEqual(read_marker(self.pi)["starts"], "1")
        self.assertTrue(confirm_healthy(self.pi))
        self.assertEqual(self.guard(), 0)

    def test_a_deferred_update_that_never_comes_up_falls_back(self):
        before, target = self.deferred()
        self.assertEqual(self.guard(), 75)
        codes = [self.guard() for _ in range(3)]
        self.assertEqual(codes, [0, 0, 0])
        self.assertEqual(self.guard(), 75)
        self.assertEqual(self.head(), before)
        self.assertEqual(read_marker(self.pi)["phase"], "fell-back")

    def test_a_deferred_update_is_not_confirmed_by_the_dashboard(self):
        self.deferred()
        self.assertFalse(confirm_healthy(self.pi))
        self.assertEqual(marker_notice(self.pi), "")
        self.assertEqual(read_marker(self.pi)["phase"], "deferred")

    def test_a_deferred_update_is_dropped_if_the_code_was_changed_since(self):
        _, target = self.deferred()
        self.commit(self.pi, "Fixed over SSH", name="fix.py")
        fixed = self.head()
        self.assertEqual(self.guard(), 0)
        self.assertEqual(self.head(), fixed)
        self.assertFalse((self.pi / MARKER).exists())

    def test_a_deferred_update_is_dropped_if_tracked_files_are_changed(self):
        before, _ = self.deferred()
        (self.pi / "app.py").write_text("mine\n")
        self.assertEqual(self.guard(), 0)
        self.assertEqual(self.head(), before)
        self.assertEqual((self.pi / "app.py").read_text(), "mine\n")
        self.assertFalse((self.pi / MARKER).exists())

    def test_a_deferred_update_whose_commit_is_gone_is_dropped(self):
        before = self.head()
        write_marker(self.pi, "deferred", before, "c" * 40)
        self.assertEqual(self.guard(), 0)
        self.assertEqual(self.head(), before)
        self.assertFalse((self.pi / MARKER).exists())

    def test_a_file_in_the_way_of_a_deferred_update_is_left_alone(self):
        before = self.head()
        (self.mac / "new.py").write_text("theirs\n")
        self.git(self.mac, "add", "new.py")
        target = self.push("One")
        check_for_updates(self.pi)
        self.assertEqual(update_to(self.pi, target, lambda: "Not while driving.")["state"], "deferred")
        (self.pi / "new.py").write_text("mine\n")          # untracked, so not a "change"
        self.assertEqual(self.guard(), 0)
        self.assertEqual(self.head(), before)
        self.assertEqual((self.pi / "new.py").read_text(), "mine\n")
        self.assertFalse((self.pi / MARKER).exists())

    def test_a_deferred_update_is_merged_through_run_sh(self):
        for src, name in ((HERE / "run.sh", "run.sh"), (GUARD, "deploy/update-guard.sh")):
            (self.mac / name).parent.mkdir(exist_ok=True)
            shutil.copy(src, self.mac / name)
        (self.mac / "main.py").write_text("print('old')\n")
        (self.mac / ".gitignore").write_text(".update-state*\n")
        self.git(self.mac, "add", ".")
        self.git(self.mac, "commit", "-q", "-m", "Good")
        self.git(self.mac, "push", "-q")
        self.git(self.pi, "pull", "-q")
        (self.mac / "main.py").write_text("print('new')\n")
        self.git(self.mac, "add", ".")
        self.git(self.mac, "commit", "-q", "-m", "Newer")
        self.git(self.mac, "push", "-q")
        target = self.git(self.mac, "rev-parse", "HEAD")
        check_for_updates(self.pi)
        self.assertEqual(update_to(self.pi, target, lambda: "Not while driving.")["state"], "deferred")
        self.assertEqual((self.pi / "main.py").read_text(), "print('old')\n")

        first = self.run_sh()                       # merged before any Python, same start
        self.assertEqual((first.returncode, first.stdout.strip()), (0, "new"))
        self.assertEqual(self.head(), target)
        self.assertEqual(read_marker(self.pi)["phase"], "pending")
        self.assertEqual(read_marker(self.pi)["starts"], "1")

    def test_a_marker_with_no_commit_is_dropped(self):
        write_marker(self.pi, "merging", "nonsense", "x")
        self.assertEqual(self.guard(), 0)
        self.assertFalse((self.pi / MARKER).exists())
        (self.pi / MARKER).write_bytes(b"\xff\x00junk")
        self.assertEqual(self.guard(), 0)

    def test_a_renamed_file_isnt_left_in_the_way(self):
        before = self.head()
        self.git(self.mac, "mv", "app.py", "moved.py")
        target = self.push("One")
        check_for_updates(self.pi)
        write_marker(self.pi, "merging", before, target)
        (self.pi / "moved.py").write_text("First\n")
        self.assertEqual(self.guard(), 75)
        self.assertFalse((self.pi / "moved.py").exists())
        self.assertEqual(update_to(self.pi, target)["state"], "updated")

    def test_a_marker_that_cant_be_saved_still_ends_in_a_start(self):
        before, target = self.cut_off()
        (self.pi / (MARKER + ".new")).mkdir()
        self.assertEqual(self.guard(), 0)
        self.assertEqual(self.head(), before)

    def test_a_guard_that_keeps_asking_for_a_restart_cant_stop_the_start(self):
        (self.pi / "deploy").mkdir(exist_ok=True)
        shutil.copy(HERE / "run.sh", self.pi / "run.sh")
        (self.pi / "deploy" / "update-guard.sh").write_text("exit 75\n")
        (self.pi / "main.py").write_text("print('started')\n")
        env = dict(self.env, QT_QPA_PLATFORM="offscreen", QT_QPA_EGLFS_KMS_CONFIG="x")
        done = subprocess.run(["./run.sh"], cwd=self.pi, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "started"))

    def run_sh(self):
        env = dict(self.env, QT_QPA_PLATFORM="offscreen", QT_QPA_EGLFS_KMS_CONFIG="x")
        return subprocess.run(["./run.sh"], cwd=self.pi, env=env, capture_output=True, text=True)

    def test_a_commit_that_crashes_at_startup_falls_back_through_run_sh(self):
        # The real run.sh and guard in the throwaway repo; main.py just says
        # which version it is.
        for src, name in ((HERE / "run.sh", "run.sh"), (GUARD, "deploy/update-guard.sh")):
            (self.mac / name).parent.mkdir(exist_ok=True)
            shutil.copy(src, self.mac / name)
        (self.mac / "main.py").write_text("print('old')\n")
        (self.mac / ".gitignore").write_text(".update-state*\n")
        self.git(self.mac, "add", ".")
        self.git(self.mac, "commit", "-q", "-m", "Good")
        self.git(self.mac, "push", "-q")
        self.git(self.pi, "pull", "-q")
        good = self.head()
        (self.mac / "main.py").write_text("raise SystemExit(1)\n")
        self.git(self.mac, "add", ".")
        self.git(self.mac, "commit", "-q", "-m", "Bad")
        self.git(self.mac, "push", "-q")
        bad = self.git(self.mac, "rev-parse", "HEAD")
        check_for_updates(self.pi)
        self.assertEqual(update_to(self.pi, bad)["state"], "updated")

        codes = [self.run_sh().returncode for _ in range(3)]
        self.assertEqual(codes, [1, 1, 1])
        self.assertEqual(self.head(), bad)
        last = self.run_sh()                        # the fourth: the old code, this same start
        self.assertEqual((last.returncode, last.stdout.strip()), (0, "old"))
        self.assertEqual(self.head(), good)
        self.assertEqual(read_marker(self.pi)["phase"], "fell-back")


if __name__ == "__main__":
    unittest.main()
