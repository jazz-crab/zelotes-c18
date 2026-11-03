"""Проверки протокола без устройства: байты, checksum, пакет, DPI."""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from zelotes_c18.protocol import (  # noqa: E402
    BASE_PAYLOAD,
    BEGIN,
    BUTTON_DEFAULT_TABLE,
    DPI_FACTORY_STAGES,
    DPI_STAGE_OFFSETS,
    EFFECT_TAIL,
    build_button_table,
    build_config_payload,
    checksum,
    commit,
    dpi_to_byte,
    parse_button_action,
    prepare_buttons,
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
            set_dpi_stage(2, 5), prepare_buttons(1), prepare_buttons(2),
        ]
        for packet in packets:
            self.assertEqual(len(packet), 8)
            self.assertEqual(sum(packet), 0xFF)
            self.assertEqual(packet[-1], checksum(packet))

    def test_prepare_buttons(self):
        self.assertEqual(prepare_buttons(1).hex(), "0d01800000000071")
        self.assertEqual(prepare_buttons(2).hex(), "0d02800000000070")


class ConfigPacketTests(unittest.TestCase):
    def test_off(self):
        payload = build_config_payload("off")
        self.assertEqual(len(payload), 64)
        self.assertEqual(payload[7:10], bytes([0x00, 0x00, 0x00]))
        self.assertEqual(payload[40:64], bytes(24))

    def test_static_red_high(self):
        payload = build_config_payload("static", "red", "high")
        self.assertEqual(payload[7:10], bytes([0x01, 0x01, 0x03]))
        self.assertEqual(payload[40:64], bytes([0x31, 0x00, 0x00]) * 8)

    def test_static_cyan_low(self):
        payload = build_config_payload("static", "cyan", "low")
        self.assertEqual(payload[7:10], bytes([0x01, 0x03, 0x03]))
        self.assertEqual(payload[40:64], bytes([0x00, 0x10, 0x10]) * 8)

    def test_wave_fast(self):
        payload = build_config_payload("wave", speed="fast")
        self.assertEqual(payload[7:10], bytes([0x04, 0x03, 0x10]))
        self.assertEqual(payload[40:64], EFFECT_TAIL)

    def test_flowing_slow(self):
        payload = build_config_payload("flowing", speed="slow")
        self.assertEqual(payload[7:10], bytes([0x06, 0x78, 0x0A]))
        self.assertEqual(payload[40:64], EFFECT_TAIL)

    def test_lighting_write_keeps_dpi_bytes(self):
        """Подсветка и DPI живут в одном пакете: LED-write не должен менять DPI."""
        payload = build_config_payload("static", "green", "high")
        self.assertEqual(payload[20:33], BASE_PAYLOAD[20:33])

    def test_combined_payload_carries_both(self):
        stages = [1000, 1200, 1600, 2400, 3200]
        payload = build_config_payload("static", "blue", "mid",
                                       dpi_stages=stages)
        self.assertEqual(payload[7:10], bytes([0x01, 0x02, 0x03]))
        self.assertEqual(payload[40:64], bytes([0x00, 0x00, 0x20]) * 8)
        for stage, dpi in enumerate(stages, start=1):
            x, y = DPI_STAGE_OFFSETS[stage]
            self.assertEqual(payload[x], dpi_to_byte(dpi))
            self.assertEqual(payload[y], dpi_to_byte(dpi))


class DpiTests(unittest.TestCase):
    def test_known_points(self):
        self.assertEqual(dpi_to_byte(200), 0x04)
        self.assertEqual(dpi_to_byte(1000), 0x16)   # hardware-confirmed
        self.assertEqual(dpi_to_byte(7000), 0xD0)   # hardware-confirmed
        self.assertEqual(dpi_to_byte(10000), 0xF3)

    def test_factory_stages_reproduce_factory_bytes(self):
        payload = build_config_payload("off", dpi_stages=DPI_FACTORY_STAGES)
        self.assertEqual(payload[20:33], BASE_PAYLOAD[20:33])
        self.assertEqual(payload[20:25], bytes([0x22, 0x39, 0x5C, 0xD0, 0xF3]))

    def test_stage_offsets(self):
        stages = [1000, 1200, 1600, 2400, 3200]
        payload = build_config_payload("off", dpi_stages=stages)
        self.assertEqual(len(payload), 64)
        for stage, dpi in enumerate(stages, start=1):
            x, y = DPI_STAGE_OFFSETS[stage]
            self.assertEqual(payload[x], dpi_to_byte(dpi))
            self.assertEqual(payload[y], dpi_to_byte(dpi))

    def test_out_of_range(self):
        with self.assertRaises(Exception):
            dpi_to_byte(100)
        with self.assertRaises(Exception):
            build_config_payload("off", dpi_stages=[800, 1200, 1600])


class ButtonTests(unittest.TestCase):
    def test_actions(self):
        self.assertEqual(parse_button_action("click:left"), (0x0001, 0xF0))
        self.assertEqual(parse_button_action("key:enter"), (0x0000, 0x28))
        self.assertEqual(parse_button_action("shortcut:ctrl+c"),
                         (0x0100, 0x06))
        self.assertEqual(parse_button_action("shortcut:win+shift+s"),
                         (0x0A00, 0x16))
        self.assertEqual(parse_button_action("media:play-pause"),
                         (0x0003, 0xCD))
        self.assertEqual(parse_button_action("dpi:cycle"), (0x0007, 0x03))
        self.assertEqual(parse_button_action("none"), (0x0000, 0x0000))

    def test_bad_actions(self):
        for spec in ("nope", "click:sideways", "shortcut:ctrl",
                     "media:rewind", "key:ж", "dpi:sideways"):
            with self.assertRaises(Exception, msg=spec):
                parse_button_action(spec)

    def test_default_table_is_stable(self):
        self.assertEqual(build_button_table(), BUTTON_DEFAULT_TABLE)
        self.assertEqual(len(BUTTON_DEFAULT_TABLE), 64)

    def test_patch_slots(self):
        table = build_button_table({4: "shortcut:ctrl+v",
                                    11: "key:printscreen"})
        # button 4 lives at offset 12, button 11 at offset 24
        self.assertEqual(table[12:16], bytes([0x00, 0x01, 0x19, 0x00]))
        self.assertEqual(table[24:28], bytes([0x00, 0x00, 0x46, 0x00]))
        # untouched buttons keep factory assignments
        self.assertEqual(table[0:4], BUTTON_DEFAULT_TABLE[0:4])

    def test_bad_slot(self):
        with self.assertRaises(Exception):
            build_button_table({12: "key:enter"})


if __name__ == "__main__":
    unittest.main()
