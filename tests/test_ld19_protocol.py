"""Unit tests for LD19 packet parsing and scan assembly."""

import math
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ld19_protocol import LD19ScanAssembler
from ld19_protocol import parse_ld19_packet


TRANSCRIPT_PACKET = bytes.fromhex(
    "54 2c 0c 0e 30 07"
    " 97 00 ff 96 00 ff 96 00 ff 96 00 ff"
    " 95 00 ff 95 00 ff 94 00 ff 94 00 ff"
    " 93 00 ff 91 00 ff 90 00 ff 8f 00 ff"
    " 3d 0a 2a 6d cb"
)


def build_packet(start_angle_hundredths, end_angle_hundredths, distance_millimeters):
    payload = bytearray()
    payload.extend([0x54, 0x2C])
    payload.extend((0x0C, 0x0E))
    payload.extend((start_angle_hundredths & 0xFF, (start_angle_hundredths >> 8) & 0xFF))
    for _ in range(12):
        payload.extend((distance_millimeters & 0xFF, (distance_millimeters >> 8) & 0xFF, 0x20))
    payload.extend((end_angle_hundredths & 0xFF, (end_angle_hundredths >> 8) & 0xFF))
    payload.extend((0x00, 0x00, 0x00))
    return bytes(payload)


class LD19ProtocolTest(unittest.TestCase):
    """Validate transcript-based packet parsing and scan assembly."""

    def test_parse_transcript_packet(self):
        parsed = parse_ld19_packet(TRANSCRIPT_PACKET)

        self.assertIsNotNone(parsed)
        self.assertAlmostEqual(parsed["start_angle_degrees"], 18.40, places=2)
        self.assertAlmostEqual(parsed["end_angle_degrees"], 26.21, places=2)
        self.assertEqual(len(parsed["points"]), 12)
        self.assertAlmostEqual(parsed["points"][0]["distance_meters"], 0.151, places=3)
        self.assertAlmostEqual(parsed["points"][-1]["angle_degrees"], 26.21, places=2)

    def test_scan_assembler_publishes_completed_scan_on_wrap(self):
        assembler = LD19ScanAssembler(
            angle_min=0.0,
            angle_max=(2.0 * math.pi),
            range_min=0.02,
            range_max=12.0,
            invert_scan=False,
        )

        first = parse_ld19_packet(build_packet(100, 1200, 1000))
        second = parse_ld19_packet(build_packet(1300, 2400, 1200))
        wrapped = parse_ld19_packet(build_packet(50, 1100, 800))

        self.assertIsNone(assembler.add_packet(first))
        self.assertIsNone(assembler.add_packet(second))
        completed = assembler.add_packet(wrapped)

        self.assertIsNotNone(completed)
        self.assertEqual(len(completed["ranges"]), 360)
        self.assertTrue(any(abs(item - 1.0) < 1e-6 for item in completed["ranges"] if item != float("inf")))
        self.assertTrue(any(abs(item - 1.2) < 1e-6 for item in completed["ranges"] if item != float("inf")))


if __name__ == "__main__":
    unittest.main()
