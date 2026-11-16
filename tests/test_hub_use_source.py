"""Off-Pi tests for moving between the Pi's music and the phone from the
Playing page (MediaHub.otherSources and useSource).

    python3 -m unittest tests.test_hub_use_source
"""

import unittest
from pathlib import Path
from unittest import mock

try:
    from backend.hub import MediaHub
    from backend.media import MediaPlayer
    from tests.test_hub import FakeSettings, FakeSource
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")

MUSIC_PAGE = Path(__file__).resolve().parent.parent / "qml" / "pages" / "MusicPage.qml"


class UseSourceTest(unittest.TestCase):
    def make(self, phone_player=True):
        self.local, self.phone, self.spotify = MediaPlayer(), FakeSource(), FakeSource()
        self.phone.deviceName = "Pixel"
        self.phone.hasPlayer = phone_player
        with mock.patch("backend.hub.shutil.which", return_value=None):
            self.hub = MediaHub(self.local, self.phone, self.spotify, settings=FakeSettings())
        self.hub.start()
        self.local_plays = lambda: None if self.local.playing else self.local.togglePlay()
        self.addCleanup(self.local._timer.stop)
        return self.hub

    def test_local_playing_offers_the_phone(self):
        hub = self.make()
        self.local_plays()
        self.assertEqual(hub.otherSources, [{"name": "phone", "label": "Pixel"}])

    def test_use_phone_pauses_local_and_plays_the_phone(self):
        hub = self.make()
        self.local_plays()
        self.assertTrue(self.local.playing)
        hub.useSource("phone")
        self.assertFalse(self.local.playing)
        self.assertEqual(hub.source, "phone")
        self.assertTrue(self.phone.playing)

    def test_use_local_returns_and_plays(self):
        hub = self.make()
        hub.useSource("phone")
        self.assertEqual(hub.otherSources, [{"name": "local", "label": "On this Pi"}])
        hub.useSource("local")
        self.assertEqual(hub.source, "local")
        self.assertTrue(self.local.playing)
        self.assertFalse(self.phone.playing)

    def test_no_phone_player_means_nothing_to_switch_to_from_local(self):
        hub = self.make(phone_player=False)
        self.assertEqual(hub.otherSources, [])
        hub.useSource("phone")
        self.assertEqual(hub.source, "local")

    def test_on_phone_without_a_player_only_local_is_listed(self):
        hub = self.make()
        hub.useSource("phone")
        self.phone.hasPlayer = False
        self.assertEqual([o["name"] for o in hub.otherSources], ["local"])

    def test_unknown_or_current_source_does_nothing(self):
        hub = self.make()
        hub.useSource("local")
        hub.useSource("nonsense")
        self.assertEqual(hub.source, "local")
        self.assertFalse(self.phone.playing)

    def test_chips_are_hidden_when_the_list_is_empty(self):
        src = MUSIC_PAGE.read_text()
        block = src.split("id: otherSources", 1)[1].split("Repeater", 1)[0]
        self.assertIn("visible: media.otherSources.length > 0", block)


if __name__ == "__main__":
    unittest.main()
