"""Off-Pi tests that a crashing Bluetooth poll (backend/bluetooth.py) is logged
once, frees the busy flag, keeps the last state, and lets the next poll run.
BlueZ is faked, and the worker thread runs right where it's started.

    python3 -m unittest tests.test_bluetooth
"""

import json
import subprocess
import time
import unittest
from datetime import date
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


AA = "/org/bluez/hci0/dev_AA"


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
        self.bt._accepted_on_screen(AA)
        self.bt._bluez._timer.stop()
        with mock.patch("backend.bluetooth._busctl", side_effect=busctl):
            for _ in range(2):
                self.bt._tick()
                self.assertFalse(self.bt._busy)
        self.assertEqual(self.bt.deviceName, "Pixel")
        self.assertEqual(len(logged(self.printed)), 1)

    def test_no_bluez_is_the_usual_quiet_blank_state(self):
        self.poll(phone("Pixel"))
        gone = subprocess.CompletedProcess(
            ["busctl"], 1, "", "Call failed: The name org.bluez was not provided by any .service files\n")
        for result in ({"side_effect": FileNotFoundError("busctl")}, {"return_value": gone}):
            with mock.patch("backend.bluetooth._busctl", **result):
                self.bt._tick()
            self.assertFalse(self.bt._busy)
            self.assertFalse(self.bt.adapterPresent)
            self.assertEqual(self.bt.deviceName, "")
        self.assertEqual(logged(self.printed), [])

    def test_a_slow_or_failing_busctl_keeps_the_last_state(self):
        self.poll(phone("Pixel"))
        failed = subprocess.CompletedProcess(["busctl"], 1, "", "Call failed: Connection timed out\n")
        for result in ({"side_effect": subprocess.TimeoutExpired("busctl", 3)}, {"return_value": failed}):
            with mock.patch("backend.bluetooth._busctl", **result):
                self.bt._tick()
            self.assertFalse(self.bt._busy)
            self.assertTrue(self.bt.adapterPresent)
            self.assertEqual(self.bt.deviceName, "Pixel")
        self.poll(phone("Pixel 9"))
        self.assertEqual(self.bt.deviceName, "Pixel 9")


class ParseObjectsTest(unittest.TestCase):
    """The rest of what parse_objects reduces BlueZ's answer to."""

    def test_no_adapter_and_nothing_else(self):
        state = parse_objects({})
        self.assertEqual((state["adapter"], state["device"], state["paired"], state["known"]), (None, None, [], {}))
        self.assertEqual((state["transport"], state["volume"], state["discoverable"]), (None, None, False))

    def test_a_phone_without_a_player_still_names_the_device(self):
        state = parse_objects(phone("Driver"))
        self.assertEqual((state["adapter"], state["device"], state["player"]), ("/org/bluez/hci0", "Driver", None))
        self.assertEqual(state["paired"], [{"path": AA, "name": "Driver", "connected": True,
                                            "address": "AA", "trusted": True}])

    def test_a_paired_phone_not_yet_trusted_stays_listed_as_untrusted(self):
        self.assertFalse(parse_objects(phone("Driver", trusted=False))["paired"][0]["trusted"])

    def test_an_unpaired_phone_is_not_listed(self):
        state = parse_objects(phone("Stranger", paired=False))
        self.assertEqual(state["paired"], [])
        self.assertEqual(state["known"][AA]["name"], "Stranger")      # for the prompt

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


class FakeSettings:
    def __init__(self, **values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class PairingTest(unittest.TestCase):
    """Only what's accepted on screen gets trusted. The agent's BlueZ side is
    tests/test_btagent.py; here BlueZ is the faked busctl, as in the polls above."""

    def setUp(self):
        self.settings = FakeSettings()
        self.bt = BluetoothAudio(settings=self.settings)
        self.objects = phone("Pixel", trusted=False)
        INLINE.start()
        self.busctl = mock.patch("backend.bluetooth._busctl",
                                 side_effect=lambda *a, **k: busctl_says(self.objects)).start()
        mock.patch("builtins.print").start()
        self.addCleanup(mock.patch.stopall)

    def poll(self):
        self.bt._refresh()

    def sets(self):
        return [c.args for c in self.busctl.call_args_list if c.args[0] == "set-property"]

    def accepted(self, path=AA, code=123456):
        """The window opens, the device asks, and Pair gets tapped."""
        self.bt._pairing_until = time.monotonic() + 60
        self.reply = mock.Mock()
        self.reply.accept.return_value = True
        self.bt._agent.confirm(path, code, self.reply)
        self.bt.acceptPairing()
        self.bt._bluez._timer.stop()

    def test_a_paired_device_nobody_accepted_is_left_alone_and_flagged(self):
        self.poll()
        self.assertEqual(self.sets(), [])
        entry = self.bt.paired[0]
        self.assertEqual((entry["name"], entry["trusted"], entry["pairedOn"]), ("Pixel", False, ""))

    def test_a_trusted_phone_is_untouched_listed_and_connectable(self):
        self.objects = phone("Pixel", trusted=True)
        self.poll()
        self.assertEqual(self.sets(), [])
        self.assertTrue(self.bt.paired[0]["trusted"])
        self.assertEqual(self.bt.deviceName, "Pixel")
        self.bt.connectDevice(AA)
        self.assertEqual(self.busctl.call_args.args[-1], "Connect")

    def test_an_accepted_device_is_trusted_and_dated_once(self):
        self.accepted()
        for _ in range(3):
            self.poll()
            self.objects = phone("Pixel", trusted=True)
        self.assertEqual(self.sets(), [("set-property", "org.bluez", AA, "org.bluez.Device1", "Trusted", "b", "true")])
        entry = self.bt.paired[0]
        self.assertTrue(entry["trusted"])
        today = date.today()
        self.assertEqual(entry["pairedOn"], f"{today:%b} {today.day}, {today.year}")
        self.assertEqual(self.bt._accepted, {})

    def test_it_waits_for_the_pairing_to_finish(self):
        self.objects = phone("Pixel", paired=False, trusted=False)
        self.accepted()
        self.poll()
        self.assertEqual(self.sets(), [])
        self.objects = phone("Pixel", trusted=False)
        self.poll()
        self.assertEqual(len(self.sets()), 1)

    def test_a_cancelled_device_is_not_trusted(self):
        self.bt._pairing_until = time.monotonic() + 60
        self.bt._agent.confirm(AA, 1, mock.Mock())
        self.bt.cancelPairing()
        self.poll()
        self.assertEqual(self.sets(), [])

    def test_a_refused_trust_is_tried_again_and_not_dated(self):
        self.accepted()
        def refused(*args, **kw):
            code = 1 if args[0] == "set-property" else 0
            return subprocess.CompletedProcess(["busctl"], code, busctl_says(self.objects).stdout, "")
        with mock.patch("backend.bluetooth._busctl", side_effect=refused):
            self.poll()
        self.assertEqual(self.bt.paired[0]["pairedOn"], "")
        self.assertFalse(self.bt.paired[0]["trusted"])
        self.poll()
        self.assertTrue(self.bt.paired[0]["trusted"])

    def test_an_accepted_device_gets_its_services_before_the_poll_trusts_it(self):
        self.accepted()
        reply = mock.Mock()
        self.bt._agent.authorize_service(AA, "a2dp", reply)
        reply.accept.assert_called_once()

    def test_a_stranger_gets_no_services(self):
        self.poll()
        reply = mock.Mock()
        self.bt._agent.authorize_service(AA, "a2dp", reply)
        reply.reject.assert_called_once()

    def test_an_acceptance_runs_out(self):
        self.accepted()
        self.bt._accepted[AA] = 1.0                   # long past
        self.bt._tick()
        self.assertEqual(self.bt._accepted, {})
        self.assertEqual(self.sets(), [])

    def test_it_polls_fast_while_a_device_waits_for_trust(self):
        self.accepted()
        with mock.patch.object(self.bt._bluez, "live", return_value=True):
            self.poll()
            self.assertEqual(self.bt._ticks_left, 1)
            self.poll()                                 # that one trusted it
            self.assertEqual(self.bt._ticks_left, SAFETY_TICKS)

    def test_requests_only_count_while_the_window_is_open(self):
        reply = mock.Mock()
        self.bt._agent.confirm(AA, 1, reply)
        reply.reject.assert_called_once()
        self.assertFalse(self.bt.pairPending)
        self.bt._pairing_until = time.monotonic() + 60
        self.bt._agent.confirm(AA, 42, mock.Mock())
        self.assertTrue(self.bt.pairPending)
        self.assertEqual(self.bt.pairCode, "000042")
        self.bt.cancelPairing()

    def test_the_prompt_names_the_device_once_a_poll_knows_it(self):
        self.objects = {"/org/bluez/hci0": self.objects["/org/bluez/hci0"]}
        self.poll()
        self.bt._pairing_until = time.monotonic() + 60
        self.bt._agent.confirm("/org/bluez/hci0/dev_AA_BB", 1, mock.Mock())
        self.bt._bluez._timer.stop()
        self.assertEqual((self.bt.pairName, self.bt.pairAddress), ("AA:BB", "AA:BB"))
        changes = mock.Mock()
        self.bt.changed.connect(changes)
        self.objects["/org/bluez/hci0/dev_AA_BB"] = {"org.bluez.Device1": {"Alias": "Pixel", "Paired": False}}
        self.poll()
        self.assertEqual(self.bt.pairName, "Pixel")
        changes.assert_called()
        self.bt.cancelPairing()

    def test_stop_pairing_cancels_the_prompt(self):
        self.poll()
        self.bt._pairing_until = time.monotonic() + 60
        reply = mock.Mock()
        self.bt._agent.confirm(AA, 1, reply)
        self.bt.setPairing(False)
        self.assertFalse(self.bt.pairPending)
        reply.reject.assert_called_once()

    def test_the_window_running_out_cancels_the_prompt(self):
        self.bt._pairing_until = time.monotonic() + 60
        reply = mock.Mock()
        self.bt._agent.confirm(AA, 1, reply)
        self.bt._pairing_until = 1.0
        self.bt._tick()
        self.assertFalse(self.bt.pairPending)
        reply.reject.assert_called_once()

    def test_dates_survive_a_restart(self):
        self.accepted()
        self.poll()
        stored = json.loads(self.settings.values["btPairedDates"])
        self.assertEqual(stored, {"AA": date.today().isoformat()})
        again = BluetoothAudio(settings=self.settings)
        self.objects = phone("Pixel", trusted=True)
        again._refresh()
        self.assertNotEqual(again.paired[0]["pairedOn"], "")

    def test_a_date_is_shown_as_a_date_and_junk_as_none(self):
        self.settings.values["btPairedDates"] = json.dumps({"AA": "2026-10-03"})
        bt = BluetoothAudio(settings=self.settings)
        bt._refresh()
        self.assertEqual(bt.paired[0]["pairedOn"], "Oct 3, 2026")
        self.settings.values["btPairedDates"] = json.dumps({"AA": "soon"})
        bt = BluetoothAudio(settings=self.settings)
        bt._refresh()
        self.assertEqual(bt.paired[0]["pairedOn"], "")

    def test_broken_stored_dates_are_no_dates(self):
        for stored in ("{oops", "[]"):
            self.assertEqual(BluetoothAudio(settings=FakeSettings(btPairedDates=stored))._dates, {})

    def test_without_settings_dates_stay_in_memory(self):
        bt = BluetoothAudio()
        bt._pairing_until = time.monotonic() + 60
        reply = mock.Mock()
        reply.accept.return_value = True
        bt._agent.confirm(AA, 1, reply)
        bt.acceptPairing()
        bt._bluez._timer.stop()
        bt._refresh()
        self.assertNotEqual(bt.paired[0]["pairedOn"], "")

    def test_a_forgotten_devices_date_goes(self):
        self.accepted()
        self.poll()
        self.objects = {"/org/bluez/hci0": self.objects["/org/bluez/hci0"]}
        self.poll()
        self.assertEqual(json.loads(self.settings.values["btPairedDates"]), {})

    def test_bluez_being_down_keeps_the_dates(self):
        self.accepted()
        self.poll()
        self.objects = {}
        self.poll()
        self.assertEqual(list(self.bt._dates), ["AA"])


class AgentReportTest(unittest.TestCase):
    """What Settings is told about the agent."""

    def setUp(self):
        mock.patch("builtins.print").start()
        self.addCleanup(mock.patch.stopall)

    def test_where_theres_no_bluetooth_nothing_nags(self):
        bt = BluetoothAudio()
        bt._available = False
        bt.start()
        self.assertEqual((bt.agentOk, bt.agentProblem), (False, ""))

    def test_on_a_pi_with_no_bus_it_says_so(self):
        bt = BluetoothAudio()
        bt._available = True
        self.addCleanup(bt._timer.stop)
        with on_bus(None):
            bt.start()
        self.assertFalse(bt.agentOk)
        self.assertIn("system bus", bt.agentProblem)

    def test_settings_hears_when_it_changes(self):
        bt = BluetoothAudio()
        changes = mock.Mock()
        bt.changed.connect(changes)
        bt._agent.lost("gone")
        changes.assert_called_once()


class PhoneSeekTest(unittest.TestCase):
    def test_the_real_phone_source_cant_seek(self):
        phone = BluetoothAudio()
        self.assertFalse(phone.canSeek)
        phone.seek(30)                                # does nothing, doesn't raise


if __name__ == "__main__":
    unittest.main()
