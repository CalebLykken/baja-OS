"""Off-Pi tests for the greeting in qml/components/Splash.qml: fixed dates
win, weekend lines come next, and each time slot has three phrasings picked by
day of the year. Runs in a subprocess because other test modules hold a
QCoreApplication.

    python3 -m unittest tests.test_splash_greeting
"""

import datetime
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

ROOT = Path(__file__).resolve().parent.parent

# The QML wrapper evaluates splash.greeting() for each (y, m, d, h) in argv[2]
# and returns the strings as one JSON value on the `out` property.
SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
pairs = json.loads(sys.argv[2])
synced = json.loads(sys.argv[3])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()

source = (
    'import QtQuick\nimport "qml/components"\n'
    'Item {\n'
    '    Splash { id: splash; width: 800; height: 480 }\n'
    '    property string out: JSON.stringify(%s.map(function (p) {\n'
    '        return splash.greeting(new Date(p[0], p[1] - 1, p[2], p[3]), %s)\n'
    '    }))\n'
    '}\n' % (json.dumps(pairs), json.dumps(synced))
)
component = QQmlComponent(engine)
component.setData(source.encode(), QUrl.fromLocalFile(str(ROOT / "x.qml")))
obj = component.create()
if obj is None:
    print([e.toString() for e in component.errors()])
    sys.exit(1)
print(obj.property("out"))
'''

AFTERNOON = {"Good afternoon", "Afternoon drive", "Plenty of daylight left"}
EVENING = {"Good evening", "Evening cruise", "Golden hour"}
NIGHT = {"Late night run", "Night drive", "Quiet roads tonight"}
MORNING = {"Good morning", "Morning, let's roll", "Coffee and the open road"}
FIXED = {"Happy New Year", "Merry Christmas", "Happy Halloween", "Happy Fourth"}
WEEKEND = {"Weekend starts here", "Weekend morning"}

NAMED = {
    "new_year": (2026, 1, 1, 9),
    "friday_evening": (2026, 1, 2, 19),
    "friday_1659": (2026, 1, 2, 16),
    "friday_1700": (2026, 1, 2, 17),
    "saturday_morning": (2026, 1, 3, 8),
    "sunday_noon": (2026, 1, 4, 12),
    "tuesday_night": (2026, 1, 6, 3),
    "monday_9": (2026, 1, 5, 9),
    "tuesday_9": (2026, 1, 6, 9),
    "wednesday_9": (2026, 1, 7, 9),
    "christmas": (2026, 12, 25, 10),
    "christmas_eve": (2026, 12, 24, 20),
    "halloween_saturday": (2026, 10, 31, 8),
    "fourth": (2026, 7, 4, 12),
}


def sweep_pairs():
    """Every day of 2026 at hours that sit on each slot boundary."""
    day = datetime.date(2026, 1, 1)
    out = []
    while day.year == 2026:
        for hour in (0, 4, 5, 11, 12, 16, 17, 21, 22, 23):
            out.append((day.year, day.month, day.day, hour))
        day += datetime.timedelta(days=1)
    return out


def run_greetings(pairs, synced):
    """splash.greeting(date, synced) for each (y, m, d, h) in pairs."""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT), json.dumps(pairs),
                             json.dumps(synced)],
                            cwd=ROOT, capture_output=True, text=True, timeout=120, env=env)
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


class UnsyncedGreetingTest(unittest.TestCase):
    """With no RTC battery the clock at boot is fake-hwclock's last save, so
    until it is set the date and hour say nothing: one plain line."""

    def test_nothing_is_said_about_the_date_or_hour(self):
        pairs = list(NAMED.values()) + sweep_pairs()
        for synced in (False, None, "yes"):
            results = run_greetings(pairs, synced)
            self.assertEqual(set(results), {"Welcome back"}, synced)

    def test_synced_still_gets_the_dated_lines(self):
        self.assertEqual(run_greetings([NAMED["christmas"]], True), ["Merry Christmas"])


class SplashSourceTest(unittest.TestCase):
    """The splash ground is fixed near-black, so its text must not follow the
    day/night appearance (Theme.text is dark-on-light in daylight)."""

    def setUp(self):
        self.text = (ROOT / "qml" / "components" / "Splash.qml").read_text()

    def test_text_colours_come_from_the_dark_set(self):
        self.assertNotRegex(self.text, r"Theme\.(text|textDim|accent)\b")
        self.assertIn("Theme.base.text", self.text)
        self.assertIn("Theme.base.textDim", self.text)

    def test_greeting_asks_whether_the_clock_is_set(self):
        self.assertIn("system.clockSynced", self.text)
        self.assertNotIn("greeting(new Date())", self.text)


class SplashGreetingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sweep = sweep_pairs()
        pairs = list(NAMED.values()) + cls.sweep
        results = run_greetings(pairs, True)
        cls.named = dict(zip(NAMED.keys(), results[:len(NAMED)]))
        cls.sweep_results = results[len(NAMED):]

    def test_new_year_wins_at_nine(self):
        self.assertEqual(self.named["new_year"], "Happy New Year")

    def test_friday_evening_is_weekend_start(self):
        self.assertEqual(self.named["friday_evening"], "Weekend starts here")

    def test_friday_starts_weekend_at_five(self):
        self.assertEqual(self.named["friday_1700"], "Weekend starts here")
        self.assertIn(self.named["friday_1659"], AFTERNOON)

    def test_saturday_morning_is_weekend_morning(self):
        self.assertEqual(self.named["saturday_morning"], "Weekend morning")

    def test_sunday_noon_is_not_weekend_morning(self):
        self.assertIn(self.named["sunday_noon"], AFTERNOON)

    def test_late_tuesday_is_a_night_variant(self):
        self.assertIn(self.named["tuesday_night"], NIGHT)

    def test_holidays(self):
        self.assertEqual(self.named["christmas"], "Merry Christmas")
        self.assertEqual(self.named["christmas_eve"], "Merry Christmas")
        self.assertEqual(self.named["fourth"], "Happy Fourth")

    def test_holiday_beats_weekend(self):
        # Oct 31 2026 is a Saturday morning; the holiday line wins.
        self.assertEqual(self.named["halloween_saturday"], "Happy Halloween")

    def test_consecutive_weekday_mornings_vary(self):
        mornings = {self.named["monday_9"], self.named["tuesday_9"], self.named["wednesday_9"]}
        self.assertTrue(mornings <= MORNING)
        self.assertGreaterEqual(len(mornings), 2)

    def test_same_day_is_stable_within_a_slot(self):
        # Ten readings for one day, hours 0, 4, 5, 11, 12, 16, 17, 21, 22, 23.
        day = [r for p, r in zip(self.sweep, self.sweep_results) if p[:3] == (2026, 3, 10)]
        self.assertEqual(day[2], day[3])   # 5:00 and 11:00, both morning
        self.assertEqual(day[4], day[5])   # 12:00 and 16:00, both afternoon

    def test_every_result_is_short_and_non_empty(self):
        for result in self.sweep_results:
            self.assertIsInstance(result, str)
            self.assertTrue(0 < len(result) < 30, result)

    def test_every_result_is_a_known_string(self):
        known = FIXED | WEEKEND | MORNING | AFTERNOON | EVENING | NIGHT
        for result in self.sweep_results:
            self.assertIn(result, known)


if __name__ == "__main__":
    unittest.main()
