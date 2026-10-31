"""Off-Pi tests for backend/btagent.py with the bus faked: what the agent answers
BlueZ, how it registers, and that a failure says why and heals itself. There's
no bus on a Mac, so Qt's own delivery of a call to a slot isn't run here; the
messages are real QDBusMessages though.

    python3 -m unittest tests.test_btagent
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtDBus import QDBusConnection, QDBusMessage, QDBusObjectPath

from backend import btagent, dbus
from backend.btagent import AGENT_PATH, PROMPT_SECONDS, REJECTED, RETRY_SECONDS, PairingAgent
from tests.test_dbus import FakeBus, on_bus

app = QCoreApplication.instance() or QCoreApplication([])

PHONE = "/org/bluez/hci0/dev_AA_BB"


class AgentBus(FakeBus):
    """FakeBus plus what the agent uses of QDBusConnection."""

    def __init__(self, exports=True):
        super().__init__()
        self.exports = exports
        self.exported = []
        self.calls = []              # (message, done, failed, timeout)
        self.sent = []

    def registerObject(self, path, obj, options):
        self.exported.append((path, obj, options))
        return self.exports

    def callWithCallback(self, message, done, failed, timeout):
        self.calls.append((message, done, failed, timeout))
        return True

    def send(self, message):
        self.sent.append(message)
        return True

    def succeed(self):
        self.calls[-1][1](QDBusMessage())

    def fail(self, name, text):
        self.calls[-1][2](SimpleNamespace(name=lambda: name, message=lambda: text))    # PyQt can't build a QDBusError


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def incoming(member, *arguments):
    message = QDBusMessage.createMethodCall(":1.1", AGENT_PATH, "org.bluez.Agent1", member)
    message.setArguments(list(arguments))
    return message


class Base(unittest.TestCase):
    def setUp(self):
        self.open = True
        self.trusted = set()
        self.accepted = []
        self.clock = Clock()
        self.agent = PairingAgent(lambda: self.open, lambda path: path in self.trusted,
                                  self.accepted.append, clock=self.clock)
        self.printed = mock.patch("builtins.print").start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(self.agent._timeout.stop)

    def reply(self, accepted=True):
        reply = mock.Mock()
        reply.accept.return_value = accepted
        return reply


class DecisionTest(Base):
    def test_a_confirmation_shows_the_code_zero_padded(self):
        self.agent.confirm(PHONE, 42, self.reply())
        self.assertTrue(self.agent.pending)
        self.assertEqual((self.agent.device, self.agent.code), (PHONE, "000042"))

    def test_nothing_is_answered_until_the_screen_does(self):
        reply = self.reply()
        self.agent.confirm(PHONE, 1, reply)
        reply.accept.assert_not_called()
        reply.reject.assert_not_called()

    def test_pair_accepts_and_tells_the_owner(self):
        reply = self.reply()
        self.agent.confirm(PHONE, 1, reply)
        self.agent.accept()
        reply.accept.assert_called_once()
        self.assertEqual(self.accepted, [PHONE])
        self.assertFalse(self.agent.pending)

    def test_an_answer_that_didnt_reach_bluez_trusts_nobody(self):
        self.agent.confirm(PHONE, 1, self.reply(accepted=False))
        self.agent.accept()
        self.assertEqual(self.accepted, [])

    def test_cancel_rejects(self):
        reply = self.reply()
        self.agent.confirm(PHONE, 1, reply)
        self.agent.cancel()
        reply.reject.assert_called_once()
        reply.accept.assert_not_called()
        self.assertEqual(self.accepted, [])

    def test_accept_and_cancel_with_nothing_pending_do_nothing(self):
        self.agent.accept()
        self.agent.cancel()
        self.assertEqual(self.accepted, [])

    def test_a_second_request_is_rejected_at_once(self):
        first, second = self.reply(), self.reply()
        self.agent.confirm(PHONE, 1, first)
        self.agent.confirm("/org/bluez/hci0/dev_CC", 2, second)
        second.reject.assert_called_once()
        first.reject.assert_not_called()
        self.assertEqual(self.agent.device, PHONE)

    def test_outside_the_window_everything_is_rejected_unseen(self):
        self.open = False
        for ask in (lambda r: self.agent.confirm(PHONE, 1, r), lambda r: self.agent.authorize(PHONE, r)):
            reply = self.reply()
            ask(reply)
            reply.reject.assert_called_once()
        self.assertFalse(self.agent.pending)

    def test_no_answer_rejects_after_the_timeout(self):
        self.assertEqual(self.agent._timeout.interval(), PROMPT_SECONDS * 1000)
        reply = self.reply()
        self.agent.confirm(PHONE, 1, reply)
        self.assertTrue(self.agent._timeout.isActive())
        self.agent._timed_out()
        reply.reject.assert_called_once()
        self.assertFalse(self.agent.pending)

    def test_an_answer_stops_the_timeout(self):
        self.agent.confirm(PHONE, 1, self.reply())
        self.agent.accept()
        self.assertFalse(self.agent._timeout.isActive())

    def test_a_phone_with_no_screen_gets_a_prompt_with_no_code(self):
        reply = self.reply()
        self.agent.authorize(PHONE, reply)
        self.assertTrue(self.agent.pending)
        self.assertEqual(self.agent.code, "")
        self.agent.accept()
        reply.accept.assert_called_once()
        self.assertEqual(self.accepted, [PHONE])

    def test_services_only_for_trusted_devices(self):
        allowed, refused = self.reply(), self.reply()
        self.trusted.add(PHONE)
        self.agent.authorize_service(PHONE, "uuid", allowed)
        self.agent.authorize_service("/org/bluez/hci0/dev_CC", "uuid", refused)
        allowed.accept.assert_called_once()
        refused.reject.assert_called_once()

    def test_a_service_request_doesnt_wait_behind_a_prompt(self):
        self.trusted.add(PHONE)
        self.agent.confirm("/org/bluez/hci0/dev_CC", 1, self.reply())
        reply = self.reply()
        self.agent.authorize_service(PHONE, "uuid", reply)
        reply.accept.assert_called_once()
        self.assertTrue(self.agent.pending)

    def test_no_pins_or_passkeys(self):
        reply = self.reply()
        self.agent.refuse("a PIN", reply)
        reply.reject.assert_called_once()

    def test_bluez_cancelling_clears_the_prompt_without_an_answer(self):
        reply = self.reply()
        self.agent.confirm(PHONE, 1, reply)
        self.agent.bluez_cancelled()
        self.assertFalse(self.agent.pending)
        self.assertFalse(self.agent._timeout.isActive())
        reply.reject.assert_not_called()

    def test_changes_are_signalled(self):
        changes = mock.Mock()
        self.agent.changed.connect(changes)
        self.agent.confirm(PHONE, 1, self.reply())
        self.agent.cancel()
        self.assertEqual(changes.call_count, 2)


class GlueTest(Base):
    """Calls as Qt would deliver them, down to what goes back on the bus."""

    def setUp(self):
        super().setUp()
        self.bus = AgentBus()
        self.glue = btagent._Agent1(self.agent, self.bus)
        self.path = QDBusObjectPath(PHONE)

    def test_it_says_its_the_agent_interface(self):
        meta = self.glue.metaObject()
        info = meta.classInfo(meta.indexOfClassInfo("D-Bus Interface"))
        self.assertEqual(info.value(), "org.bluez.Agent1")

    def test_the_slots_have_agent1s_signatures(self):
        meta = self.glue.metaObject()
        have = {bytes(meta.method(i).methodSignature()).decode()
                for i in range(meta.methodOffset(), meta.methodCount())}
        o, m = "QDBusObjectPath", "QDBusMessage"
        self.assertEqual(have, {"Release()", "Cancel()", f"RequestConfirmation({o},uint,{m})",
                                f"RequestAuthorization({o},{m})", f"AuthorizeService({o},QString,{m})",
                                f"DisplayPasskey({o},uint,ushort,{m})", f"DisplayPinCode({o},QString,{m})",
                                f"RequestPinCode({o},{m})", f"RequestPasskey({o},{m})"})

    def test_pair_sends_an_empty_reply(self):
        message = incoming("RequestConfirmation", self.path, 123456)
        self.glue.RequestConfirmation(self.path, 123456, message)
        self.assertTrue(message.isDelayedReply())
        self.assertEqual(self.bus.sent, [])
        self.agent.accept()
        self.assertEqual(self.bus.sent[0].type(), QDBusMessage.MessageType.ReplyMessage)
        self.assertEqual(self.bus.sent[0].arguments(), [])

    def test_cancel_sends_rejected(self):
        self.glue.RequestAuthorization(self.path, incoming("RequestAuthorization", self.path))
        self.agent.cancel()
        self.assertEqual(self.bus.sent[0].type(), QDBusMessage.MessageType.ErrorMessage)
        self.assertEqual(self.bus.sent[0].errorName(), REJECTED)

    def test_a_plain_string_path_works_too(self):
        self.glue.RequestConfirmation(PHONE, 1, incoming("RequestConfirmation", PHONE, 1))
        self.assertEqual(self.agent.device, PHONE)

    def test_authorize_service_of_a_stranger_is_rejected(self):
        self.glue.AuthorizeService(self.path, "uuid", incoming("AuthorizeService", self.path, "uuid"))
        self.assertEqual(self.bus.sent[0].errorName(), REJECTED)

    def test_legacy_methods_are_all_rejected(self):
        self.glue.RequestPinCode(self.path, incoming("RequestPinCode", self.path))
        self.glue.RequestPasskey(self.path, incoming("RequestPasskey", self.path))
        self.glue.DisplayPasskey(self.path, 1, 0, incoming("DisplayPasskey", self.path))
        self.glue.DisplayPinCode(self.path, "0000", incoming("DisplayPinCode", self.path))
        self.assertEqual([m.errorName() for m in self.bus.sent], [REJECTED] * 4)

    def test_a_crash_in_the_logic_rejects_and_doesnt_escape(self):
        self.agent._allowed = mock.Mock(side_effect=TypeError("boom"))
        self.glue.RequestConfirmation(self.path, 1, incoming("RequestConfirmation", self.path, 1))
        self.assertEqual(self.bus.sent[0].errorName(), REJECTED)

    def test_a_failed_send_doesnt_escape(self):
        self.bus.send = mock.Mock(side_effect=RuntimeError("gone"))
        self.glue.RequestConfirmation(self.path, 1, incoming("RequestConfirmation", self.path, 1))
        self.agent.accept()
        self.assertEqual(self.accepted, [])

    def test_cancel_and_release_arrive(self):
        self.glue.RequestConfirmation(self.path, 1, incoming("RequestConfirmation", self.path, 1))
        self.glue.Cancel()
        self.assertFalse(self.agent.pending)
        self.agent._registered = True
        self.glue.Release()
        self.assertFalse(self.agent.registered)


class RegisterTest(Base):
    def started(self, bus):
        with on_bus(bus):
            self.agent.start()

    def registered(self, bus):
        self.started(bus)
        bus.succeed()
        bus.succeed()
        return bus

    def retry(self, bus, seconds=RETRY_SECONDS):
        self.clock.now += seconds
        with on_bus(bus):
            self.agent.tick()

    def test_it_exports_itself_then_registers_and_asks_to_be_default(self):
        bus = AgentBus()
        self.started(bus)
        (path, obj, options), = bus.exported
        self.assertEqual(path, "/org/baja/agent")
        self.assertIsInstance(obj, btagent._Agent1)
        self.assertEqual(options, QDBusConnection.RegisterOption.ExportAllSlots)

        call = bus.calls[0][0]
        self.assertEqual((call.service(), call.path(), call.interface(), call.member()),
                         ("org.bluez", "/org/bluez", "org.bluez.AgentManager1", "RegisterAgent"))
        self.assertEqual(call.arguments(), ["/org/baja/agent", "DisplayYesNo"])
        self.assertFalse(self.agent.registered)

        bus.succeed()
        call = bus.calls[1][0]
        self.assertEqual(call.member(), "RequestDefaultAgent")
        self.assertEqual(call.arguments(), ["/org/baja/agent"])
        self.assertFalse(self.agent.registered)

        bus.succeed()
        self.assertEqual((self.agent.registered, self.agent.problem), (True, ""))

    def test_the_path_goes_out_as_an_object_path(self):
        """arguments() reads it back as a str either way, so catch it going in."""
        bus = AgentBus()
        with mock.patch("backend.btagent.QDBusObjectPath", wraps=QDBusObjectPath) as path:
            self.started(bus)
        path.assert_called_once_with(AGENT_PATH)

    def test_it_never_waits_on_the_bus(self):
        bus = AgentBus()
        self.started(bus)
        self.assertEqual(bus.calls[0][3], btagent.CALL_TIMEOUT_MS)
        self.assertLessEqual(btagent.CALL_TIMEOUT_MS, 10000)

    def test_no_bus_gives_a_reason_and_doesnt_raise(self):
        self.started(None)
        self.assertFalse(self.agent.registered)
        self.assertIn("system bus", self.agent.problem)

    def test_no_qtdbus_gives_a_reason(self):
        with mock.patch.object(dbus, "QDBusConnection", None):
            self.agent.start()
        self.assertIn("QtDBus", self.agent.problem)

    def test_a_refused_export_gives_a_reason(self):
        bus = AgentBus(exports=False)
        self.started(bus)
        self.assertIn("on the bus", self.agent.problem)
        self.assertEqual(bus.calls, [])

    def test_an_error_from_register_agent_gives_its_reason(self):
        bus = AgentBus()
        self.started(bus)
        bus.fail("org.freedesktop.DBus.Error.ServiceUnknown", "org.bluez isn't there")
        self.assertFalse(self.agent.registered)
        self.assertIn("org.bluez isn't there", self.agent.problem)

    def test_an_error_from_request_default_agent_gives_its_reason(self):
        bus = AgentBus()
        self.started(bus)
        bus.succeed()
        bus.fail("org.bluez.Error.DoesNotExist", "No such agent")
        self.assertFalse(self.agent.registered)
        self.assertIn("No such agent", self.agent.problem)

    def test_an_exception_while_registering_gives_a_reason(self):
        bus = AgentBus()
        bus.callWithCallback = mock.Mock(side_effect=TypeError("boom"))
        self.started(bus)
        self.assertIn("boom", self.agent.problem)
        self.assertFalse(self.agent._calling)

    def test_a_call_that_cant_be_queued_gives_a_reason(self):
        bus = AgentBus()
        bus.callWithCallback = mock.Mock(return_value=False)
        self.started(bus)
        self.assertIn("RegisterAgent", self.agent.problem)
        self.assertFalse(self.agent._calling)

    def test_a_failure_is_retried_after_the_wait_and_clears(self):
        bus = AgentBus()
        self.started(bus)
        bus.fail("org.bluez.Error.Failed", "nope")
        self.retry(bus, RETRY_SECONDS - 1)
        self.assertEqual(len(bus.calls), 1)
        self.assertNotEqual(self.agent.problem, "")           # no flicker while it tries
        self.retry(bus, 1)
        self.assertEqual(len(bus.calls), 2)
        bus.succeed()
        bus.succeed()
        self.assertEqual((self.agent.registered, self.agent.problem), (True, ""))

    def test_a_late_first_bus_is_found(self):
        self.started(None)
        bus = AgentBus()
        self.retry(bus)
        self.assertEqual(len(bus.calls), 1)

    def test_it_exports_only_once(self):
        bus = AgentBus()
        self.started(bus)
        bus.fail("org.bluez.Error.Failed", "nope")
        self.retry(bus)
        self.assertEqual(len(bus.exported), 1)

    def test_no_second_try_while_one_is_running(self):
        bus = AgentBus()
        self.started(bus)
        self.retry(bus, 100)
        self.assertEqual(len(bus.calls), 1)

    def test_nothing_happens_before_start(self):
        self.clock.now += 100
        bus = AgentBus()
        with on_bus(bus):
            self.agent.tick()
        self.assertEqual(bus.exported, [])

    def test_an_agent_bluez_already_has_goes_on_to_default(self):
        bus = AgentBus()
        self.started(bus)
        bus.fail("org.bluez.Error.AlreadyExists", "Already Exists")
        self.assertEqual(bus.calls[-1][0].member(), "RequestDefaultAgent")
        self.assertEqual(self.agent.problem, "")

    def test_nothing_nags_or_logs_on_a_healthy_start_until_it_is_up(self):
        bus = AgentBus()
        self.started(bus)
        self.assertEqual(self.agent.problem, "")

    def test_release_says_so_and_registers_again_after_the_wait(self):
        bus = self.registered(AgentBus())
        self.agent.confirm(PHONE, 1, self.reply())
        self.agent.lost("BlueZ dropped the pairing agent")
        self.assertEqual((self.agent.registered, self.agent.pending), (False, False))
        self.assertIn("dropped", self.agent.problem)
        self.retry(bus, RETRY_SECONDS - 1)
        self.assertEqual(len(bus.calls), 2)
        self.retry(bus, 1)
        self.assertEqual(len(bus.calls), 3)
        bus.succeed()
        bus.succeed()
        self.assertEqual((self.agent.registered, self.agent.problem), (True, ""))

    def test_a_ticking_healthy_agent_does_nothing(self):
        bus = self.registered(AgentBus())
        self.retry(bus, 1000)
        self.assertEqual(len(bus.calls), 2)

    def test_it_watches_for_bluez_going_away(self):
        bus = self.registered(AgentBus())
        self.assertEqual(bus.subscribed, [("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                           "org.freedesktop.DBus", "NameOwnerChanged")])

    def owner_changed(self, *names):
        message = QDBusMessage.createSignal("/org/freedesktop/DBus", "org.freedesktop.DBus", "NameOwnerChanged")
        message.setArguments(list(names))
        return message

    def test_a_bluetoothd_crash_counts_as_being_dropped(self):
        bus = self.registered(AgentBus())
        bus.slot(self.owner_changed("org.bluez", ":1.5", ""))
        self.assertFalse(self.agent.registered)
        self.assertIn("bluetoothd", self.agent.problem)

    def test_other_names_changing_are_ignored(self):
        bus = self.registered(AgentBus())
        bus.slot(self.owner_changed("org.freedesktop.NetworkManager", ":1.5", ""))
        self.assertTrue(self.agent.registered)

    def test_changes_are_signalled_once_each(self):
        changes = mock.Mock()
        self.agent.changed.connect(changes)
        bus = AgentBus()
        self.started(bus)
        bus.fail("org.bluez.Error.Failed", "nope")
        self.retry(bus)
        bus.fail("org.bluez.Error.Failed", "nope")
        self.assertEqual(changes.call_count, 1)


if __name__ == "__main__":
    unittest.main()
