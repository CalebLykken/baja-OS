"""Off-Pi tests for reading Soloist's events (backend/spotify.py): odd but
valid JSON must show blanks, never raise.

    python3 -m unittest tests.test_spotify
"""

import contextlib
import io
import json
import unittest
from unittest import mock

try:
    from PyQt6.QtCore import QCoreApplication
    from backend import spotify
    from backend.spotify import SETTLE_S, SpotifyPlayer
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


class Connected(unittest.TestCase):
    """A player with its socket faked: `sent` is what went to Soloist."""

    def setUp(self):
        self.sp = SpotifyPlayer(settings=self.settings())
        self.sent = []
        self.sp._ws = mock.Mock()
        self.sp._ws.sendTextMessage = lambda text: self.sent.append(json.loads(text))
        self.sp._connected = True
        self.addCleanup(self.sp._pending_timer.stop)
        self.addCleanup(self.sp._fallback_timer.stop)

    def settings(self):
        return None

    def send(self, **event):
        self.sp._on_message(json.dumps(event))

    def commands(self):
        return [m["command"] for m in self.sent]

    def signed_in(self, active=False):
        self.send(type="auth_state", logged_in=True, is_active=active, device_name="Baja")
        self.sent.clear()


class ReachingTheHubTest(Connected):
    def test_playing_then_active_says_playing(self):
        self.signed_in()
        self.send(type="playback_changed", status="playing")
        self.assertFalse(self.sp.playing)
        heard = []
        self.sp.playingChanged.connect(lambda: heard.append(self.sp.playing))
        self.send(type="device_changed", is_active=True)
        self.assertEqual(heard, [True])

    def test_a_whole_state_in_one_event_says_playing(self):
        self.signed_in()
        heard = []
        self.sp.playingChanged.connect(lambda: heard.append(self.sp.playing))
        self.send(type="playback_state", status="playing", is_active=True, item=track())
        self.assertEqual(heard[-1], True)

    def test_signing_in_asks_what_is_playing(self):
        self.send(type="auth_state", logged_in=True, is_active=True)
        self.assertIn("get_state", self.commands())

    def test_signed_out_it_doesnt_ask(self):
        self.send(type="auth_state", logged_in=False, is_active=False)
        self.assertEqual(self.commands(), [])

    def test_a_dropped_socket_clears_the_error(self):
        self.send(type="error", message="boom")
        with mock.patch.object(self.sp._retry, "start"):
            self.sp._on_disconnected()
        self.assertEqual(self.sp.error, "")

    def test_signing_in_clears_the_error(self):
        self.send(type="error", message="command requires authentication")
        self.assertEqual(self.sp.error, "Spotify is still connecting")
        self.send(type="auth_state", logged_in=True, is_active=False)
        self.assertEqual(self.sp.error, "")


class PlayingFromTheDashboardTest(Connected):
    def test_it_waits_for_the_pi_to_be_active(self):
        self.signed_in()
        self.sp.playUri("spotify:album:a")
        self.assertEqual(self.sent, [{"type": "command", "command": "activate"}])
        self.send(type="device_changed", is_active=True)
        self.assertEqual(self.sent[-1], {"type": "command", "command": "play", "uri": "spotify:album:a"})

    def test_it_plays_anyway_if_the_answer_never_comes(self):
        self.signed_in()
        self.sp.playUri("spotify:album:a")
        self.sp._pending_timer.timeout.emit()
        self.assertEqual(self.commands(), ["activate", "play"])

    def test_already_active_it_just_plays(self):
        self.signed_in(active=True)
        self.sp.playUri("spotify:track:t")
        self.assertEqual(self.commands(), ["play"])

    def test_signed_out_it_says_so(self):
        self.send(type="auth_state", logged_in=False)
        self.sp.playUri("spotify:track:t")
        self.assertEqual((self.commands()[-1:], self.sp.error), ([], "Spotify is still connecting"))

    def test_resuming_carries_on_without_a_uri(self):
        self.signed_in()
        self.sp.resume("spotify:album:a")
        self.send(type="device_changed", is_active=True)
        self.assertEqual(self.sent[-1], {"type": "command", "command": "play"})

    def test_resuming_falls_back_on_the_saved_album(self):
        self.signed_in(active=True)
        self.sp.resume("spotify:album:a")
        self.sp._fallback_timer.timeout.emit()
        self.assertEqual(self.sent[-1], {"type": "command", "command": "play", "uri": "spotify:album:a"})

    def test_no_fallback_once_its_playing(self):
        self.signed_in(active=True)
        self.sp.resume("spotify:album:a")
        self.send(type="playback_changed", status="playing")
        self.sent.clear()
        self.sp._fallback_timer.timeout.emit()
        self.assertEqual(self.sent, [])

    def test_still_falls_back_if_it_only_buffered(self):
        self.signed_in(active=True)
        self.sp.resume("spotify:album:a")
        self.send(type="playback_changed", status="buffering")
        self.send(type="playback_changed", status="paused")     # ...and then it failed
        self.sent.clear()
        self.sp._fallback_timer.timeout.emit()
        self.assertEqual(self.sent[-1], {"type": "command", "command": "play", "uri": "spotify:album:a"})

    def test_no_fallback_after_pausing(self):
        self.signed_in(active=True)
        self.sp.resume("spotify:album:a")
        self.sp.pause()
        self.sent.clear()
        self.sp._fallback_timer.timeout.emit()
        self.assertEqual(self.sent, [])
        self.assertFalse(self.sp._fallback_timer.isActive())

    def test_no_fallback_after_the_knob_toggles(self):
        self.signed_in(active=True)
        self.sp.resume("spotify:album:a")
        self.sp.togglePlay()
        self.sent.clear()
        self.sp._fallback_timer.timeout.emit()
        self.assertEqual(self.sent, [])

    def test_no_fallback_after_picking_something_else(self):
        self.signed_in(active=True)
        self.sp.resume("spotify:album:a")
        self.sp.playUri("spotify:album:b")
        self.sent.clear()
        self.sp._fallback_timer.timeout.emit()
        self.assertEqual(self.sent, [])

    def test_no_fallback_after_cancelling_the_resume(self):
        self.signed_in(active=True)
        self.sp.resume("spotify:album:a")
        self.sp.cancel_resume()
        self.sent.clear()
        self.sp._fallback_timer.timeout.emit()
        self.assertEqual(self.sent, [])

    def test_a_cancelled_resume_sends_no_play_once_active(self):
        self.signed_in()
        self.sp.resume("spotify:album:a")
        self.sp.cancel_resume()
        self.send(type="device_changed", is_active=True)
        self.assertNotIn("play", self.commands())

    def test_no_fallback_after_disconnecting(self):
        self.signed_in(active=True)
        self.sp.resume("spotify:album:a")
        self.sp._on_disconnected()
        self.assertFalse(self.sp._fallback_timer.isActive())
        self.assertEqual(self.sp._fallback, "")

    def test_the_resume_uri_is_the_context_then_the_song(self):
        self.send(type="track_changed", item=track())
        self.assertEqual(self.sp.resumeUri, "spotify:track:t")
        self.send(type="context_changed", context={"uri": "spotify:playlist:p"})
        self.assertEqual(self.sp.resumeUri, "spotify:playlist:p")

    def test_a_list_plays_the_first_and_queues_the_rest_in_order(self):
        self.signed_in()
        self.sp.playTracks(["spotify:track:1", "spotify:track:2", "spotify:track:3"])
        self.assertEqual(self.commands(), ["activate"])     # nothing queued before it's playing here
        self.send(type="device_changed", is_active=True)
        self.assertEqual(self.commands(), ["activate", "play", "add_to_queue", "add_to_queue"])
        self.assertEqual(self.sent[-1]["uri"], "spotify:track:3")

    def test_an_empty_list_does_nothing(self):
        self.signed_in(active=True)
        self.sp.playTracks([])
        self.assertEqual(self.sent, [])

    def test_adding_to_the_queue(self):
        self.signed_in(active=True)
        self.sp.addToQueue("spotify:track:t")
        self.assertEqual(self.sent, [{"type": "command", "command": "add_to_queue", "uri": "spotify:track:t"}])


class ModesTest(Connected):
    def test_options_are_read_from_both_events(self):
        self.send(type="playback_state", options={"shuffle": True, "repeat": "track"})
        self.assertEqual((self.sp.shuffle, self.sp.repeat), (True, "one"))
        self.send(type="options_changed", options={"shuffle": False, "repeat": "context"})
        self.assertEqual((self.sp.shuffle, self.sp.repeat), (False, "all"))

    def test_odd_options_change_nothing(self):
        self.send(type="options_changed", options={"shuffle": True, "repeat": "track"})
        for odd in (None, 7, {"repeat": "sideways"}, {}):
            self.send(type="options_changed", options=odd)
        self.assertEqual((self.sp.shuffle, self.sp.repeat), (True, "one"))

    def test_shuffle(self):
        self.sp.toggleShuffle()
        self.assertEqual(self.sent, [{"type": "command", "command": "set_shuffle", "enabled": True}])

    def test_repeat_sends_soloists_two_commands_in_order(self):
        steps = []
        for _ in range(3):
            self.sent.clear()
            self.sp.cycleRepeat()
            steps.append([(m["command"].removeprefix("set_repeat_"), m["enabled"]) for m in self.sent])
        self.assertEqual(steps, [[("track", False), ("context", True)],
                                 [("context", False), ("track", True)],
                                 [("track", False), ("context", False)]])


class StoreSettings(dict):
    def set(self, key, value):
        self[key] = value


class StayingSignedInTest(Connected):
    def settings(self):
        self.store = StoreSettings(spotifyPaired="true")
        return self.store

    def setUp(self):
        super().setUp()
        self.now = 1000.0
        self.restarts = 0
        self.sp._connected_at = self.now
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(spotify.time, "monotonic", lambda: self.now).start()
        mock.patch.object(SpotifyPlayer, "_restart_soloist", side_effect=self.restarted).start()
        mock.patch.object(spotify, "threading", mock.Mock(
            Thread=lambda target, daemon: mock.Mock(start=target))).start()
        mock.patch("builtins.print").start()

    def restarted(self):
        self.restarts += 1

    def check(self):
        self.sp._check_session()
        return self.restarts

    def test_signed_out_and_online_it_restarts_soloist(self):
        self.sp.set_network(True, "172.20.10.2")
        self.now += SETTLE_S + 1
        self.assertEqual(self.check(), 1)

    def test_a_fresh_soloist_gets_time_to_sign_in(self):
        self.sp.set_network(True, "172.20.10.2")
        self.now += SETTLE_S - 1
        self.assertEqual(self.check(), 0)

    def test_offline_there_is_no_point(self):
        self.sp.set_network(False, "")
        self.now += SETTLE_S + 1
        self.assertEqual(self.check(), 0)

    def test_restarts_back_off(self):
        self.sp.set_network(True, "172.20.10.2")
        self.now += SETTLE_S + 1
        self.check()
        self.now += 30
        self.assertEqual(self.check(), 1)
        self.now += 31
        self.assertEqual(self.check(), 2)
        self.now += 61
        self.assertEqual(self.check(), 2)      # the wait doubled

    def test_a_pi_that_never_paired_is_left_alone(self):
        self.sp._paired = False
        self.sp.set_network(True, "172.20.10.2")
        self.now += 999
        self.assertEqual(self.check(), 0)

    def test_signing_in_is_remembered_as_paired(self):
        self.sp._paired = False
        del self.store["spotifyPaired"]
        self.store["other"] = "kept"      # an empty dict is falsy, unlike real settings
        self.signed_in()
        self.assertEqual(self.store["spotifyPaired"], "true")

    def test_the_connection_moving_restarts_it_even_signed_in(self):
        self.signed_in()
        self.sp.set_network(True, "192.168.1.5")
        self.now += SETTLE_S + 1
        self.sp.set_network(True, "172.20.10.2")
        self.assertEqual(self.check(), 1)
        self.assertEqual(self.check(), 1)      # once for one move

    def test_the_connection_coming_back_restarts_it(self):
        self.signed_in()
        self.sp.set_network(True, "172.20.10.2")
        self.sp.set_network(False, "")
        self.now += SETTLE_S + 1
        self.sp.set_network(True, "172.20.10.2")
        self.assertEqual(self.check(), 1)

    def test_coming_online_as_soloist_starts_is_not_a_move(self):
        self.signed_in()
        self.sp.set_network(False, "")
        self.sp.set_network(True, "172.20.10.2")
        self.now += SETTLE_S + 1
        self.assertEqual(self.check(), 0)

    def test_it_never_restarts_over_playing_music(self):
        self.signed_in(active=True)
        self.send(type="playback_changed", status="playing")
        self.sp.set_network(True, "192.168.1.5")
        self.now += SETTLE_S + 1
        self.sp.set_network(True, "172.20.10.2")
        self.assertEqual(self.check(), 0)
        self.send(type="playback_changed", status="paused")
        self.assertEqual(self.check(), 1)      # as soon as it can


class StatusTextTest(Connected):
    def shown(self, bin=True, key=True):
        with mock.patch.object(spotify, "SOLOIST_BIN", mock.Mock(exists=lambda: bin)), \
             mock.patch.object(spotify, "SOLOIST_ENV", mock.Mock(exists=lambda: key)):
            return self.sp.statusText

    def test_not_installed(self):
        self.assertEqual(self.shown(bin=False), "Not set up on this Pi")

    def test_no_key(self):
        self.assertIn("set-spotify-key.sh", self.shown(key=False))

    def test_waiting_for_internet_isnt_not_set_up(self):
        self.sp._connected = False
        self.sp.set_network(False, "")
        self.assertIn("Waiting for internet", self.shown())

    def test_online_and_starting(self):
        self.sp._connected = False
        self.sp.set_network(True, "172.20.10.2")
        self.assertEqual(self.shown(), "Starting Spotify")

    def test_never_paired_says_how(self):
        self.assertIn("same Wi-Fi", self.shown())

    def test_paired_but_signed_out_is_reconnecting(self):
        self.sp._paired = True
        self.assertEqual(self.shown(), "Reconnecting to Spotify")

    def test_signed_in(self):
        self.signed_in()
        self.assertEqual(self.shown(), "Connected as Baja")


if __name__ == "__main__":
    unittest.main()
