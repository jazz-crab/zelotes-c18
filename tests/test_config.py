"""Проверки разбора конфига."""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from zelotes_c18.config import Config, ConfigError  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_default_config(self):
        cfg = Config.load(REPO / "config" / "default.toml")
        self.assertEqual((cfg.vid, cfg.pid), (0x12C9, 0x2003))
        self.assertEqual(cfg.profile_targets, (1, 2))
        self.assertEqual(cfg.profile_select, 1)
        self.assertEqual(cfg.lighting.mode, "off")
        self.assertEqual(cfg.polling.enabled, False)
        self.assertEqual(cfg.polling.hz, 1000)
        self.assertEqual(cfg.dpi.stages, (2500, 2500, 2500, 2500, 2500))
        self.assertEqual(len(cfg.buttons), 11)
        self.assertEqual(cfg.buttons[4], "shortcut:ctrl+v")
        self.assertEqual(cfg.buttons[11], "key:printscreen")

    def test_profiles_can_be_both(self):
        cfg = Config.from_dict(
            {"profile": {"targets": "both", "select": 2}},
            Path("test.toml"),
        )
        self.assertEqual(cfg.profile_targets, (1, 2))
        self.assertEqual(cfg.profile_select, 2)

    def test_bad_mode(self):
        with self.assertRaises(ConfigError):
            Config.from_dict(
                {"lighting": {"mode": "disco"}}, Path("test.toml"))

    def test_bad_polling(self):
        with self.assertRaises(ConfigError):
            Config.from_dict(
                {"polling": {"hz": 333}}, Path("test.toml"))

    def test_bad_dpi_count(self):
        with self.assertRaises(ConfigError):
            Config.from_dict(
                {"dpi": {"stages": [800, 1600, 3200]}}, Path("test.toml"))

    def test_bad_profile(self):
        with self.assertRaises(ConfigError):
            Config.from_dict(
                {"profile": {"targets": [3]}}, Path("test.toml"))

    def test_buttons_override(self):
        cfg = Config.from_dict(
            {"buttons": {7: "shortcut:alt+tab", 8: "key:enter"}},
            Path("test.toml"),
        )
        self.assertEqual(cfg.buttons, {7: "shortcut:alt+tab", 8: "key:enter"})

    def test_bad_button_action(self):
        with self.assertRaises(ConfigError):
            Config.from_dict(
                {"buttons": {7: "teleport"}}, Path("test.toml"))

    def test_bad_button_number(self):
        with self.assertRaises(ConfigError):
            Config.from_dict(
                {"buttons": {12: "key:enter"}}, Path("test.toml"))


if __name__ == "__main__":
    unittest.main()
