"""Off-Pi tests for reading Soloist's events (backend/spotify.py): odd but
valid JSON must show blanks, never raise.

    python3 -m unittest tests.test_spotify
"""

import contextlib
import io
import json
import unittest

try:
    from PyQt6.QtCore import QCoreApplication
    from backend.spotify import SpotifyPlayer
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])

PROPERTIES = ("available", "linked", "active", "deviceName", "title", "artist", "album", "art",
              "duration", "position", "playing", "hasVolume", "volume", "upNext", "recents")


def track(**decorations):
    """A track as Soloist describes it, with some decorations replaced."""
    d = {"identity": {"name": "Song"},
         "visual_identity": {"cover": [{"size": "small", "url": "https://i/small"},
                                       {"size": "large", "url": "https://i/large"}]},
         "creators": [{"entity": {"decorations": {"identity": {"name": "Band"}}}}],
         "playback": {"duration_ms": 200500},
         "parent": {"entity": {"uri": "spotify:album:a",
                               "decorations": {"identity": {"name": "Album"}}}}}
    d.update(decorations)
    return {"uri": "spotify:track:t", "decorations": {k: v for k, v in d.items() if v != "-"}}


class SoloistEventsTest(unittest.TestCase):
    def setUp(self):
        self.sp = SpotifyPlayer()

    def send(self, **event):
        """Feed one event; returns what it printed."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.sp._on_message(json.dumps(event))
        return out.getvalue()

    def read_all(self):
        """Every property QML or the hub reads; any of them raising fails."""
        return {name: getattr(self.sp, name) for name in PROPERTIES}

    def test_a_whole_track(self):
        self.send(type="track_changed", item=track())
        shown = self.read_all()
        self.assertEqual((shown["title"], shown["artist"], shown["album"], shown["art"], shown["duration"]),
                         ("Song", "Band", "Album", "https://i/large", 200))

    def test_no_cover(self):
        self.assertEqual(self.send(type="track_changed", item=track(visual_identity=None)), "")
        self.assertEqual(self.read_all()["art"], "")
        self.assertEqual(self.sp.title, "Song")

    def test_no_identity(self):
        self.assertEqual(self.send(type="track_changed", item=track(identity=None)), "")
        self.assertEqual(self.read_all()["title"], "")
        self.assertEqual(self.sp.artist, "Band")

    def test_episode_with_no_parent(self):
        self.assertEqual(self.send(type="track_changed", item=track(creators="-", parent=None)), "")
        shown = self.read_all()
        self.assertEqual((shown["artist"], shown["album"]), ("", ""))

    def test_no_playback(self):
        self.assertEqual(self.send(type="track_changed", item=track(playback=None)), "")
        self.assertEqual(self.read_all()["duration"], 0)

    def test_context_uri_without_a_kind(self):
        ctx = {"uri": "odd", "decorations": {"identity": {"name": "Mix"}}}
        self.assertEqual(self.send(type="context_changed", context=ctx), "")
        self.assertEqual(self.read_all()["recents"][0]["title"], "Mix")

    def test_position_that_isnt_an_object(self):
        self.send(type="position_sync", position={"position_ms": 61000, "speed": 0})
        self.assertEqual(self.send(type="position_sync", position=12345), "")
        self.assertEqual(self.send(type="playback_state", item=track(), position=7), "")
        self.assertEqual(self.read_all()["position"], 61)     # kept the last good one

    def test_null_in_the_queue(self):
        self.assertEqual(self.send(type="queue_changed", upcoming=[None, {"item": track()}]), "")
        self.assertEqual(self.read_all()["upNext"],
                         [{"title": "", "artist": ""}, {"title": "Song", "artist": "Band"}])

    def test_null_everything(self):
        for kind in ("auth_state", "playback_state", "track_changed", "context_changed",
                     "playback_changed", "position_sync", "volume_changed", "device_changed",
                     "queue_changed"):
            self.assertEqual(self.send(type=kind, item=None, context=None, position=None,
                                       volume=None, status=None, upcoming=None,
                                       device_name=None), "", kind)
            self.read_all()

    def test_a_bad_event_logs_one_line_and_spotify_carries_on(self):
        printed = self.send(type="volume_changed", volume=float("nan"))   # json allows NaN
        self.assertEqual(len(printed.splitlines()), 1)
        self.assertIn("Spotify: ignored a volume_changed event", printed)
        self.send(type="volume_changed", volume=30)
        self.assertEqual(self.sp.volume, 30)

    def test_a_soloist_error_shows_a_short_message_until_playback_moves(self):
        self.send(type="error", message="429 too many requests")
        self.assertEqual(self.sp.error, "Spotify isn't answering right now")
        self.send(type="playback_state", status="playing")
        self.assertEqual(self.sp.error, "")

    def test_a_new_track_clears_the_error_and_tells_qml(self):
        self.send(type="playback_state", status="playing", item=track())
        self.send(type="error", message="429")
        changes = []
        self.sp.changed.connect(lambda: changes.append(1))
        self.send(type="track_changed", item=track(identity={"name": "Next"}))
        self.assertEqual(self.sp.error, "")
        self.assertTrue(changes)

    def test_a_status_change_tells_qml_the_error_went(self):
        self.send(type="error", message="429")
        changes = []
        self.sp.changed.connect(lambda: changes.append(1))
        self.send(type="playback_changed", status="paused")
        self.assertEqual(self.sp.error, "")
        self.assertTrue(changes)


if __name__ == "__main__":
    unittest.main()
