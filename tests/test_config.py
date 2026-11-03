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
        self.assertEqual(cfg.polling.hz, 1000)
        self.assertEqual(cfg.dpi.stages, (1520, 2500, 4000, 7000, 10000))

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


if __name__ == "__main__":
    unittest.main()
