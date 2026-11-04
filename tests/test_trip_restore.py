"""Off-Pi tests for carrying the trip across a dashboard restart: the saved
numbers come back in the same boot only, and a restored trip does not fire
the milestones it already passed. The QML half runs in a subprocess because
other test modules hold a QCoreApplication.

    python3 -m unittest tests.test_trip_restore
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

try:
    import PyQt6.QtQml  # noqa: F401
except ImportError:
    raise unittest.SkipTest("PyQt6 isn't installed")

from backend.trip import TripStore, saved_trip, trip_record

ROOT = Path(__file__).resolve().parent.parent
MI = 1609.344


class SavedTripTest(unittest.TestCase):
    def record(self, boot="boot-a", up=1000.0, peak=7.5):
        return trip_record(40 * MI, 3000, 3600, peak, boot, up)

    def test_same_boot_restores_the_numbers(self):
        r = saved_trip(self.record(), "boot-a", 1000.0)
        self.assertAlmostEqual(r["metres"], 40 * MI)
        self.assertEqual(r["movingSeconds"], 3000)
        self.assertEqual(r["runningSeconds"], 3600)
        self.assertEqual(r["peakBoost"], 7.5)

    def test_the_time_the_dashboard_was_down_counts_as_running(self):
        r = saved_trip(self.record(up=1000.0), "boot-a", 1012.0)
        self.assertEqual(r["runningSeconds"], 3612)
        self.assertEqual(r["movingSeconds"], 3000)

    def test_a_new_boot_starts_fresh(self):
        self.assertIsNone(saved_trip(self.record(boot="boot-a"), "boot-b", 5.0))

    def test_no_boot_id_never_restores(self):
        self.assertIsNone(saved_trip(self.record(boot=""), "", 1000.0))

    def test_no_peak_boost_is_kept_as_unknown(self):
        self.assertIsNone(saved_trip(self.record(peak=float("-inf")), "boot-a", 1000.0)["peakBoost"])

    def test_junk_starts_fresh(self):
        for text in ("", "nonsense", "[]", "{}", '{"boot": "boot-a"}',
                     json.dumps({"boot": "boot-a", "metres": -1, "moving": 0, "running": 0, "up": 0}),
                     json.dumps({"boot": "boot-a", "metres": "x", "moving": 0, "running": 0, "up": 0})):
            self.assertIsNone(saved_trip(text, "boot-a", 10.0), text)


class FakeSettings:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class TripStoreTest(unittest.TestCase):
    def test_save_then_restore_in_the_same_boot(self):
        from unittest import mock
        settings = FakeSettings()
        with mock.patch("backend.trip.boot_id", lambda: "boot-a"):
            store = TripStore(settings)
            self.assertEqual(store.restore(), {})
            store.save(1234.5, 200, 300, float("-inf"))
            r = store.restore()
        self.assertAlmostEqual(r["metres"], 1234.5)
        self.assertEqual(r["movingSeconds"], 200)
        self.assertIsNone(r["peakBoost"])

    def test_a_new_boot_does_not_restore_it(self):
        from unittest import mock
        settings = FakeSettings()
        with mock.patch("backend.trip.boot_id", lambda: "boot-a"):
            TripStore(settings).save(1234.5, 200, 300, 3)
        with mock.patch("backend.trip.boot_id", lambda: "boot-b"):
            self.assertEqual(TripStore(settings).restore(), {})


SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QObject, QTimer, QUrl, QEventLoop, pyqtProperty
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

sys.path.insert(0, sys.argv[1])
from backend.trip import TripStore, trip_record, uptime

ROOT = Path(sys.argv[1])
MI = 1609.344
app = QGuiApplication(sys.argv)


class Vehicle(QObject):
    @pyqtProperty(bool, constant=True)
    def speedKnown(self): return True

    @pyqtProperty(float, constant=True)
    def speed(self): return 60.0

    @pyqtProperty(bool, constant=True)
    def engineKnown(self): return False

    @pyqtProperty(float, constant=True)
    def boost(self): return 0.0


class Settings:
    def __init__(self, text=None):
        self.values = {} if text is None else {"trip": text}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


def run(settings, boot):
    """A Trip started with these settings, left to count for 1.3 s at 60 mph."""
    import backend.trip as t
    t.boot_id = lambda: boot
    engine = QQmlEngine()
    vehicle, store = Vehicle(), TripStore(settings)
    engine.rootContext().setContextProperty("vehicle", vehicle)
    engine.rootContext().setContextProperty("tripStore", store)
    component = QQmlComponent(engine)
    component.setData(b'import QtQuick\nimport "qml/components"\n'
                      b'Trip { property var fired: []\n'
                      b'  onMilestone: function(text) { fired = fired.concat([text]) } }',
                      QUrl.fromLocalFile(str(ROOT / "x.qml")))
    trip = component.create()
    if trip is None:
        print([e.toString() for e in component.errors()])
        sys.exit(1)
    start = {"metres": trip.property("metres"), "moving": trip.property("movingSeconds"),
             "running": trip.property("runningSeconds")}
    loop = QEventLoop()
    QTimer.singleShot(1300, loop.quit)
    loop.exec()
    return {"start": start, "fired": trip.property("fired").toVariant(),
            "metres": trip.property("metres"), "saved": settings.values.get("trip")}


def record(metres, moving=1000, running=1500, boot="boot-a"):
    return trip_record(metres, moving, running, float("-inf"), boot, uptime())


out = {
    # 40 miles in, then a restart in the same boot, rolling on at 60 mph: it
    # carries on from 40 miles and the 10, 25 miles it passed don't come again.
    "restored": run(Settings(record(40 * MI)), "boot-a"),
    # The same restart just short of 10 miles still gets its 10-mile toast.
    "crossing": run(Settings(record(10 * MI - 10)), "boot-a"),
    # A new boot (the key turned on again) is a fresh trip.
    "new_boot": run(Settings(record(40 * MI, boot="boot-a")), "boot-b"),
    "fresh": run(Settings(), "boot-a"),
}
print(json.dumps(out))
'''


class TripRestoreQmlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_same_boot_carries_on_from_the_saved_trip(self):
        r = self.out["restored"]
        self.assertAlmostEqual(r["start"]["metres"], 40 * MI)
        self.assertEqual(r["start"]["moving"], 1000)
        self.assertGreaterEqual(r["start"]["running"], 1500)
        self.assertGreater(r["metres"], 40 * MI)

    def test_nothing_fires_again_after_a_restore(self):
        self.assertEqual(self.out["restored"]["fired"], [])

    def test_a_crossing_after_a_restore_still_fires(self):
        self.assertEqual(self.out["crossing"]["fired"], ["10 miles this trip"])

    def test_a_new_boot_starts_the_trip_over(self):
        r = self.out["new_boot"]
        self.assertEqual(r["start"]["metres"], 0)
        self.assertEqual(r["start"]["moving"], 0)
        self.assertEqual(r["start"]["running"], 0)

    def test_it_is_saved_at_a_milestone(self):
        saved = json.loads(self.out["crossing"]["saved"])
        self.assertGreaterEqual(saved["metres"], 10 * MI)

    def test_it_is_not_saved_every_second(self):
        # One second of rolling, no milestone, not a 30 s mark: nothing written.
        self.assertIsNone(self.out["fresh"]["saved"])


if __name__ == "__main__":
    unittest.main()
