"""Проверки протокола без устройства: байты, checksum, payload, DPI."""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from zelotes_c18.protocol import (  # noqa: E402
    BEGIN,
    DPI_STAGE_OFFSETS,
    EFFECT_TAIL,
    build_dpi_payload,
    build_lighting_payload,
    checksum,
    commit,
    dpi_to_byte,
    prepare_table,
    set_dpi_stage,
    set_polling,
)


class CommandTests(unittest.TestCase):
    def test_fixed_packets(self):
        self.assertEqual(BEGIN.hex(), "0188000000000076")
        self.assertEqual(prepare_table(1).hex(), "0c01800000000072")
        self.assertEqual(prepare_table(2).hex(), "0c02800000000071")
        self.assertEqual(commit(1).hex(), "02010000000000fc")
        self.assertEqual(commit(2).hex(), "02020000000000fb")
        self.assertEqual(set_polling(1, 1000).hex(), "03010100000000fa")
        self.assertEqual(set_polling(2, 500).hex(), "03020200000000f8")
        self.assertEqual(set_dpi_stage(1, 1).hex(), "04010100000000f9")

    def test_every_packet_sums_to_ff(self):
        packets = [
            BEGIN, prepare_table(1), prepare_table(2), commit(1), commit(2),
            set_polling(1, 125), set_polling(1, 1000),
            set_dpi_stage(2, 5),
        ]
        for packet in packets:
            self.assertEqual(len(packet), 8)
            self.assertEqual(sum(packet), 0xFF)
            self.assertEqual(packet[-1], checksum(packet))


class LightingTests(unittest.TestCase):
    def test_off(self):
        payload = build_lighting_payload("off")
        self.assertEqual(len(payload), 64)
        self.assertEqual(payload[7:10], bytes([0x00, 0x00, 0x00]))
        self.assertEqual(payload[40:64], bytes(24))

    def test_static_red_high(self):
        payload = build_lighting_payload("static", "red", "high")
        self.assertEqual(payload[7:10], bytes([0x01, 0x01, 0x03]))
        self.assertEqual(payload[40:64], bytes([0x31, 0x00, 0x00]) * 8)

    def test_static_cyan_low(self):
        payload = build_lighting_payload("static", "cyan", "low")
        self.assertEqual(payload[7:10], bytes([0x01, 0x03, 0x03]))
        self.assertEqual(payload[40:64], bytes([0x00, 0x10, 0x10]) * 8)

    def test_wave_fast(self):
        payload = build_lighting_payload("wave", speed="fast")
        self.assertEqual(payload[7:10], bytes([0x04, 0x03, 0x10]))
        self.assertEqual(payload[40:64], EFFECT_TAIL)

    def test_flowing_slow(self):
        payload = build_lighting_payload("flowing", speed="slow")
        self.assertEqual(payload[7:10], bytes([0x06, 0x78, 0x0A]))
        self.assertEqual(payload[40:64], EFFECT_TAIL)


class DpiTests(unittest.TestCase):
    def test_known_points(self):
        self.assertEqual(dpi_to_byte(200), 0x04)
        self.assertEqual(dpi_to_byte(1000), 0x16)   # hardware-confirmed
        self.assertEqual(dpi_to_byte(7000), 0xD0)   # hardware-confirmed
        self.assertEqual(dpi_to_byte(10000), 0xF3)

    def test_stage_offsets(self):
        stages = [1000, 1200, 1600, 2400, 3200]
        payload = build_dpi_payload(1, stages)
        self.assertEqual(len(payload), 64)
        for stage, dpi in enumerate(stages, start=1):
            x, y = DPI_STAGE_OFFSETS[stage]
            self.assertEqual(payload[x], dpi_to_byte(dpi))
            self.assertEqual(payload[y], dpi_to_byte(dpi))

    def test_out_of_range(self):
        with self.assertRaises(Exception):
            dpi_to_byte(100)
        with self.assertRaises(Exception):
            build_dpi_payload(1, [800, 1200, 1600])


if __name__ == "__main__":
    unittest.main()
