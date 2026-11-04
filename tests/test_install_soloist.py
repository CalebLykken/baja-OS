"""Off-Pi tests for where the Soloist daily updater points (deploy/spotify):
install-soloist.sh must fill in the checkout's real path, so the updater
runs from any folder, paths with spaces and % included.

The installer runs on a throwaway copy of deploy/ under a temp dir, with a
fake HOME, a stub systemctl and a stub updater, so nothing real is touched.

    python3 -m unittest tests.test_install_soloist
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEPLOY = REPO / "deploy"
UNIT = "baja-soloist-update.service"

STUB_SYSTEMCTL = "#!/bin/sh\necho \"$@\" >> \"$SYSTEMCTL_LOG\"\n"


def exec_start(unit_text):
    """The ExecStart value as systemd reads it: one quoted word, C escapes, %% for %."""
    line = next(l for l in unit_text.splitlines() if l.startswith("ExecStart="))
    value = line[len("ExecStart="):]
    assert value.startswith('"') and value.endswith('"'), value
    value = re.sub(r"\\(.)", r"\1", value[1:-1])
    return value.replace("%%", "%")


class InstallSoloistTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        # A checkout in a folder with a space and a % in its name.
        self.app = root / "Baja OS 100% copy"
        shutil.copytree(DEPLOY, self.app / "deploy")
        spotify = self.app / "deploy" / "spotify"
        (spotify / "update-soloist.sh").write_text("#!/bin/sh\nexit 0\n")
        os.chmod(spotify / "update-soloist.sh", 0o755)
        self.home = root / "home"
        self.bin = root / "bin"
        self.bin.mkdir()
        self.log = root / "systemctl.log"
        (self.bin / "systemctl").write_text(STUB_SYSTEMCTL)
        os.chmod(self.bin / "systemctl", 0o755)

    def install(self):
        done = subprocess.run(
            ["sh", str(self.app / "deploy" / "spotify" / "install-soloist.sh")],
            capture_output=True, text=True,
            env={"HOME": str(self.home), "SYSTEMCTL_LOG": str(self.log),
                 "PATH": f"{self.bin}{os.pathsep}/usr/bin{os.pathsep}/bin"})
        self.assertEqual(done.returncode, 0, done.stderr)
        return (self.home / ".config" / "systemd" / "user" / UNIT).read_text()

    def test_the_updater_runs_the_script_in_this_checkout(self):
        unit = self.install()
        script = Path(exec_start(unit))
        self.assertEqual(script, self.app / "deploy" / "spotify" / "update-soloist.sh")
        self.assertTrue(script.is_file())

    def test_no_placeholder_is_left_in_the_installed_unit(self):
        self.assertNotIn("@APP@", self.install())

    def test_the_other_units_are_copied_as_they_are(self):
        self.install()
        units = self.home / ".config" / "systemd" / "user"
        self.assertEqual((units / "baja-soloist.service").read_text(),
                         (DEPLOY / "spotify" / "baja-soloist.service").read_text())
        self.assertTrue((units / "baja-soloist-update.timer").is_file())

    def test_no_unit_under_deploy_still_has_the_hard_coded_path(self):
        for path in DEPLOY.rglob("*.service"):
            self.assertNotIn("%h/baja-OS", path.read_text(), path.relative_to(REPO))


class UpdateSoloistTest(unittest.TestCase):
    """The daily updater swaps the binary but never restarts the player: the
    timer fires mid-drive and a restart would cut off Spotify Connect."""

    def test_a_new_build_is_installed_without_restarting_the_player(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build = root / "build"
            build.mkdir()
            (build / "soloist").write_text("#!/bin/sh\necho soloist-new\n")
            os.chmod(build / "soloist", 0o755)
            subprocess.run(["tar", "-czf", str(root / "soloist.tar.gz"), "-C", str(build), "soloist"],
                           check=True)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            # curl is told "-o <file>"; hand back the prebuilt archive.
            (bin_dir / "curl").write_text(
                '#!/bin/sh\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done\n'
                f'cp "{root / "soloist.tar.gz"}" "$out"\n')
            (bin_dir / "systemctl").write_text(STUB_SYSTEMCTL)
            for name in ("curl", "systemctl"):
                os.chmod(bin_dir / name, 0o755)
            log = root / "systemctl.log"
            home = root / "home"
            done = subprocess.run(
                ["sh", str(DEPLOY / "spotify" / "update-soloist.sh")],
                capture_output=True, text=True,
                env={"HOME": str(home), "SYSTEMCTL_LOG": str(log),
                     "PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin"})
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertTrue((home / ".local" / "opt" / "soloist" / "soloist").is_file())
            self.assertFalse(log.exists(), "the updater touched systemctl")

    def test_the_script_never_restarts_the_player(self):
        code = [l for l in (DEPLOY / "spotify" / "update-soloist.sh").read_text().splitlines()
                if not l.lstrip().startswith("#")]
        self.assertFalse([l for l in code if "systemctl" in l])


if __name__ == "__main__":
    unittest.main()
