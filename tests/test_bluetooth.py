"""Off-Pi tests that a crashing Bluetooth poll (backend/bluetooth.py) is logged
once, frees the busy flag, keeps the last state, and lets the next poll run.
BlueZ is faked, and the worker thread runs right where it's started.

    python3 -m unittest tests.test_bluetooth
"""

import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from PyQt6.QtCore import QCoreApplication

from backend.bluetooth import SAFETY_TICKS, BluetoothAudio, parse_objects
from tests.test_dbus import FakeBus, on_bus

app = QCoreApplication.instance() or QCoreApplication([])


class InlineThread:
    """Stands in for threading.Thread: start() runs the work on the spot."""

    def __init__(self, target=None, daemon=None):
        self.target = target

    def start(self):
        self.target()


INLINE = mock.patch("backend.bluetooth.threading", SimpleNamespace(Thread=InlineThread))


def phone(alias, paired=True, trusted=True):
    """What busctl says about an adapter and one connected phone."""
    def v(kind, data):
        return {"type": kind, "data": data}
    return {
        "/org/bluez/hci0": {"org.bluez.Adapter1": {"Discoverable": v("b", False)}},
        "/org/bluez/hci0/dev_AA": {"org.bluez.Device1": {
            "Alias": v("s", alias), "Paired": v("b", paired), "Trusted": v("b", trusted),
            "Connected": v("b", True)}},
    }


def busctl_says(objects):
    out = json.dumps({"type": "a{oa{sa{sv}}}", "data": [objects]})
    return subprocess.CompletedProcess(["busctl"], 0, out, "")


def logged(printed):
    return [c.args[0] for c in printed.call_args_list if c.args and "Bluetooth" in str(c.args[0])]


def two_phones(status_a, status_b):
    """Two connected phones, each with a player and a transport (volume 10 / 90)."""
    def v(kind, data):
        return {"type": kind, "data": data}
    objects = phone("Driver")
    objects["/org/bluez/hci0/dev_BB"] = {"org.bluez.Device1": {
        "Alias": v("s", "Passenger"), "Paired": v("b", True), "Trusted": v("b", True),
        "Connected": v("b", True)}}
    for tag, status, vol in (("AA", status_a, 10), ("BB", status_b, 90)):
        dev = f"/org/bluez/hci0/dev_{tag}"
        objects[dev + "/player0"] = {"org.bluez.MediaPlayer1": {
            "Device": v("o", dev), "Status": v("s", status),
            "Track": v("a{sv}", {"Title": v("s", "Song " + tag)})}}
        objects[dev + "/fd0"] = {"org.bluez.MediaTransport1": {
            "Device": v("o", dev), "Volume": v("q", vol)}}
    return objects


class PlayerChoiceTest(unittest.TestCase):
    def test_the_playing_phone_wins_whatever_the_order(self):
        for a, b, want in (("paused", "playing", "BB"), ("playing", "paused", "AA")):
            state = parse_objects(two_phones(a, b))
            self.assertEqual(state["player"]["path"], f"/org/bluez/hci0/dev_{want}/player0")
            self.assertEqual(state["player"]["title"], "Song " + want)
            self.assertEqual(state["device"], "Driver" if want == "AA" else "Passenger")

    def test_the_volume_is_the_playing_phones_own(self):
        state = parse_objects(two_phones("paused", "playing"))
        self.assertEqual((state["transport"], state["volume"]), ("/org/bluez/hci0/dev_BB/fd0", 90))
        state = parse_objects(two_phones("playing", "paused"))
        self.assertEqual((state["transport"], state["volume"]), ("/org/bluez/hci0/dev_AA/fd0", 10))

    def test_no_volume_from_the_other_phone(self):
        # The playing phone has no absolute volume (or its transport isn't
        # up yet): the slider mustn't take the passenger's instead.
        objects = two_phones("paused", "playing")
        del objects["/org/bluez/hci0/dev_BB/fd0"]
        state = parse_objects(objects)
        self.assertEqual(state["player"]["title"], "Song BB")
        self.assertEqual((state["transport"], state["volume"]), (None, None))

    def test_when_neither_or_both_play_the_last_one_used_stays(self):
        for status in ("paused", "playing"):
            for last in ("AA", "BB"):
                state = parse_objects(two_phones(status, status), f"/org/bluez/hci0/dev_{last}/player0")
                self.assertEqual(state["player"]["title"], "Song " + last)

    def test_transport_commands_go_to_the_chosen_player(self):
        bt = BluetoothAudio()
        bt._player = parse_objects(two_phones("paused", "playing"))["player"]
        with mock.patch("backend.bluetooth.threading", SimpleNamespace(Thread=InlineThread)), \
                mock.patch("backend.bluetooth._busctl") as busctl:
            bt.next()
        self.assertEqual(busctl.call_args.args[2], "/org/bluez/hci0/dev_BB/player0")

    def test_one_phone_is_as_before(self):
        state = parse_objects(two_phones("playing", "playing"))
        self.assertIsNotNone(state["player"])
        self.assertIsNone(parse_objects({})["player"])


class PollFailureTest(unittest.TestCase):
    def setUp(self):
        self.bt = BluetoothAudio()
        INLINE.start()
        self.printed = mock.patch("builtins.print").start()
        self.addCleanup(mock.patch.stopall)

    def poll(self, objects):
        with mock.patch("backend.bluetooth._busctl", return_value=busctl_says(objects)):
            self.bt._tick()

    def test_two_crashing_polls_log_once_and_keep_the_state(self):
        self.poll(phone("Pixel"))
        self.assertEqual(self.bt.deviceName, "Pixel")
        with mock.patch("backend.bluetooth.parse_objects", side_effect=TypeError("bad data")):
            for _ in range(2):
                self.poll(phone("Pixel"))
                self.assertFalse(self.bt._busy)           # the next poll can run
                self.assertEqual(self.bt.deviceName, "Pixel")
        lines = logged(self.printed)
        self.assertEqual(len(lines), 1)
        self.assertIn("TypeError: bad data", lines[0])
        self.assertIn("Traceback", lines[0])              # an unexpected kind of error

    def test_the_next_poll_after_a_crash_applies_good_data(self):
        self.poll(phone("Pixel"))
        with mock.patch("backend.bluetooth.parse_objects", side_effect=AttributeError("nope")):
            self.poll(phone("Pixel"))
        self.poll(phone("Pixel 9"))
        self.assertEqual(self.bt.deviceName, "Pixel 9")
        self.assertFalse(self.bt._busy)
        lines = logged(self.printed)
        self.assertEqual(len(lines), 2)
        self.assertIn("working again", lines[1])

    def test_a_different_error_is_logged_again(self):
        with mock.patch("backend.bluetooth.parse_objects", side_effect=TypeError("one")):
            self.poll({})
        with mock.patch("backend.bluetooth.parse_objects", side_effect=KeyError("two")):
            self.poll({})
        self.assertEqual(len(logged(self.printed)), 2)

    def test_junk_json_from_busctl_is_a_crash_not_a_blank_state(self):
        self.poll(phone("Pixel"))
        bad = subprocess.CompletedProcess(["busctl"], 0, json.dumps({"data": 5}), "")
        with mock.patch("backend.bluetooth._busctl", return_value=bad):
            self.bt._tick()                               # 5[0]: a TypeError
        self.assertFalse(self.bt._busy)
        self.assertEqual(self.bt.deviceName, "Pixel")
        self.assertEqual(len(logged(self.printed)), 1)

    def test_a_crash_while_trusting_still_applies_the_poll(self):
        def busctl(*args, **kw):
            if args[0] == "set-property":
                raise TypeError("trust")
            return busctl_says(phone("Pixel", trusted=False))
        with mock.patch("backend.bluetooth._busctl", side_effect=busctl):
            for _ in range(2):
                self.bt._tick()
                self.assertFalse(self.bt._busy)
        self.assertEqual(self.bt.deviceName, "Pixel")
        self.assertEqual(len(logged(self.printed)), 1)

    def test_no_bluez_is_the_usual_quiet_blank_state(self):
        self.poll(phone("Pixel"))
        for error in (FileNotFoundError("busctl"), subprocess.TimeoutExpired("busctl", 3)):
            with mock.patch("backend.bluetooth._busctl", side_effect=error):
                self.bt._tick()
            self.assertFalse(self.bt._busy)
            self.assertFalse(self.bt.adapterPresent)
            self.assertEqual(self.bt.deviceName, "")
        self.assertEqual(logged(self.printed), [])


class ParseObjectsTest(unittest.TestCase):
    """The rest of what parse_objects reduces BlueZ's answer to."""

    def test_no_adapter_and_nothing_else(self):
        state = parse_objects({})
        self.assertEqual((state["adapter"], state["device"], state["paired"], state["to_trust"]), (None, None, [], []))
        self.assertEqual((state["transport"], state["volume"], state["discoverable"]), (None, None, False))

    def test_a_phone_without_a_player_still_names_the_device(self):
        state = parse_objects(phone("Driver"))
        self.assertEqual((state["adapter"], state["device"], state["player"]), ("/org/bluez/hci0", "Driver", None))
        self.assertEqual(state["paired"], [{"path": "/org/bluez/hci0/dev_AA", "name": "Driver", "connected": True}])

    def test_a_paired_phone_not_yet_trusted_is_to_be_trusted(self):
        self.assertEqual(parse_objects(phone("Driver", trusted=False))["to_trust"], ["/org/bluez/hci0/dev_AA"])
        self.assertEqual(parse_objects(phone("Driver", trusted=True))["to_trust"], [])

    def test_an_unpaired_phone_is_not_listed(self):
        state = parse_objects(phone("Stranger", paired=False))
        self.assertEqual((state["paired"], state["to_trust"]), ([], []))

    def test_connected_phones_first_then_by_name(self):
        objects = two_phones("paused", "paused")
        objects["/org/bluez/hci0/dev_CC"] = {"org.bluez.Device1": {
            "Alias": "alpha", "Paired": True, "Trusted": True, "Connected": False}}      # plain values, not variants
        objects["/org/bluez/hci0/dev_DD"] = {"org.bluez.Device1": {
            "Name": "Zed", "Paired": True, "Trusted": True, "Connected": False}}
        self.assertEqual([(d["name"], d["connected"]) for d in parse_objects(objects)["paired"]],
                         [("Driver", True), ("Passenger", True), ("alpha", False), ("Zed", False)])

    def test_the_name_falls_back_to_the_address(self):
        objects = {"/org/bluez/hci0/dev_AA": {"org.bluez.Device1": {
            "Address": "AA:BB", "Paired": True, "Trusted": True, "Connected": True}},
            "/org/bluez/hci0/dev_BB": {"org.bluez.Device1": {"Paired": True, "Trusted": True, "Connected": False}}}
        self.assertEqual([d["name"] for d in parse_objects(objects)["paired"]], ["AA:BB", "Device"])

    def test_discoverable_while_pairing(self):
        objects = phone("Driver")
        objects["/org/bluez/hci0"]["org.bluez.Adapter1"]["Discoverable"] = {"type": "b", "data": True}
        self.assertTrue(parse_objects(objects)["discoverable"])

    def test_a_track_with_nothing_filled_in(self):
        objects = phone("Driver")
        objects["/org/bluez/hci0/dev_AA/player0"] = {"org.bluez.MediaPlayer1": {
            "Device": {"type": "o", "data": "/org/bluez/hci0/dev_AA"}}}
        player = parse_objects(objects)["player"]
        self.assertEqual((player["status"], player["title"], player["artist"], player["album"]),
                         ("stopped", "", "", ""))
        self.assertEqual((player["position_ms"], player["duration_ms"]), (0, 0))

    def test_a_tracks_details(self):
        def v(kind, data):
            return {"type": kind, "data": data}
        objects = phone("Driver")
        objects["/org/bluez/hci0/dev_AA/player0"] = {"org.bluez.MediaPlayer1": {
            "Device": v("o", "/org/bluez/hci0/dev_AA"), "Status": v("s", "playing"), "Position": v("u", 12345),
            "Track": v("a{sv}", {"Title": v("s", "Song"), "Artist": v("s", "Band"), "Album": v("s", "LP"),
                                 "Duration": v("u", 200000)})}}
        self.assertEqual(parse_objects(objects)["player"],
                         {"path": "/org/bluez/hci0/dev_AA/player0", "device": "/org/bluez/hci0/dev_AA",
                          "status": "playing", "position_ms": 12345, "title": "Song", "artist": "Band",
                          "album": "LP", "duration_ms": 200000})

    def test_a_transport_with_no_player_gives_its_volume(self):
        objects = two_phones("paused", "paused")
        for path in [p for p in objects if p.endswith("/player0")]:
            del objects[path]
        state = parse_objects(objects)
        self.assertIsNone(state["player"])
        self.assertIn(state["volume"], (10, 90))

    def test_a_transport_without_a_volume_is_not_one(self):
        objects = phone("Driver")
        objects["/org/bluez/hci0/dev_AA/fd0"] = {"org.bluez.MediaTransport1": {
            "Device": {"type": "o", "data": "/org/bluez/hci0/dev_AA"}}}
        state = parse_objects(objects)
        self.assertEqual((state["transport"], state["volume"]), (None, None))

    def test_a_volume_of_zero_is_a_volume(self):
        objects = two_phones("playing", "paused")
        objects["/org/bluez/hci0/dev_AA/fd0"]["org.bluez.MediaTransport1"]["Volume"]["data"] = 0
        state = parse_objects(objects)
        self.assertEqual((state["transport"], state["volume"]), ("/org/bluez/hci0/dev_AA/fd0", 0))

class SignalsTest(unittest.TestCase):
    """BlueZ's signals drive the poll, faked at the bus; polling is the fallback."""

    def setUp(self):
        self.bt = BluetoothAudio()
        self.bt._available = True
        INLINE.start()
        self.busctl = mock.patch("backend.bluetooth._busctl",
                                 side_effect=lambda *a, **k: busctl_says(phone("Pixel"))).start()
        mock.patch("builtins.print").start()
        self.addCleanup(self.bt._timer.stop)
        self.addCleanup(mock.patch.stopall)

    def started(self, bus):
        with on_bus(bus):
            self.bt.start()
        self.busctl.reset_mock()

    def signal(self, bus):
        bus.slot()
        self.bt._bluez._timer.stop()     # stands in for the debounce running out
        self.bt._bluez._fire()

    def test_subscribes_to_what_bluez_sends(self):
        bus = FakeBus()
        self.started(bus)
        names = {(s[0], s[1], s[3]) for s in bus.subscribed}
        self.assertEqual(names, {("org.bluez", "/", "InterfacesAdded"), ("org.bluez", "/", "InterfacesRemoved"),
                                 ("org.bluez", "", "PropertiesChanged")})

    def test_a_signal_reads_bluez_at_once(self):
        bus = FakeBus()
        self.started(bus)
        self.signal(bus)
        self.busctl.assert_called_once()
        self.assertEqual(self.busctl.call_args.args[-1], "GetManagedObjects")

    def test_signals_in_a_burst_read_it_once(self):
        bus = FakeBus()
        self.started(bus)
        for _ in range(5):
            bus.slot()
        self.assertTrue(self.bt._bluez._timer.isActive())
        self.signal(bus)
        self.busctl.assert_called_once()

    def test_a_signal_during_a_poll_reads_again_after_it(self):
        """That poll may have read just before the change."""
        bus = FakeBus()
        self.started(bus)
        self.bt._busy = True
        self.bt._bluez._fire()
        self.busctl.assert_not_called()
        self.bt._apply(None)
        self.assertTrue(self.bt._bluez._timer.isActive())
        self.signal(bus)
        self.busctl.assert_called_once()

    def test_without_a_bus_it_polls_every_tick(self):
        self.started(None)
        for _ in range(3):
            self.bt._tick()
        self.assertEqual(self.busctl.call_count, 3)

    def test_with_signals_it_polls_only_now_and_then(self):
        self.started(FakeBus())
        for _ in range(SAFETY_TICKS - 1):
            self.bt._tick()
        self.busctl.assert_not_called()
        self.bt._tick()
        self.busctl.assert_called_once()

    def test_a_signal_puts_the_safety_poll_off(self):
        bus = FakeBus()
        self.started(bus)
        for _ in range(SAFETY_TICKS - 1):
            self.bt._tick()
        self.signal(bus)
        self.busctl.reset_mock()
        self.bt._tick()
        self.busctl.assert_not_called()

    def test_with_bluez_down_it_polls_every_tick(self):
        self.started(FakeBus(running=False))
        for _ in range(3):
            self.bt._tick()
        self.assertEqual(self.busctl.call_count, 3)

    def test_bluez_going_away_falls_back_to_the_fast_poll(self):
        bus = FakeBus()
        self.started(bus)
        bus.running = False
        for _ in range(SAFETY_TICKS):
            self.bt._tick()                            # the safety poll notices
        self.busctl.reset_mock()
        for _ in range(3):
            self.bt._tick()
        self.assertEqual(self.busctl.call_count, 3)

    def test_the_position_clock_keeps_ticking_between_polls(self):
        self.started(FakeBus())
        self.bt._player = {"status": "playing"}
        ticks = mock.Mock()
        self.bt.positionChanged.connect(ticks)
        for _ in range(3):
            self.bt._tick()
        self.assertEqual(ticks.call_count, 3)
        self.busctl.assert_not_called()

    def test_pairing_still_times_out_between_polls(self):
        self.started(FakeBus())
        self.bt._pairing_until = 1.0                  # long past
        self.bt._tick()
        self.assertEqual(self.bt._pairing_until, 0.0)

    def test_a_volume_we_set_is_read_back_after_the_ignored_window(self):
        self.bt._state["transport"] = "/org/bluez/hci0/dev_AA/fd0"
        self.bt.setVolume(50)
        self.assertTrue(self.bt._volume_settle.isActive())
        self.assertGreater(self.bt._volume_settle.interval(), 1500)
        self.bt._volume_settle.stop()


class PhoneSeekTest(unittest.TestCase):
    def test_the_real_phone_source_cant_seek(self):
        phone = BluetoothAudio()
        self.assertFalse(phone.canSeek)
        phone.seek(30)                                # does nothing, doesn't raise


if __name__ == "__main__":
    unittest.main()
