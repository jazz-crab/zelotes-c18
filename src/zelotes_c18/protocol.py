"""USB HID protocol of the Zelotes C-18 / SOAI C18 mouse (12C9:2003).

The mouse exposes three HID interfaces. Interface 2 (usage page 0xFF00,
usage 0xFF00) is the vendor configuration channel:

* an 8-byte **feature report** for compact commands (begin / prepare / commit),
* a 64-byte **output report** for table payloads (LED, DPI, buttons, macros).

Every transaction is ``begin -> optional table write -> commit``. The commit
packet is a real "select active profile" command, so it both applies the change
and selects the profile.

This module only builds bytes. It intentionally contains nothing that opens the
device; see :mod:`zelotes_c18.device`.
"""
from __future__ import annotations

from dataclasses import dataclass

REPORT_SIZE = 8
PAYLOAD_SIZE = 64

# --- 8-byte control commands ------------------------------------------------ #
OP_BEGIN = 0x01
OP_COMMIT = 0x02
OP_POLLING = 0x03
OP_DPI_STAGE = 0x04
OP_PREPARE_TABLE = 0x0C
OP_PREPARE_BUTTONS = 0x0D
OP_PREPARE_EXT = 0x0F

# Fixed first packet of every transaction: 01 88 00 00 00 00 00 76.
BEGIN = bytes([0x01, 0x88, 0x00, 0x00, 0x00, 0x00, 0x00, 0x76])

# --- LED ------------------------------------------------------------------- #
# 64-byte template captured from the vendor software. The mode block is
# ``19 19 05 <mode> <speed-or-tier> <param>`` at bytes 4..9; bytes 40..63 are
# eight RGB triplets. The rest of the packet is fixed.
BASE_PAYLOAD = bytes([
    0x0F, 0x00, 0x1E, 0x0A, 0x19, 0x19, 0x05, 0x01,
    0x01, 0x03, 0x64, 0x64, 0x01, 0xC0, 0xF0, 0x03,
    0x01, 0x01, 0x19, 0x19, 0x22, 0x39, 0x5C, 0xD0,
    0xF3, 0x5C, 0x73, 0x00, 0x22, 0x39, 0x5C, 0xD0,
    0xF3, 0x5C, 0x73, 0x00, 0x1F, 0xFF, 0x00, 0x00,
    0x00, 0x00, 0x31, 0x00, 0x00, 0x31, 0x00, 0x00,
    0x31, 0x00, 0x00, 0x31, 0x00, 0x00, 0x31, 0x00,
    0x00, 0x31, 0x00, 0x00, 0x31, 0x00, 0x00, 0x31,
])

# Fixed tail for every non-static mode (red/green/blue/yellow/purple/cyan/
# white/white). It does not depend on mode or speed.
EFFECT_TAIL = bytes([
    0x31, 0x00, 0x00, 0x00, 0x31, 0x00, 0x00, 0x00,
    0x31, 0x31, 0x31, 0x00, 0x31, 0x00, 0x31, 0x00,
    0x31, 0x31, 0x31, 0x31, 0x31, 0x31, 0x31, 0x31,
])

MODE_OFF = 0x00
MODE_STATIC = 0x01
MODE_BREATHING = 0x02
MODE_NEON = 0x03
MODE_WAVE = 0x04
MODE_FLOWING = 0x06

# brightness tier -> (tier byte, "on" value written into the RGB triplets)
BRIGHTNESS = {
    "high": (0x01, 0x31),
    "mid": (0x02, 0x20),
    "low": (0x03, 0x10),
}

# static colour -> channel mask. The hardware stores a binary mask per channel,
# not an 8-bit value, so only these eight presets exist.
COLORS = {
    "red": (1, 0, 0),
    "green": (0, 1, 0),
    "blue": (0, 0, 1),
    "yellow": (1, 1, 0),
    "purple": (1, 0, 1),
    "cyan": (0, 1, 1),
    "white": (1, 1, 1),
    "off": (0, 0, 0),
}

# effect -> (mode byte, param byte)
EFFECTS = {
    "breathing": (MODE_BREATHING, 0x0A),
    "neon": (MODE_NEON, 0x00),
    "wave": (MODE_WAVE, 0x10),
    "flowing": (MODE_FLOWING, 0x0A),
}

SPEEDS = {
    "neon": {"fast": 0x04, "mid": 0x08, "slow": 0x0C},
    "breathing": {"fast": 0x04, "mid": 0x08, "slow": 0x0C},
    "wave": {"fast": 0x03, "mid": 0x06, "slow": 0x09},
    "flowing": {"fast": 0x3C, "mid": 0x5F, "slow": 0x78},
}

# --- DPI ------------------------------------------------------------------- #
# Factory tables for both profiles. Bytes 7..9 and 40..63 are not fully
# decoded, so every write starts from the profile's factory table and patches
# only the two bytes of the stage being changed.
PROFILE_DPI_DEFAULT = {
    1: bytes([
        0x0F, 0x00, 0x1E, 0x0A, 0x19, 0x19, 0x05, 0x04,
        0x06, 0x10, 0x64, 0x64, 0x01, 0xC0, 0xF0, 0x03,
        0x01, 0x01, 0x19, 0x19, 0x22, 0x39, 0x5C, 0xD0,
        0xF3, 0x5C, 0x73, 0x00, 0x22, 0x39, 0x5C, 0xD0,
        0xF3, 0x5C, 0x73, 0x00, 0x1F, 0xFF, 0x00, 0x00,
        0x31, 0x00, 0x00, 0x00, 0x31, 0x00, 0x00, 0x00,
        0x31, 0x31, 0x31, 0x00, 0x31, 0x00, 0x31, 0x00,
        0x31, 0x31, 0x31, 0x31, 0x31, 0x31, 0x31, 0x31,
    ]),
    2: bytes([
        0x0F, 0x00, 0x1E, 0x0A, 0x19, 0x19, 0x05, 0x01,
        0x01, 0x03, 0x64, 0x64, 0x01, 0xC0, 0xF0, 0x03,
        0x01, 0x01, 0x19, 0x19, 0x22, 0x39, 0x5C, 0xD0,
        0xF3, 0x5C, 0x73, 0x00, 0x22, 0x39, 0x5C, 0xD0,
        0xF3, 0x5C, 0x73, 0x00, 0x1F, 0xFF, 0x00, 0x00,
        0x00, 0x00, 0x31, 0x00, 0x00, 0x31, 0x00, 0x00,
        0x31, 0x00, 0x00, 0x31, 0x00, 0x00, 0x31, 0x00,
        0x00, 0x31, 0x00, 0x00, 0x31, 0x00, 0x00, 0x31,
    ]),
}

# stage number -> (X byte offset, Y byte offset)
DPI_STAGE_OFFSETS = {
    1: (20, 28),
    2: (21, 29),
    3: (22, 30),
    4: (23, 31),
    5: (24, 32),
}

# Calibration measured by the c18_reverseengineer project.
DPI_CALIBRATION = (
    (200, 0x04), (300, 0x06), (400, 0x08), (600, 0x0D), (800, 0x12),
    (1200, 0x1B), (1600, 0x24), (2000, 0x2E), (2300, 0x34), (2400, 0x37),
    (2600, 0x3B), (3200, 0x49), (4800, 0x6F), (6400, 0xC9), (6600, 0xCC),
    (10000, 0xF3),
)

# polling rate in Hz -> bInterval in milliseconds
POLLING_INTERVALS = {1000: 1, 500: 2, 250: 4, 125: 8}


class ProtocolError(ValueError):
    """A value cannot be encoded for this device."""


# --- small builders -------------------------------------------------------- #
def checksum(packet: bytes) -> int:
    """All eight bytes of a control packet must sum to 0xFF."""
    return (0xFF - (sum(packet[:7]) & 0xFF)) & 0xFF


def command(opcode: int, b1: int = 0, b2: int = 0, b3: int = 0,
            b4: int = 0, b5: int = 0, b6: int = 0) -> bytes:
    body = bytes([opcode, b1, b2, b3, b4, b5, b6])
    return body + bytes([checksum(body)])


def prepare_table(profile: int) -> bytes:
    return command(OP_PREPARE_TABLE, profile, 0x80)


def commit(profile: int) -> bytes:
    return command(OP_COMMIT, profile)


def set_polling(profile: int, hz: int) -> bytes:
    try:
        interval = POLLING_INTERVALS[hz]
    except KeyError:
        raise ProtocolError(
            f"частота {hz} Гц не поддерживается (есть: "
            f"{', '.join(str(h) for h in POLLING_INTERVALS)})"
        ) from None
    return command(OP_POLLING, profile, interval)


def set_dpi_stage(profile: int, stage: int) -> bytes:
    if stage not in DPI_STAGE_OFFSETS:
        raise ProtocolError(f"DPI-стадия {stage} вне диапазона 1..5")
    return command(OP_DPI_STAGE, profile, stage)


# --- LED payload ----------------------------------------------------------- #
def _patch_mode_block(payload: bytearray, mode: int, speed: int, param: int) -> None:
    index = payload.find(bytes([0x19, 0x19, 0x05]))
    if index < 0:
        raise ProtocolError("в базовом LED-пакете не найден блок режима 19 19 05")
    payload[index + 3] = mode
    payload[index + 4] = speed
    payload[index + 5] = param


def _patch_tail(payload: bytearray, rgb: tuple[int, int, int] | None) -> None:
    if rgb is None:
        payload[40:64] = bytes(24)
        return
    payload[40:64] = bytes(rgb) * 8


def build_lighting_payload(mode: str, color: str = "red",
                           brightness: str = "high",
                           speed: str = "mid") -> bytes:
    """Return the 64-byte LED payload for a mode from the config."""
    payload = bytearray(BASE_PAYLOAD)

    if mode == "off":
        _patch_mode_block(payload, MODE_OFF, 0x00, 0x00)
        _patch_tail(payload, None)
        return bytes(payload)

    if mode == "static":
        if color not in COLORS:
            raise ProtocolError(
                f"цвет {color!r} не поддерживается (есть: {', '.join(COLORS)})"
            )
        if brightness not in BRIGHTNESS:
            raise ProtocolError(
                f"яркость {brightness!r} не поддерживается (есть: "
                f"{', '.join(BRIGHTNESS)})"
            )
        tier, on = BRIGHTNESS[brightness]
        mask = COLORS[color]
        _patch_mode_block(payload, MODE_STATIC, tier, 0x03)
        _patch_tail(payload, tuple(on if channel else 0 for channel in mask))
        return bytes(payload)

    if mode not in EFFECTS:
        raise ProtocolError(
            f"режим подсветки {mode!r} не поддерживается (есть: off, static, "
            f"{', '.join(EFFECTS)})"
        )
    if speed not in SPEEDS[mode]:
        raise ProtocolError(
            f"скорость {speed!r} для режима {mode} не поддерживается (есть: "
            f"{', '.join(SPEEDS[mode])})"
        )
    effect_mode, param = EFFECTS[mode]
    _patch_mode_block(payload, effect_mode, SPEEDS[mode][speed], param)
    payload[40:64] = EFFECT_TAIL
    return bytes(payload)


def primer() -> bytes:
    """The 64-byte primer that precedes every table payload."""
    return bytes([0xFF, 0xFF]) + bytes(PAYLOAD_SIZE - 2)


# --- DPI payload ----------------------------------------------------------- #
def dpi_to_byte(dpi: int) -> int:
    """Map a DPI value to the byte stored in the DPI table."""
    if not (DPI_CALIBRATION[0][0] <= dpi <= DPI_CALIBRATION[-1][0]):
        raise ProtocolError(
            f"DPI {dpi} вне диапазона "
            f"{DPI_CALIBRATION[0][0]}..{DPI_CALIBRATION[-1][0]}"
        )
    for (d0, b0), (d1, b1) in zip(DPI_CALIBRATION, DPI_CALIBRATION[1:]):
        if d0 <= dpi <= d1:
            return (b0 + (dpi - d0) * (b1 - b0) // (d1 - d0)) & 0xFF
    return DPI_CALIBRATION[-1][1]


def build_dpi_payload(profile: int, stages: list[int] | tuple[int, ...]) -> bytes:
    """Patch all five stage values into the profile's factory DPI table."""
    if len(stages) != 5:
        raise ProtocolError(
            f"нужно ровно 5 DPI-стадий, получено {len(stages)}"
        )
    payload = bytearray(PROFILE_DPI_DEFAULT[profile])
    for stage, dpi in enumerate(stages, start=1):
        value = dpi_to_byte(int(dpi))
        x_offset, y_offset = DPI_STAGE_OFFSETS[stage]
        payload[x_offset] = value
        payload[y_offset] = value
    return bytes(payload)


@dataclass(frozen=True)
class LedSummary:
    mode: str
    color: str
    brightness: str
    speed: str
    payload: bytes

    def describe(self) -> str:
        if self.mode == "off":
            return "подсветка выключена (mode 0x00)"
        if self.mode == "static":
            return (f"статический цвет {self.color}, яркость {self.brightness} "
                    f"(mode 0x01)")
        return f"эффект {self.mode}, скорость {self.speed}"


def describe_lighting(mode: str, color: str = "red",
                      brightness: str = "high", speed: str = "mid") -> LedSummary:
    return LedSummary(mode, color, brightness, speed,
                      build_lighting_payload(mode, color, brightness, speed))
