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
from ld19_protocol import is_valid_ld19_packet
from ld19_protocol import ld19_checksum
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
    payload.extend((0x00, 0x00))
    payload.append(ld19_checksum(payload))
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

    def test_transcript_packet_checksum_matches_captured_trailer(self):
        """The captured bring-up packet pins the CRC polynomial."""
        self.assertEqual(ld19_checksum(TRANSCRIPT_PACKET), TRANSCRIPT_PACKET[46])
        self.assertTrue(is_valid_ld19_packet(TRANSCRIPT_PACKET))

    def test_rejects_packet_with_corrupted_payload(self):
        """A flipped payload byte must not reach the caller as range data."""
        for corrupt_index in [6, 20, 41, 44]:
            corrupted = bytearray(TRANSCRIPT_PACKET)
            corrupted[corrupt_index] ^= 0xFF

            self.assertFalse(is_valid_ld19_packet(bytes(corrupted)), corrupt_index)
            self.assertIsNone(parse_ld19_packet(bytes(corrupted)), corrupt_index)

    def test_rejects_packet_with_corrupted_checksum(self):
        corrupted = bytearray(TRANSCRIPT_PACKET)
        corrupted[46] ^= 0x01

        self.assertIsNone(parse_ld19_packet(bytes(corrupted)))

    def test_rejects_false_header_lock_on_payload_bytes(self):
        """0x54 inside payload must not be accepted as a packet start."""
        false_lock = bytearray([0x54, 0x2C]) + bytearray(TRANSCRIPT_PACKET[:45])

        self.assertIsNone(parse_ld19_packet(bytes(false_lock)))

    def test_checksum_verification_can_be_bypassed_for_diagnostics(self):
        corrupted = bytearray(TRANSCRIPT_PACKET)
        corrupted[46] ^= 0x01

        self.assertIsNotNone(parse_ld19_packet(bytes(corrupted), verify_checksum=False))

    def test_parses_bytearray_and_bytes_identically(self):
        """The driver feeds a bytearray; Python 2 indexes bytes differently."""
        from_bytes = parse_ld19_packet(TRANSCRIPT_PACKET)
        from_bytearray = parse_ld19_packet(bytearray(TRANSCRIPT_PACKET))

        self.assertIsNotNone(from_bytearray)
        self.assertEqual(from_bytes["points"], from_bytearray["points"])

    def test_reports_rotor_speed_in_degrees_per_second(self):
        """The LD19 speed field is degrees per second, not hundredths."""
        parsed = parse_ld19_packet(TRANSCRIPT_PACKET)

        # ~3596 deg/s is roughly 10 Hz, matching the observed scan rate.
        self.assertAlmostEqual(parsed["speed_degrees_per_second"], 3596.0, places=0)

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
