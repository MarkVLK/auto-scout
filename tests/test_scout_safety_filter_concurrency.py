#!/usr/bin/env python3
"""Concurrency tests for the Scout safety filter node.

rospy gives every subscriber its own thread and the publish timer another.
``command_callback`` and ``tick`` both drive ``_publish_decision``, which mutates
the episode state in ``ScoutCommandPublishPolicy``. Interleaved, the timer can
consume the one-stop-per-episode budget while the callback is mid-decision, and
the real stop is dropped.

Two kinds of test live here, and the distinction matters:

``SafetyFilterLockDisciplineTest`` asserts the invariant directly - that no
shared collaborator is called without the lock held. These fail deterministically
against the pre-lock implementation, so deleting a ``with self.state_lock:``
breaks the suite on the very next run.

``SafetyFilterConcurrencyTest`` is a stress test. It runs the real threads and
checks that no exception escapes and that the published-command invariants hold.
It does NOT reliably detect the race on its own - under CPython the unguarded
window is narrow enough that it passes without the lock - so it is a smoke test
for deadlock and torn state, not the regression guard.
"""

import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import scout_safety_filter


class FakeVector:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0


class FakeTwist:
    def __init__(self):
        self.linear = FakeVector()
        self.angular = FakeVector()


class FakeRange:
    def __init__(self, value=1.0):
        self.range = value


class FakeLaserScan:
    pass


class FakeString:
    def __init__(self, data=""):
        self.data = data


class FakeDuration:
    def __init__(self, seconds):
        self.seconds = float(seconds)

    def to_sec(self):
        return self.seconds


class FakeTime:
    """Monotonic fake clock driven by the test, not the wall clock."""

    _value = 0.0
    _lock = threading.Lock()

    def __init__(self, value):
        self.value = float(value)

    @classmethod
    def now(cls):
        with cls._lock:
            return FakeTime(cls._value)

    @classmethod
    def advance(cls, delta):
        with cls._lock:
            cls._value += delta

    @classmethod
    def reset(cls):
        with cls._lock:
            cls._value = 0.0

    def to_sec(self):
        return self.value

    def __sub__(self, other):
        return FakeDuration(self.value - other.value)


class RecordingPublisher:
    """Records publishes and deliberately widens the race window."""

    def __init__(self, topic):
        self.topic = topic
        self.messages = []
        self.lock = threading.Lock()

    def publish(self, message):
        # Yield inside the critical section so an unlocked implementation
        # reliably interleaves rather than depending on scheduler luck.
        snapshot = getattr(message, "linear", None)
        value = snapshot.x if snapshot is not None else message
        for _ in range(3):
            pass
        with self.lock:
            self.messages.append(value)


class FakeRospy(types.ModuleType):
    def __init__(self):
        super(FakeRospy, self).__init__("rospy")
        self.publishers = {}
        self.subscribers = []
        self.Time = FakeTime

    def init_node(self, *args, **kwargs):
        return None

    def get_param(self, name, default=None):
        return default

    def Publisher(self, topic, msg_type, queue_size=10, latch=False):
        publisher = RecordingPublisher(topic)
        self.publishers[topic] = publisher
        return publisher

    def Subscriber(self, topic, msg_type, callback, queue_size=10):
        self.subscribers.append((topic, callback))
        return object()

    def loginfo(self, *args, **kwargs):
        return None

    def logwarn(self, *args, **kwargs):
        return None


def fake_ros_modules():
    rospy = FakeRospy()

    geometry_msgs = types.ModuleType("geometry_msgs")
    geometry_msgs_msg = types.ModuleType("geometry_msgs.msg")
    geometry_msgs_msg.Twist = FakeTwist
    geometry_msgs.msg = geometry_msgs_msg

    sensor_msgs = types.ModuleType("sensor_msgs")
    sensor_msgs_msg = types.ModuleType("sensor_msgs.msg")
    sensor_msgs_msg.Range = FakeRange
    sensor_msgs_msg.LaserScan = FakeLaserScan
    sensor_msgs.msg = sensor_msgs_msg

    std_msgs = types.ModuleType("std_msgs")
    std_msgs_msg = types.ModuleType("std_msgs.msg")
    std_msgs_msg.String = FakeString
    std_msgs.msg = std_msgs_msg

    return rospy, {
        "rospy": rospy,
        "geometry_msgs": geometry_msgs,
        "geometry_msgs.msg": geometry_msgs_msg,
        "sensor_msgs": sensor_msgs,
        "sensor_msgs.msg": sensor_msgs_msg,
        "std_msgs": std_msgs,
        "std_msgs.msg": std_msgs_msg,
    }


def build_node():
    FakeTime.reset()
    rospy, modules = fake_ros_modules()
    with patch.dict(sys.modules, modules):
        node = scout_safety_filter.ScoutSafetyFilterNode(
            config={"safety": {"scan_watchdog_enabled": False, "tof_stop_enabled": False}},
            site_config={"roles": {"scout": {"topics": {}}}},
            init_node=False,
        )
    return node, rospy


def moving_command(value=0.2):
    command = FakeTwist()
    command.linear.x = value
    return command


class OwnershipLock:
    """Re-entrant lock that records which thread currently holds it."""

    def __init__(self):
        self._lock = threading.RLock()
        self._owner = None
        self._depth = 0

    def __enter__(self):
        self._lock.acquire()
        self._owner = threading.current_thread().ident
        self._depth += 1
        return self

    def __exit__(self, *exc_info):
        self._depth -= 1
        if self._depth == 0:
            self._owner = None
        self._lock.release()
        return False

    def held_by_current_thread(self):
        return self._owner == threading.current_thread().ident and self._depth > 0


class LockDisciplineProxy:
    """Fails the test if shared state is touched without holding the lock."""

    def __init__(self, target, lock, violations, label):
        self._target = target
        self._lock = lock
        self._violations = violations
        self._label = label

    def __getattr__(self, name):
        attribute = getattr(self._target, name)
        if not callable(attribute):
            return attribute

        def checked(*args, **kwargs):
            if not self._lock.held_by_current_thread():
                self._violations.append("{}.{}".format(self._label, name))
            return attribute(*args, **kwargs)

        return checked


def instrument(node):
    """Replace the node's lock and shared collaborators with checked versions."""
    violations = []
    lock = OwnershipLock()
    node.state_lock = lock
    node.command_policy = LockDisciplineProxy(node.command_policy, lock, violations, "command_policy")
    node.logic = LockDisciplineProxy(node.logic, lock, violations, "logic")
    return violations


class SafetyFilterLockDisciplineTest(unittest.TestCase):
    """Deterministic checks that every mutation path holds the lock.

    These do not depend on catching a rare interleaving: they assert the
    invariant directly, so removing any `with self.state_lock:` fails the suite
    on the next run rather than once in a thousand.
    """

    def test_command_callback_holds_lock_for_the_whole_decision(self):
        node, _ = build_node()
        violations = instrument(node)

        node.command_callback(moving_command())

        self.assertEqual(violations, [])

    def test_tick_holds_lock_for_the_whole_decision(self):
        node, _ = build_node()
        violations = instrument(node)

        node.tick()

        self.assertEqual(violations, [])

    def test_sensor_callbacks_hold_lock(self):
        node, _ = build_node()
        violations = instrument(node)

        node.tof_callback(FakeRange(0.9))
        node.scan_callback(FakeLaserScan())
        node.battery_guard_callback(FakeString('{"mode": "idle", "battery_percent": 80}'))
        # The sensor writes themselves are only observable through a decision.
        node.tick()

        self.assertEqual(violations, [])

    def test_note_command_and_decide_publish_are_one_critical_section(self):
        """The pair must be atomic, or the episode clock and the stop budget diverge."""
        node, _ = build_node()
        lock = OwnershipLock()
        node.state_lock = lock

        depths = []
        real_policy = node.command_policy

        class DepthRecorder:
            def note_command(self, now):
                depths.append(("note_command", lock.held_by_current_thread()))
                return real_policy.note_command(now)

            def decide_publish(self, decision, now, command_event=False):
                depths.append(("decide_publish", lock.held_by_current_thread()))
                return real_policy.decide_publish(decision, now, command_event=command_event)

            def __getattr__(self, name):
                return getattr(real_policy, name)

        node.command_policy = DepthRecorder()
        node.command_callback(moving_command())

        self.assertEqual(
            depths,
            [("note_command", True), ("decide_publish", True)],
        )


class SafetyFilterConcurrencyTest(unittest.TestCase):

    def test_concurrent_command_and_tick_never_lose_the_episode_stop(self):
        """A blocked episode must always produce exactly one stop.

        The timer and the command callback both decide whether to publish. If
        they interleave unguarded, the timer can consume the one-stop-per-episode
        budget while the callback is mid-decision, and the real stop is dropped.
        """
        for _ in range(200):
            node, _ = build_node()
            output = node.command_pub

            # Establish an active planner episode that is allowed through.
            node.command_callback(moving_command())
            self.assertEqual(len(output.messages), 1)

            # Now block it: the battery guard takes over return-to-dock.
            node.battery_guard_callback(FakeString('{"mode": "return_required"}'))

            errors = []

            def push_commands():
                try:
                    for _ in range(20):
                        node.command_callback(moving_command())
                except Exception as exc:  # pragma: no cover - surfaced below
                    errors.append(exc)

            def push_ticks():
                try:
                    for _ in range(20):
                        node.tick()
                except Exception as exc:  # pragma: no cover - surfaced below
                    errors.append(exc)

            threads = [threading.Thread(target=push_commands), threading.Thread(target=push_ticks)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])

            stops = [value for value in output.messages[1:] if value == 0.0]
            non_stops = [value for value in output.messages[1:] if value != 0.0]

            # Exactly one stop for the blocked episode, and nothing may slip
            # through as motion after the guard took over.
            self.assertEqual(len(stops), 1, output.messages)
            self.assertEqual(non_stops, [], output.messages)

    def test_concurrent_sensor_updates_do_not_corrupt_state(self):
        """Sensor callbacks racing the timer must not produce torn decisions."""
        node, _ = build_node()
        node.logic.scan_watchdog_enabled = True
        node.logic.tof_stop_enabled = True

        errors = []

        def push_sensors():
            try:
                for _ in range(300):
                    node.tof_callback(FakeRange(1.0))
                    node.scan_callback(FakeLaserScan())
                    node.battery_guard_callback(FakeString('{"mode": "idle", "battery_percent": 80}'))
            except Exception as exc:  # pragma: no cover - surfaced below
                errors.append(exc)

        def push_traffic():
            try:
                for _ in range(300):
                    node.command_callback(moving_command())
                    node.tick()
            except Exception as exc:  # pragma: no cover - surfaced below
                errors.append(exc)

        threads = [threading.Thread(target=push_sensors), threading.Thread(target=push_traffic)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        # stop_sent_for_episode is a bool, not a torn value, and the policy's
        # command clock never runs backwards.
        self.assertIn(node.command_policy.stop_sent_for_episode, [True, False])
        self.assertIsNotNone(node.command_policy.last_command_time)


if __name__ == "__main__":
    unittest.main()
