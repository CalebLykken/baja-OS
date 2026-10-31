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
import time
import unittest
from pathlib import Path
from unittest import mock

from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer

from backend import updater
from backend.updater import (NOT_A_CHECKOUT, Updater, check_for_updates, driving_reason,
                             explain, update_to)

app = QCoreApplication.instance() or QCoreApplication([])


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

    def test_read_only_message(self):
        self.assertIn("read-only", explain("error: unable to create file: Read-only file system"))


class DrivingTest(unittest.TestCase):
    def test_stopped_is_fine(self):
        self.assertEqual(driving_reason(0.0, 0.0, False), "")
        self.assertEqual(driving_reason(None, None, False), "")     # simulated drive, no receiver

    def test_walking_pace_counts_as_stopped(self):
        self.assertEqual(driving_reason(2.0, 0.5, False), "")

    def test_car_speed_refuses(self):
        self.assertIn("driving", driving_reason(30.0, None, False))

    def test_gps_speed_refuses(self):
        self.assertIn("driving", driving_reason(None, 10.0, False))

    def test_routing_refuses(self):
        self.assertIn("directions", driving_reason(0.0, 0.0, True))


class Fake:
    def __init__(self, **kw):
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

    def test_restart_waits_for_the_truck_to_stop(self):
        u = self.make()
        self.push("One")
        u.check()
        wait_for(lambda: u.state == "available")
        with mock.patch.object(updater, "RESTART_DELAY_MS", 10):
            u._vehicle.speed = 0.0
            u.update()
            u._vehicle.speed = 40.0         # sets off right after Update
            wait_for(lambda: u.state == "updated")
            spin(100)
            self.assertEqual(self.restarts, [])
            u._vehicle.speed = 0.0
            wait_for(lambda: bool(self.restarts))

    def test_restart_waits_when_the_speed_goes_missing_after_moving(self):
        u = self.make()
        u._vehicle.speed = 40.0
        self.assertTrue(u._why_not_now())
        u._vehicle.live = False             # OBD silent, and no GPS fix
        self.assertTrue(u._why_not_now())
        u._vehicle.live = True
        u._vehicle.speed = 0.0              # a real reading at rest clears it
        self.assertEqual(u._why_not_now(), "")
        u._vehicle.live = False
        self.assertEqual(u._why_not_now(), "")

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


if __name__ == "__main__":
    unittest.main()
