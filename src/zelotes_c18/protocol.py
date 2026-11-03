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
# DPI stage bytes live in the SAME 64-byte packet as the lighting fields.
# Confirmed on hardware: writing a DPI table applies its lighting block
# (bytes 7..9 and 40..63), and writing a lighting packet applies its DPI bytes.
# Both factory profiles use the same five stage bytes, so one template covers
# them.
#
# These values encode to exactly the factory bytes (22 39 5c d0 f3), so
# applying them leaves the out-of-the-box DPI registers unchanged.
DPI_FACTORY_STAGES = (1520, 2500, 4000, 7000, 10000)

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


def prepare_buttons(profile: int) -> bytes:
    return command(OP_PREPARE_BUTTONS, profile, 0x80)


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


# --- buttons --------------------------------------------------------------- #
# Offset of each physical button's 4-byte [type LE][value LE] pair. Button 11
# sits out of numeric order, between 6 and 7 (vendor layout quirk).
BUTTON_SLOTS = {
    1: 0, 2: 4, 3: 8, 4: 12, 5: 16, 6: 20, 11: 24,
    7: 32, 8: 36, 9: 40, 10: 44,
}

# Factory table (Restore Defaults capture). Bytes 28..31 and 48..63 are a
# fixed trailer and are preserved as-is.
BUTTON_DEFAULT_TABLE = bytes([
    0x01, 0x00, 0xF0, 0x00, 0x01, 0x00, 0xF1, 0x00,
    0x01, 0x00, 0xF2, 0x00, 0x01, 0x00, 0xF4, 0x00,
    0x01, 0x00, 0xF3, 0x00, 0x07, 0x00, 0x03, 0x00,
    0x00, 0x00, 0x2C, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x1A, 0x00, 0x00, 0x00, 0x16, 0x00,
    0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x07, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x04, 0x00, 0x01, 0x00, 0x04, 0x00, 0x02, 0x00,
])

BUTTON_CLICKS = {
    "left": 0xF0, "menu": 0xF1, "middle": 0xF2, "back": 0xF3,
    "forward": 0xF4,
}

MEDIA_ACTIONS = {
    "play-pause": 0xCD, "playpause": 0xCD, "stop": 0xB7,
    "next": 0xB5, "prev": 0xB6, "previous": 0xB6,
    "mute": 0xE2, "vol-up": 0xE9, "volume-up": 0xE9,
    "vol-down": 0xEA, "volume-down": 0xEA,
}

DPI_ACTIONS = {"up": 0x01, "down": 0x02, "cycle": 0x03}
PROFILE_ACTIONS = {"up": 0x01, "down": 0x02, "cycle": 0x03}

MODIFIER_BITS = {"ctrl": 0x01, "shift": 0x02, "alt": 0x04, "win": 0x08}

# USB HID keyboard usage codes (standard Keyboard/Keypad page).
KEY_CODES: dict[str, int] = {
    "enter": 0x28, "return": 0x28,
    "esc": 0x29, "escape": 0x29,
    "backspace": 0x2A,
    "tab": 0x2B,
    "space": 0x2C,
    "capslock": 0x39,
    "printscreen": 0x46, "prtsc": 0x46,
    "insert": 0x49,
    "home": 0x4A,
    "pageup": 0x4B, "pgup": 0x4B,
    "delete": 0x4C, "del": 0x4C,
    "end": 0x4D,
    "pagedown": 0x4E, "pgdn": 0x4E,
    "right": 0x4F, "left": 0x50, "down": 0x51, "up": 0x52,
    "minus": 0x2D, "plus": 0x2E,
    "`": 0x35, "[" : 0x2F, "]" : 0x30, "\\": 0x31,
    ";": 0x33, "'": 0x34, ",": 0x36, ".": 0x37, "/": 0x38,
}
for _i in range(1, 13):
    KEY_CODES[f"f{_i}"] = 0x3A + _i - 1
for _c in range(ord("a"), ord("z") + 1):
    KEY_CODES[chr(_c)] = 0x04 + _c - ord("a")
for _d in range(1, 10):
    KEY_CODES[str(_d)] = 0x1E + _d - 1
KEY_CODES["0"] = 0x27


def _parse_shortcut(arg: str) -> tuple[int, int]:
    parts = [part.strip().lower() for part in arg.split("+") if part.strip()]
    if len(parts) < 2:
        raise ProtocolError(
            f"shortcut {arg!r}: нужен модификатор и клавиша, например ctrl+c"
        )
    *mods, key = parts
    bits = 0
    for name in mods:
        if name not in MODIFIER_BITS:
            raise ProtocolError(
                f"shortcut {arg!r}: неизвестный модификатор {name!r} "
                f"(есть: {', '.join(MODIFIER_BITS)})"
            )
        bits |= MODIFIER_BITS[name]
    if key not in KEY_CODES:
        raise ProtocolError(f"shortcut {arg!r}: неизвестная клавиша {key!r}")
    return bits << 8, KEY_CODES[key]


def parse_button_action(spec: str) -> tuple[int, int]:
    """Turn ``"shortcut:ctrl+c"`` into the device's ``(type, value)`` pair.

    Supported forms:
    ``none``, ``click:<left|menu|middle|back|forward>``, ``key:<name>``,
    ``shortcut:<mods>+<key>``, ``media:<name>``, ``dpi:<up|down|cycle>``,
    ``profile:<up|down|cycle>``.
    """
    text = str(spec).strip().lower()
    if text in ("", "none", "off", "disabled"):
        return 0x0000, 0x0000
    if ":" not in text:
        raise ProtocolError(
            f"кнопка {spec!r}: ожидалось действие вида click:left, key:enter, "
            f"shortcut:ctrl+c, media:mute, dpi:cycle, profile:cycle или none"
        )
    kind, arg = text.split(":", 1)
    arg = arg.strip()

    if kind == "click":
        if arg not in BUTTON_CLICKS:
            raise ProtocolError(
                f"click {arg!r}: есть {', '.join(BUTTON_CLICKS)}"
            )
        return 0x0001, BUTTON_CLICKS[arg]
    if kind == "key":
        if arg not in KEY_CODES:
            raise ProtocolError(f"key {arg!r}: неизвестная клавиша")
        return 0x0000, KEY_CODES[arg]
    if kind == "shortcut":
        return _parse_shortcut(arg)
    if kind == "media":
        if arg not in MEDIA_ACTIONS:
            raise ProtocolError(
                f"media {arg!r}: есть {', '.join(sorted(MEDIA_ACTIONS))}"
            )
        return 0x0003, MEDIA_ACTIONS[arg]
    if kind == "dpi":
        if arg not in DPI_ACTIONS:
            raise ProtocolError("dpi: ожидалось up, down или cycle")
        return 0x0007, DPI_ACTIONS[arg]
    if kind == "profile":
        if arg not in PROFILE_ACTIONS:
            raise ProtocolError("profile: ожидалось up, down или cycle")
        return 0x0008, PROFILE_ACTIONS[arg]
    raise ProtocolError(
        f"кнопка {spec!r}: неизвестный тип {kind!r} "
        f"(есть: click, key, shortcut, media, dpi, profile, none)"
    )


def build_button_table(assignments: dict[int, str] | None = None) -> bytes:
    """Build the full 64-byte button table, starting from factory defaults."""
    table = bytearray(BUTTON_DEFAULT_TABLE)
    for slot, spec in (assignments or {}).items():
        slot = int(slot)
        if slot not in BUTTON_SLOTS:
            raise ProtocolError(f"кнопка {slot}: номер должен быть 1..11")
        btype, value = parse_button_action(spec)
        offset = BUTTON_SLOTS[slot]
        table[offset:offset + 2] = btype.to_bytes(2, "little")
        table[offset + 2:offset + 4] = value.to_bytes(2, "little")
    return bytes(table)


# --- 64-byte config packet ------------------------------------------------- #
def _lighting_fields(mode: str, color: str, brightness: str,
                     speed: str) -> tuple[int, int, int, bytes]:
    """Validate lighting settings and return (mode, speed, param, tail)."""
    if mode == "off":
        return MODE_OFF, 0x00, 0x00, bytes(24)

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
        rgb = tuple(on if channel else 0 for channel in mask)
        return MODE_STATIC, tier, 0x03, bytes(rgb) * 8

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
    return effect_mode, SPEEDS[mode][speed], param, EFFECT_TAIL


def _patch_lighting(payload: bytearray, mode: str, color: str,
                    brightness: str, speed: str) -> None:
    mode_byte, speed_byte, param, tail = _lighting_fields(
        mode, color, brightness, speed)
    index = payload.find(bytes([0x19, 0x19, 0x05]))
    if index < 0:
        raise ProtocolError("в 64-байтовом пакете не найден блок режима 19 19 05")
    payload[index + 3] = mode_byte
    payload[index + 4] = speed_byte
    payload[index + 5] = param
    payload[40:64] = tail


def _patch_dpi(payload: bytearray, stages: list[int] | tuple[int, ...]) -> None:
    if len(stages) != 5:
        raise ProtocolError(
            f"нужно ровно 5 DPI-стадий, получено {len(stages)}"
        )
    for stage, dpi in enumerate(stages, start=1):
        value = dpi_to_byte(int(dpi))
        x_offset, y_offset = DPI_STAGE_OFFSETS[stage]
        payload[x_offset] = value
        payload[y_offset] = value


def build_config_payload(mode: str = "off", color: str = "red",
                         brightness: str = "high", speed: str = "mid",
                         dpi_stages: list[int] | tuple[int, ...] | None = None
                         ) -> bytes:
    """Build the single 64-byte packet that carries lighting AND DPI.

    The device stores both subsystems in one packet, so every write specifies
    both. ``dpi_stages=None`` keeps the factory DPI bytes of the template.
    """
    payload = bytearray(BASE_PAYLOAD)
    _patch_lighting(payload, mode, color, brightness, speed)
    if dpi_stages is not None:
        _patch_dpi(payload, dpi_stages)
    return bytes(payload)


def primer() -> bytes:
    """The 64-byte primer that precedes every table payload."""
    return bytes([0xFF, 0xFF]) + bytes(PAYLOAD_SIZE - 2)


# --- DPI encoding ---------------------------------------------------------- #
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


@dataclass(frozen=True)
class LightingSummary:
    mode: str
    color: str
    brightness: str
    speed: str

    def describe(self) -> str:
        if self.mode == "off":
            return "подсветка выключена (mode 0x00)"
        if self.mode == "static":
            return (f"статический цвет {self.color}, яркость {self.brightness} "
                    f"(mode 0x01)")
        return f"эффект {self.mode}, скорость {self.speed}"


def describe_lighting(mode: str, color: str = "red",
                      brightness: str = "high",
                      speed: str = "mid") -> LightingSummary:
    _lighting_fields(mode, color, brightness, speed)  # validate early
    return LightingSummary(mode, color, brightness, speed)
