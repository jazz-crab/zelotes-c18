"""Load and validate ``config/default.toml``.

The config describes intent: which profile(s) to write, which lighting mode,
polling rate and DPI stages. The protocol layer turns that intent into packets.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .protocol import (
    BRIGHTNESS,
    COLORS,
    EFFECTS,
    POLLING_INTERVALS,
    SPEEDS,
)

VALID_PROFILES = (1, 2)
LIGHTING_MODES = ("off", "static", *EFFECTS)


class ConfigError(ValueError):
    """Invalid or missing configuration."""


@dataclass(frozen=True)
class LightingConfig:
    enabled: bool = True
    mode: str = "off"
    color: str = "red"
    brightness: str = "high"
    speed: str = "mid"


@dataclass(frozen=True)
class PollingConfig:
    enabled: bool = True
    hz: int = 1000


@dataclass(frozen=True)
class DpiConfig:
    enabled: bool = True
    active_stage: int = 1
    stages: tuple[int, ...] = (800, 1200, 1600, 2400, 3200)


@dataclass(frozen=True)
class Config:
    path: Path
    vid: int = 0x12C9
    pid: int = 0x2003
    interface: int = 2
    usage_page: int = 0xFF00
    usage: int = 0xFF00
    profile_targets: tuple[int, ...] = (1, 2)
    profile_select: int = 1
    lighting: LightingConfig = field(default_factory=LightingConfig)
    polling: PollingConfig = field(default_factory=PollingConfig)
    dpi: DpiConfig = field(default_factory=DpiConfig)

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        path = Path(path)
        if not path.is_file():
            raise ConfigError(f"конфиг не найден: {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"{path}: не удалось прочитать: {exc}") from exc
        try:
            raw = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: некорректный TOML: {exc}") from exc
        return cls.from_dict(raw, path)

    @classmethod
    def from_dict(cls, raw: dict, path: Path) -> "Config":
        dev = raw.get("device", {})
        profile = raw.get("profile", {})
        cfg = cls(
            path=path,
            vid=_as_int(dev.get("vid", 0x12C9), "device.vid"),
            pid=_as_int(dev.get("pid", 0x2003), "device.pid"),
            interface=_as_int(dev.get("interface", 2), "device.interface"),
            usage_page=_as_int(dev.get("usage_page", 0xFF00), "device.usage_page"),
            usage=_as_int(dev.get("usage", 0xFF00), "device.usage"),
            profile_targets=_as_profiles(
                profile.get("targets", [1, 2]), "profile.targets"),
            profile_select=_as_int(profile.get("select", 1), "profile.select"),
            lighting=_lighting(raw.get("lighting", {})),
            polling=_polling(raw.get("polling", {})),
            dpi=_dpi(raw.get("dpi", {})),
        )
        cfg._validate()
        return cfg

    def _validate(self) -> None:
        if not (0 <= self.vid <= 0xFFFF and 0 <= self.pid <= 0xFFFF):
            raise ConfigError("device.vid/pid должны быть 0..0xFFFF")
        if not (0 <= self.interface <= 0xFF):
            raise ConfigError("device.interface должен быть 0..255")
        if not (0 <= self.usage_page <= 0xFFFF and 0 <= self.usage <= 0xFFFF):
            raise ConfigError("device.usage_page/usage должны быть 0..0xFFFF")
        if not self.profile_targets:
            raise ConfigError("profile.targets не может быть пустым")
        if self.profile_select not in VALID_PROFILES:
            raise ConfigError("profile.select должен быть 1 или 2")
        if self.lighting.enabled:
            if self.lighting.mode not in LIGHTING_MODES:
                raise ConfigError(
                    f"lighting.mode: неизвестный режим {self.lighting.mode!r} "
                    f"(есть: {', '.join(LIGHTING_MODES)})"
                )
            if self.lighting.mode == "static":
                if self.lighting.color not in COLORS:
                    raise ConfigError(
                        f"lighting.color: неизвестный цвет {self.lighting.color!r} "
                        f"(есть: {', '.join(COLORS)})"
                    )
                if self.lighting.brightness not in BRIGHTNESS:
                    raise ConfigError(
                        "lighting.brightness: ожидалось high/mid/low"
                    )
            if self.lighting.mode in SPEEDS:
                if self.lighting.speed not in SPEEDS[self.lighting.mode]:
                    raise ConfigError(
                        f"lighting.speed: для {self.lighting.mode} ожидалось "
                        f"{'/'.join(SPEEDS[self.lighting.mode])}"
                    )
        if self.polling.enabled and self.polling.hz not in POLLING_INTERVALS:
            raise ConfigError(
                f"polling.hz: поддерживается {', '.join(str(h) for h in POLLING_INTERVALS)}"
            )
        if self.dpi.enabled:
            if not (1 <= self.dpi.active_stage <= 5):
                raise ConfigError("dpi.active_stage должен быть 1..5")
            if len(self.dpi.stages) != 5:
                raise ConfigError("dpi.stages должен содержать ровно 5 значений")
            for value in self.dpi.stages:
                if not (200 <= value <= 10000):
                    raise ConfigError("dpi.stages: каждое значение 200..10000")


# --------------------------------------------------------------------------- #
# parsing helpers
# --------------------------------------------------------------------------- #
def _as_int(value, where: str) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{where}: ожидалось целое число")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{where}: ожидалось целое число, получено {value!r}") from None


def _as_bool(value, where: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{where}: ожидалось true/false")
    return value


def _as_profiles(value, where: str) -> tuple[int, ...]:
    if isinstance(value, str):
        if value.lower() == "both":
            return VALID_PROFILES
        try:
            value = [int(value)]
        except ValueError:
            raise ConfigError(f"{where}: ожидалось 1, 2 или [1, 2]") from None
    if isinstance(value, int) and not isinstance(value, bool):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise ConfigError(f"{where}: ожидался список профилей")
    profiles: list[int] = []
    for item in value:
        number = _as_int(item, where)
        if number not in VALID_PROFILES:
            raise ConfigError(f"{where}: профиль {number} не существует (1 или 2)")
        if number not in profiles:
            profiles.append(number)
    return tuple(sorted(profiles))


def _lighting(raw: dict) -> LightingConfig:
    return LightingConfig(
        enabled=_as_bool(raw.get("enabled", True), "lighting.enabled"),
        mode=str(raw.get("mode", "off")).lower(),
        color=str(raw.get("color", "red")).lower(),
        brightness=str(raw.get("brightness", "high")).lower(),
        speed=str(raw.get("speed", "mid")).lower(),
    )


def _polling(raw: dict) -> PollingConfig:
    return PollingConfig(
        enabled=_as_bool(raw.get("enabled", True), "polling.enabled"),
        hz=_as_int(raw.get("hz", 1000), "polling.hz"),
    )


def _dpi(raw: dict) -> DpiConfig:
    stages = raw.get("stages", [800, 1200, 1600, 2400, 3200])
    if not isinstance(stages, (list, tuple)):
        raise ConfigError("dpi.stages: ожидался список из 5 значений")
    return DpiConfig(
        enabled=_as_bool(raw.get("enabled", True), "dpi.enabled"),
        active_stage=_as_int(raw.get("active_stage", 1), "dpi.active_stage"),
        stages=tuple(_as_int(v, "dpi.stages") for v in stages),
    )
