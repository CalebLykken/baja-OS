"""The clock setup (chrony with the GPS, the RTC battery) is in the right files.

Reads the Pi setup script and chrony config as text; nothing is executed.
"""
import os
import re
import subprocess
import unittest

DEPLOY = os.path.join(os.path.dirname(__file__), "..", "deploy")
SETUP = os.path.join(DEPLOY, "setup-pi.sh")
CONF = os.path.join(DEPLOY, "chrony", "baja-gps.conf")


def read(path):
    with open(path) as f:
        return f.read()


def active_lines(text):
    return [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]


class ChronyConf(unittest.TestCase):
    def setUp(self):
        self.lines = active_lines(read(CONF))

    def test_gpsd_shared_memory_source(self):
        self.assertTrue(any(re.match(r"refclock SHM 0 .*refid GPS", l) for l in self.lines))

    def test_syncs_the_rtc(self):
        self.assertIn("rtcsync", self.lines)

    def test_leaves_debians_makestep_and_does_not_trust_the_gps(self):
        self.assertFalse(any(l.startswith("makestep") for l in self.lines))
        self.assertFalse(any(re.search(r"\btrust\b", l) for l in self.lines))

    def test_internet_sources_are_not_overridden(self):
        self.assertFalse(any(l.startswith(("pool", "server", "sourcedir")) for l in self.lines))


class SetupScript(unittest.TestCase):
    def setUp(self):
        self.text = read(SETUP)

    def test_installs_chrony_and_its_conf(self):
        self.assertRegex(self.text, r"(?m)^\s+.*\bchrony( |$)")
        self.assertIn("chrony/baja-gps.conf", self.text)
        self.assertIn("/etc/chrony/conf.d", self.text)

    def test_fake_hwclock_and_guarded_restart(self):
        self.assertRegex(self.text, r"chrony fake-hwclock")
        self.assertRegex(self.text, r"systemctl restart chrony \|\|")

    def test_rtc_charging_only_commented_out(self):
        lines = [l for l in self.text.splitlines() if "dtparam=rtc_bbat_vchg" in l]
        self.assertTrue(any("# dtparam=rtc_bbat_vchg=3000000" in l for l in lines))
        for l in lines:
            self.assertTrue(l.lstrip().startswith("#") or "'# dtparam" in l or "# dtparam" in l, l)
        self.assertNotRegex(self.text, r"(?m)^dtparam=rtc_bbat_vchg")

    def test_syntax(self):
        r = subprocess.run(["sh", "-n", SETUP], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
