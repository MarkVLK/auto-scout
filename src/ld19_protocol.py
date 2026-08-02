#!/usr/bin/env python
"""LD19 packet parsing helpers that are reusable from tests and runtime nodes."""

import math
import struct


LD19_HEADER = 0x54
LD19_VER_LEN = 0x2C
LD19_PACKET_LENGTH = 47
LD19_POINTS_PER_PACKET = 12

# The LD19 trailer byte is a CRC8 over the preceding 46 bytes:
# polynomial 0x4D, initial value 0x00, non-reflected, no final XOR.
# Verified against the captured bring-up packet in tests/test_ld19_protocol.py.
LD19_CRC_POLYNOMIAL = 0x4D


def _build_crc_table(polynomial):
    table = []
    for index in range(256):
        value = index
        for _ in range(8):
            if value & 0x80:
                value = ((value << 1) ^ polynomial) & 0xFF
            else:
                value = (value << 1) & 0xFF
        table.append(value)
    return table


LD19_CRC_TABLE = _build_crc_table(LD19_CRC_POLYNOMIAL)


def _byte_at(data, index):
    """Return ``data[index]`` as an int under both Python 2 and Python 3.

    Indexing ``bytes`` yields a one-character str on Python 2, which the Scout
    still runs. Normalizing here keeps the parser correct whether the caller
    passes ``bytes`` or ``bytearray``.
    """
    value = data[index]
    if isinstance(value, int):
        return value
    return ord(value)


def ld19_checksum(data, length=LD19_PACKET_LENGTH - 1):
    """Return the LD19 CRC8 over the first ``length`` bytes of ``data``."""
    crc = 0
    for index in range(length):
        crc = LD19_CRC_TABLE[(crc ^ _byte_at(data, index)) & 0xFF]
    return crc


def is_valid_ld19_packet(packet):
    """Return whether ``packet`` has a valid header, version byte, and CRC."""
    if len(packet) < LD19_PACKET_LENGTH:
        return False
    if _byte_at(packet, 0) != LD19_HEADER or _byte_at(packet, 1) != LD19_VER_LEN:
        return False
    return ld19_checksum(packet) == _byte_at(packet, LD19_PACKET_LENGTH - 1)


def normalize_angle_degrees(angle_degrees):
    """Normalize an angle into ``[0, 360)`` degrees."""
    return angle_degrees % 360.0


def interpolate_angle_degrees(start_angle, end_angle, point_index, point_count=LD19_POINTS_PER_PACKET):
    """Interpolate a point angle across the packet span, handling wrap-around."""
    if point_count <= 1:
        return normalize_angle_degrees(start_angle)

    span = end_angle - start_angle
    if span < 0:
        span += 360.0
    step = span / float(point_count - 1)
    return normalize_angle_degrees(start_angle + (step * point_index))


def parse_ld19_packet(packet, verify_checksum=True):
    """Parse one LD19 packet and return the decoded points or ``None``.

    A failed CRC returns ``None``. Corrupted range data must never reach the
    costmap or the safety filter, and the driver's byte-wise resync makes a
    false header lock likely enough that the CRC is the only real defence.
    """
    if verify_checksum:
        if not is_valid_ld19_packet(packet):
            return None
    else:
        if len(packet) < LD19_PACKET_LENGTH:
            return None
        if _byte_at(packet, 0) != LD19_HEADER or _byte_at(packet, 1) != LD19_VER_LEN:
            return None

    raw = bytes(bytearray(packet[:LD19_PACKET_LENGTH]))

    # The LD19 reports rotor speed directly in degrees per second.
    speed_degrees_per_second = float(struct.unpack("<H", raw[2:4])[0])
    start_angle_degrees = struct.unpack("<H", raw[4:6])[0] / 100.0
    end_angle_degrees = struct.unpack("<H", raw[42:44])[0] / 100.0
    timestamp = struct.unpack("<H", raw[44:46])[0]

    points = []
    for index in range(LD19_POINTS_PER_PACKET):
        offset = 6 + (index * 3)
        distance_millimeters = struct.unpack("<H", raw[offset : offset + 2])[0]
        angle_degrees = interpolate_angle_degrees(
            start_angle_degrees,
            end_angle_degrees,
            index,
            LD19_POINTS_PER_PACKET,
        )
        points.append(
            {
                "angle_degrees": angle_degrees,
                "angle_radians": math.radians(angle_degrees),
                "distance_meters": distance_millimeters / 1000.0,
                "intensity": float(_byte_at(raw, offset + 2)),
            }
        )

    return {
        "speed_degrees_per_second": speed_degrees_per_second,
        "start_angle_degrees": start_angle_degrees,
        "end_angle_degrees": end_angle_degrees,
        "timestamp": timestamp,
        "points": points,
    }


class LD19ScanAssembler(object):
    """Accumulate LD19 packets into a single LaserScan revolution."""

    def __init__(self, angle_min=0.0, angle_max=(2.0 * math.pi), range_min=0.02, range_max=12.0, invert_scan=False):
        self.angle_min = angle_min
        self.angle_max = angle_max
        self.range_min = range_min
        self.range_max = range_max
        self.invert_scan = invert_scan
        self.angle_increment = math.radians(1.0)
        self.reset()

    def reset(self):
        self._scan_data = {}
        self._last_start_angle = None

    def _scan_size(self):
        return max(1, int(round((self.angle_max - self.angle_min) / self.angle_increment)))

    def _angle_index(self, angle_radians):
        index = int((angle_radians - self.angle_min) / self.angle_increment)
        size = self._scan_size()
        if self.invert_scan:
            index = (size - 1) - index
        return index

    def _build_scan(self):
        size = self._scan_size()
        ranges = [float("inf")] * size
        intensities = [0.0] * size

        for point in self._scan_data.values():
            index = self._angle_index(point["angle_radians"])
            if 0 <= index < size:
                ranges[index] = point["distance_meters"]
                intensities[index] = point["intensity"]

        return {
            "angle_increment": self.angle_increment,
            "ranges": ranges,
            "intensities": intensities,
            "point_count": len(self._scan_data),
        }

    def add_packet(self, packet_data):
        """Add one parsed packet and return a completed scan dict on wrap-around."""
        completed_scan = None
        start_angle = packet_data["start_angle_degrees"]
        if self._last_start_angle is not None and start_angle < self._last_start_angle and self._scan_data:
            completed_scan = self._build_scan()
            self.reset()

        self._last_start_angle = start_angle
        for point in packet_data["points"]:
            if self.range_min <= point["distance_meters"] <= self.range_max:
                angle_key = int(normalize_angle_degrees(point["angle_degrees"])) % 360
                self._scan_data[angle_key] = point
        return completed_scan
