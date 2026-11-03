"""Windows HID transport for the Zelotes C-18 configuration interface.

On Windows the vendor collection declares a 64-byte output report and an
8-byte feature report (no report IDs). HIDAPI therefore needs one leading
``0x00`` report-ID byte for each transfer:

* 8-byte command  -> ``00`` + 8 bytes via ``HidD_SetFeature``
* 64-byte payload -> ``00`` + 64 bytes via the interrupt OUT report

No driver replacement (Zadig/WinUSB) and no administrator rights are needed.
"""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

import hid

from .protocol import (
    BEGIN,
    PAYLOAD_SIZE,
    REPORT_SIZE,
    commit,
    prepare_table,
    primer,
)

VENDOR_USAGE_PAGE = 0xFF00
VENDOR_USAGE = 0xFF00


class DeviceNotFound(RuntimeError):
    """The mouse or its vendor configuration interface is not present."""


class TransportError(RuntimeError):
    """A HID transfer was rejected by the device or the OS."""


class _HIDP_CAPS(ctypes.Structure):
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


def windows_report_caps(path: str) -> dict | None:
    """Ask Windows for the report lengths (hidapi does not expose HidP_GetCaps).

    Returns ``None`` on non-Windows or if the device cannot be queried.
    """
    if sys.platform != "win32":
        return None
    try:
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
            ctypes.c_void_p, ctypes.POINTER(_HIDP_CAPS),
        ]
        hid_dll.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
    except (AttributeError, OSError):
        return None

    handle = k32.CreateFileW(path, 0, 3, None, 3, 0x40000000, None)
    if handle == wintypes.HANDLE(-1).value:
        return None
    try:
        pp = ctypes.c_void_p()
        if not hid_dll.HidD_GetPreparsedData(wintypes.HANDLE(handle),
                                            ctypes.byref(pp)):
            return None
        try:
            caps = _HIDP_CAPS()
            if hid_dll.HidP_GetCaps(pp, ctypes.byref(caps)) != 0x00110000:
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


def find_vendor_info(vid: int, pid: int, interface: int = 2,
                     usage_page: int = VENDOR_USAGE_PAGE,
                     usage: int = VENDOR_USAGE) -> dict | None:
    """Return the HID info of the vendor collection, or ``None``."""
    candidates = hid.enumerate(vid, pid)
    for info in candidates:
        if (info.get("interface_number") == interface
                and info.get("usage_page") == usage_page
                and info.get("usage") == usage):
            return info
    # Fall back to interface number only: some Windows builds report a
    # different usage pair for the same vendor collection.
    for info in candidates:
        if info.get("interface_number") == interface:
            return info
    return None


class Mouse:
    def __init__(self, vid: int, pid: int, interface: int = 2,
                 usage_page: int = VENDOR_USAGE_PAGE,
                 usage: int = VENDOR_USAGE, verbose: bool = False):
        self.vid = vid
        self.pid = pid
        self.interface = interface
        self.verbose = verbose
        self.path: bytes | str | None = None
        self.h: hid.device | None = None
        self._open(usage_page, usage)

    def _open(self, usage_page: int, usage: int) -> None:
        chosen = find_vendor_info(self.vid, self.pid, self.interface,
                                  usage_page, usage)
        if chosen is None:
            raise DeviceNotFound(
                f"не найден вендорский HID-интерфейс мыши "
                f"(VID {self.vid:04X} / PID {self.pid:04X} / interface "
                f"{self.interface} / usage_page 0x{usage_page:04X}). "
                f"Проверь, что мышь подключена проводом и не спит."
            )
        self.path = chosen["path"]
        self.info = chosen
        self.h = hid.device()
        try:
            self.h.open_path(self.path)
        except Exception as exc:  # hidapi raises OSError/IOError
            raise TransportError(
                f"не удалось открыть интерфейс мыши: {exc}. "
                f"Закрой вендорскую утилиту и попробуй снова."
            ) from exc

    # --- lifecycle --------------------------------------------------------- #
    def __enter__(self) -> "Mouse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if self.h is not None:
            try:
                self.h.close()
            except Exception:
                pass
            self.h = None

    # --- raw transfers ----------------------------------------------------- #
    def send_command(self, packet: bytes, delay: float = 0.005) -> None:
        """Send one 8-byte feature report (SET_REPORT, report ID 0)."""
        if len(packet) != REPORT_SIZE:
            raise ValueError(f"команда должна быть {REPORT_SIZE} байт")
        assert self.h is not None
        written = self.h.send_feature_report(b"\x00" + packet)
        if written < 0:
            raise TransportError(self.h.error() or "send_feature_report failed")
        if delay:
            time.sleep(delay)

    def write_payload(self, payload: bytes, delay: float = 0.0) -> None:
        """Send one 64-byte output report (interrupt OUT endpoint 0x04)."""
        if len(payload) != PAYLOAD_SIZE:
            raise ValueError(f"payload должен быть {PAYLOAD_SIZE} байт")
        assert self.h is not None
        written = self.h.write(b"\x00" + payload)
        if written < 0:
            raise TransportError(self.h.error() or "write failed")
        if delay:
            time.sleep(delay)

    # --- transaction ------------------------------------------------------- #
    def transaction(self, profile: int, payload: bytes | None = None,
                    extra: tuple[bytes, ...] = ()) -> None:
        """begin -> [prepare + primer + payload] -> extra commands -> commit.

        ``extra`` commands are sent after the payload and before the commit, so
        the whole change lands in one transaction (used for DPI stage select).
        """
        self.send_command(BEGIN)
        if payload is not None:
            self.send_command(prepare_table(profile))
            self.write_payload(primer(), delay=0.020)
            self.write_payload(payload, delay=0.040)
        for packet in extra:
            self.send_command(packet)
        self.send_command(commit(profile), delay=0.050)

    # --- read-only diagnostics --------------------------------------------- #
    def report_descriptor(self) -> bytes:
        assert self.h is not None
        return bytes(self.h.get_report_descriptor())

    def feature_echo(self) -> bytes:
        """GET_REPORT of the 8-byte feature channel.

        This is a live status/counter, not a configuration readback.
        """
        assert self.h is not None
        return bytes(self.h.get_feature_report(0, REPORT_SIZE + 1))

    @property
    def path_str(self) -> str:
        path = self.path
        return path.decode() if isinstance(path, bytes) else str(path)

    def describe(self) -> str:
        info = self.info
        return (
            f"{info.get('manufacturer_string', '')} "
            f"{info.get('product_string', '')} "
            f"({self.vid:04X}:{self.pid:04X}, interface {self.interface}, "
            f"usage_page 0x{info.get('usage_page', 0):04X}, "
            f"usage 0x{info.get('usage', 0):04X})"
        )
