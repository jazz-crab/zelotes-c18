#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only диагностика мыши: что именно видит Windows.

Печатает все HID-интерфейсы 12C9:2003, report descriptor вендорского
интерфейса, длины отчётов и ответ GET_REPORT. Ничего не пишет.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import hid

from zelotes_c18.config import Config
from zelotes_c18.device import Mouse, find_vendor_info, windows_report_caps


def print_hex(data: bytes, indent: str = "    ") -> None:
    for offset in range(0, len(data), 16):
        chunk = data[offset:offset + 16]
        print(indent + f"{offset:04x}  " + " ".join(f"{b:02x}" for b in chunk))


def main() -> int:
    cfg = Config.load(REPO / "config" / "default.toml")
    print(f"Устройство: {cfg.vid:04X}:{cfg.pid:04X}")
    print("Все HID-интерфейсы:")
    for info in hid.enumerate(cfg.vid, cfg.pid):
        print(f"  MI_{info.get('interface_number')}  "
              f"usage_page=0x{info.get('usage_page', 0):04X}  "
              f"usage=0x{info.get('usage', 0):04X}  "
              f"path={info.get('path')}")

    info = find_vendor_info(cfg.vid, cfg.pid, cfg.interface,
                            cfg.usage_page, cfg.usage)
    if info is None:
        print(f"\nВендорский интерфейс MI_{cfg.interface} не найден.")
        return 1

    path = info["path"]
    path_str = path.decode() if isinstance(path, bytes) else str(path)
    caps = windows_report_caps(path_str)
    if caps:
        print("\nHidP_GetCaps (включая report ID):")
        print(f"  usage_page=0x{caps['usage_page']:04X}  "
              f"usage=0x{caps['usage']:04X}")
        print(f"  input={caps['input']}  output={caps['output']}  "
              f"feature={caps['feature']}")
    else:
        print("\nHidP_GetCaps: недоступен")

    with Mouse(cfg.vid, cfg.pid, cfg.interface,
               cfg.usage_page, cfg.usage) as mouse:
        print(f"\nВендорский интерфейс: {mouse.describe()}")
        print("Report descriptor:")
        print_hex(mouse.report_descriptor())
        try:
            echo = mouse.feature_echo()
            print(f"GET_REPORT: {echo.hex(' ')}")
        except Exception as exc:
            print(f"GET_REPORT: недоступен ({exc})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
