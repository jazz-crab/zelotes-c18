#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only диагностика мыши: что именно видит Windows.

Печатает все HID-интерфейсы 12C9:2003, report descriptor вендорского
интерфейса, длины отчётов и ответ GET_REPORT. Ничего не пишет.
"""
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import hid

from zelotes_c18.config import Config
from zelotes_c18.device import Mouse


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", wintypes.USHORT),
        ("UsagePage", wintypes.USHORT),
        ("InputReportByteLength", wintypes.USHORT),
        ("OutputReportByteLength", wintypes.USHORT),
        ("FeatureReportByteLength", wintypes.USHORT),
        ("Reserved", wintypes.USHORT * 17),
        ("NumberLinkCollectionNodes", wintypes.USHORT),
        ("NumberInputButtonCaps", wintypes.USHORT),
        ("NumberInputValueCaps", wintypes.USHORT),
        ("NumberInputDataIndices", wintypes.USHORT),
        ("NumberOutputButtonCaps", wintypes.USHORT),
        ("NumberOutputValueCaps", wintypes.USHORT),
        ("NumberOutputDataIndices", wintypes.USHORT),
        ("NumberFeatureButtonCaps", wintypes.USHORT),
        ("NumberFeatureValueCaps", wintypes.USHORT),
        ("NumberFeatureDataIndices", wintypes.USHORT),
    ]


def print_hex(data: bytes, indent: str = "    ") -> None:
    for offset in range(0, len(data), 16):
        chunk = data[offset:offset + 16]
        print(indent + f"{offset:04x}  " + " ".join(f"{b:02x}" for b in chunk))


def windows_caps(path: str) -> dict | None:
    """Ask Windows for the report lengths (hidapi does not expose them)."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    hid_dll = ctypes.WinDLL("hid", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    hid_dll.HidD_GetPreparsedData.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p),
    ]
    hid_dll.HidP_GetCaps.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS),
    ]
    hid_dll.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]

    handle = k32.CreateFileW(path, 0, 3, None, 3, 0x40000000, None)
    if handle == wintypes.HANDLE(-1).value:
        return None
    try:
        pp = ctypes.c_void_p()
        if not hid_dll.HidD_GetPreparsedData(wintypes.HANDLE(handle),
                                            ctypes.byref(pp)):
            return None
        try:
            caps = HIDP_CAPS()
            if hid_dll.HidP_GetCaps(pp, ctypes.byref(caps)) != 0:
                return None
            return {
                "usage_page": caps.UsagePage,
                "usage": caps.Usage,
                "input": caps.InputReportByteLength,
                "output": caps.OutputReportByteLength,
                "feature": caps.FeatureReportByteLength,
            }
        finally:
            hid_dll.HidD_FreePreparsedData(pp)
    finally:
        k32.CloseHandle(wintypes.HANDLE(handle))


def main() -> int:
    cfg = Config.load(REPO / "config" / "default.toml")
    print(f"Устройство: {cfg.vid:04X}:{cfg.pid:04X}")
    print("Все HID-интерфейсы:")
    for info in hid.enumerate(cfg.vid, cfg.pid):
        print(f"  MI_{info.get('interface_number')}  "
              f"usage_page=0x{info.get('usage_page', 0):04X}  "
              f"usage=0x{info.get('usage', 0):04X}  "
              f"path={info.get('path')}")

    vendor = [i for i in hid.enumerate(cfg.vid, cfg.pid)
              if i.get("interface_number") == cfg.interface]
    if not vendor:
        print(f"\nВендорский интерфейс MI_{cfg.interface} не найден.")
        return 1

    path = vendor[0]["path"]
    path_str = path.decode() if isinstance(path, bytes) else path
    caps = windows_caps(path_str)
    if caps:
        print("\nHidP_GetCaps (включая report ID):")
        print(f"  usage_page=0x{caps['usage_page']:04X}  "
              f"usage=0x{caps['usage']:04X}")
        print(f"  input={caps['input']}  output={caps['output']}  "
              f"feature={caps['feature']}")

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
