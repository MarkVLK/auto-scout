#!/usr/bin/env python3
"""External dog-detection event bridge for phase-1 compatibility."""

import json
from datetime import datetime, timezone
from pathlib import Path

from config_utils import load_scout_config


class DogDetectionModule:
    """Normalize external detection events and persist them to companion storage."""

    def __init__(self, config_path=None):
        try:
            import rospy
            from std_msgs.msg import String
        except ImportError as exc:
            raise SystemExit("Dog detection bridge requires ROS Python packages: {}".format(exc))

        from auto_scout.site_config import load_site_config, scout_runtime_topic

        self.rospy = rospy
        self.String = String
        rospy.init_node("dog_detection_module", anonymous=False)
        site_path = rospy.get_param("~site_file", None)
        self.config, self.config_path = load_scout_config(config_path)
        self.site_config, self.site_path = load_site_config(site_path)
        self.current_room = "unknown"
        self.detection_active = False
        self.last_detection = None

        dog_config = self.config.get("dog_search", {})
        storage_config = self.config.get("storage", {})

        self.external_topic = dog_config.get(
            "external_detection_topic",
            scout_runtime_topic(self.site_config, self.config, "vendor_dog_detection", "/scout/dog_detection_external"),
        )
        self.event_dir = Path(storage_config.get("companion_event_dir", "/srv/auto-scout/events"))
        self.event_dir.mkdir(parents=True, exist_ok=True)

        self.publisher = rospy.Publisher("/scout/dog_detection", String, queue_size=1)
        self.subscriber = rospy.Subscriber(self.external_topic, String, self.external_detection_callback, queue_size=1)

    def set_room(self, room_name):
        self.current_room = room_name

    def start_detection_for_room(self, room_name):
        self.current_room = room_name
        self.detection_active = True

    def stop_detection(self):
        self.detection_active = False

    def external_detection_callback(self, msg):
        if not self.detection_active:
            return

        try:
            payload = json.loads(msg.data)
        except ValueError:
            payload = {"detected": True, "raw": msg.data}

        detected = payload.get("dog_detected", payload.get("detected", True))
        if not detected:
            return

        event = {
            "detected": True,
            "room": payload.get("room", self.current_room),
            "confidence": payload.get("confidence", 1.0),
            "method": payload.get("method", "external_event"),
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        self.last_detection = event
        self._write_event(event)
        self.publisher.publish(json.dumps(event, sort_keys=True))

    def _write_event(self, event):
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = self.event_dir / "dog-detection-{}.json".format(timestamp)
        with target.open("w", encoding="utf-8") as handle:
            json.dump(event, handle, indent=2, sort_keys=True)
            handle.write("\n")


def main():
    module = DogDetectionModule()
    module.rospy.spin()


if __name__ == "__main__":
    main()
