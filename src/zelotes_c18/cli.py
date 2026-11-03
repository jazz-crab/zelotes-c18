"""Command line interface: status / probe / apply / off."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .config import Config, ConfigError
from .device import (
    DeviceNotFound,
    Mouse,
    TransportError,
    find_vendor_info,
    windows_report_caps,
)
from .protocol import (
    ProtocolError,
    build_dpi_payload,
    build_lighting_payload,
    describe_lighting,
    set_dpi_stage,
    set_polling,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "default.toml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="c18",
        description="Zelotes C-18 (SOAI C18, 12C9:2003): конфигурация через HID "
                    "(Windows).",
    )
    parser.add_argument("--config", metavar="PATH",
                        help=f"путь к TOML-конфигу (по умолчанию {DEFAULT_CONFIG})")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="показать интерфейс и сохранённый конфиг")
    sub.add_parser("probe", help="подробная read-only диагностика HID")

    p = sub.add_parser("apply", help="привести мышь к конфигу")
    p.add_argument("--yes", action="store_true",
                   help="реально писать (без флага — dry-run)")
    p.add_argument("--no-light", action="store_true", help="не трогать подсветку")
    p.add_argument("--no-dpi", action="store_true", help="не трогать DPI")
    p.add_argument("--no-polling", action="store_true",
                   help="не трогать частоту опроса")
    _add_profile_flags(p)

    p = sub.add_parser("off", help="выключить подсветку (mode 0x00)")
    p.add_argument("--yes", action="store_true",
                   help="реально писать (без флага — dry-run)")
    _add_profile_flags(p)
    return parser


def _add_profile_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", choices=("1", "2", "both"),
                        help="профиль(и) для записи (по умолчанию из конфига)")
    parser.add_argument("--select", type=int, choices=(1, 2),
                        help="профиль, который останется активным (по умолчанию "
                             "из конфига)")


def load_config(args) -> Config:
    raw = args.config or os.environ.get("ZELOTES_C18_CONFIG")
    path = Path(raw).expanduser() if raw else DEFAULT_CONFIG
    return Config.load(path)


def targets_from(cfg: Config, args) -> tuple[int, ...]:
    if not args.profile:
        return cfg.profile_targets
    if args.profile == "both":
        return (1, 2)
    return (int(args.profile),)


def select_from(cfg: Config, args) -> int:
    return args.select if args.select is not None else cfg.profile_select


def print_config(cfg: Config) -> None:
    light = cfg.lighting
    print(f"  конфиг: {cfg.path}")
    print(f"  профили записи: {', '.join(map(str, cfg.profile_targets))}; "
          f"активный после записи: {cfg.profile_select}")
    if light.enabled:
        summary = describe_lighting(light.mode, light.color, light.brightness,
                                    light.speed)
        print(f"  подсветка: {summary.describe()}")
    else:
        print("  подсветка: не настраивается (lighting.enabled = false)")
    if cfg.polling.enabled:
        print(f"  опрос: {cfg.polling.hz} Гц")
    if cfg.dpi.enabled:
        print(f"  DPI: стадии {', '.join(map(str, cfg.dpi.stages))}; "
              f"активная {cfg.dpi.active_stage}")


def cmd_status(cfg: Config, args) -> int:
    print("Конфиг (намерение, а не снимок устройства):")
    print_config(cfg)
    print("\nУстройство:")
    try:
        with Mouse(cfg.vid, cfg.pid, cfg.interface,
                   cfg.usage_page, cfg.usage) as mouse:
            print(f"  {mouse.describe()}")
            print(f"  путь: {mouse.path_str}")
            try:
                echo = mouse.feature_echo()
                print(f"  GET_REPORT: {echo.hex(' ')}")
            except Exception as exc:
                print(f"  GET_REPORT: недоступен ({exc})")
    except (DeviceNotFound, TransportError) as exc:
        print(f"  {exc}")
        return 1
    print("\n  ВАЖНО: у мыши нет чтения конфигурации. LED/DPI/кнопки — "
          "write-only,\n  поэтому status не может показать, что реально залито "
          "в устройство.")
    return 0


def cmd_probe(cfg: Config, args) -> int:
    info = find_vendor_info(cfg.vid, cfg.pid, cfg.interface,
                            cfg.usage_page, cfg.usage)
    if info is None:
        raise DeviceNotFound(
            f"не найден вендорский интерфейс MI_{cfg.interface} "
            f"({cfg.vid:04X}:{cfg.pid:04X})"
        )
    path = info["path"]
    path_str = path.decode() if isinstance(path, bytes) else str(path)

    # Query Windows caps before hidapi opens the collection: opening it
    # exclusively prevents a second CreateFile on some systems.
    caps = windows_report_caps(path_str)
    if caps is None:
        print("  HidP_GetCaps: недоступен")
    else:
        print(f"  usage_page=0x{caps['usage_page']:04X}  "
              f"usage=0x{caps['usage']:04X}")
        print(f"  input report: {caps['input']} байт (включая report ID)")
        print(f"  output report: {caps['output']} байт (включая report ID)")
        print(f"  feature report: {caps['feature']} байт (включая report ID)")

    with Mouse(cfg.vid, cfg.pid, cfg.interface,
               cfg.usage_page, cfg.usage) as mouse:
        print(f"  {mouse.describe()}")
        print(f"  путь: {mouse.path_str}")
        descriptor = mouse.report_descriptor()
        print(f"  report descriptor ({len(descriptor)} байт):")
        _print_hex(descriptor, indent="    ")
        try:
            echo = mouse.feature_echo()
            print(f"  GET_REPORT: {echo.hex(' ')}")
        except Exception as exc:
            print(f"  GET_REPORT: недоступен ({exc})")
    return 0


def _print_hex(data: bytes, indent: str = "  ", width: int = 16) -> None:
    for offset in range(0, len(data), width):
        chunk = data[offset:offset + width]
        print(indent + f"{offset:04x}  " + " ".join(f"{b:02x}" for b in chunk))


def warn_no_readback() -> None:
    print("  ВНИМАНИЕ: протокол не поддерживает чтение конфигурации. "
          "Проверить\n  результат можно только глазами (подсветка) или "
          "вендорской утилитой.")


def cmd_apply(cfg: Config, args) -> int:
    targets = targets_from(cfg, args)
    select = select_from(cfg, args)
    want_light = cfg.lighting.enabled and not args.no_light
    want_dpi = cfg.dpi.enabled and not args.no_dpi
    want_polling = cfg.polling.enabled and not args.no_polling

    light_summary = None
    light_payload = None
    if want_light:
        light_summary = describe_lighting(cfg.lighting.mode, cfg.lighting.color,
                                          cfg.lighting.brightness,
                                          cfg.lighting.speed)
        light_payload = light_summary.payload

    print("План:")
    print(f"  профили записи: {', '.join(map(str, targets))}; "
          f"активный после записи: {select}")
    if light_summary:
        print(f"  подсветка: {light_summary.describe()}")
    else:
        print("  подсветка: пропущена")
    if want_dpi:
        print(f"  DPI: стадии {', '.join(map(str, cfg.dpi.stages))}; "
              f"активная {cfg.dpi.active_stage}")
    else:
        print("  DPI: пропущено")
    if want_polling:
        print(f"  опрос: {cfg.polling.hz} Гц")
    else:
        print("  опрос: пропущен")

    if light_payload is not None:
        print("  LED payload (64 байта):")
        _print_hex(light_payload, indent="    ")

    if not args.yes:
        print("\nDRY-RUN: ничего не записано. Добавь --yes, чтобы залить.")
        return 0

    warn_no_readback()
    with Mouse(cfg.vid, cfg.pid, cfg.interface,
               cfg.usage_page, cfg.usage) as mouse:
        print(f"\nУстройство: {mouse.describe()}")
        for profile in targets:
            print(f"\n== профиль {profile} ==")
            if light_payload is not None:
                mouse.transaction(profile, light_payload)
                print(f"  подсветка: {light_summary.describe()}")
            if want_dpi:
                dpi_payload = build_dpi_payload(profile, list(cfg.dpi.stages))
                mouse.transaction(profile, dpi_payload,
                                  extra=(set_dpi_stage(profile,
                                                       cfg.dpi.active_stage),))
                print(f"  DPI: {', '.join(map(str, cfg.dpi.stages))}, "
                      f"активная {cfg.dpi.active_stage}")
            if want_polling:
                mouse.transaction(profile, None,
                                  extra=(set_polling(profile, cfg.polling.hz),))
                print(f"  опрос: {cfg.polling.hz} Гц")

        if select != targets[-1]:
            mouse.transaction(select, None)
    print("\nГотово. Проверь подсветку глазами: чтения состояния у мыши нет.")
    return 0


def cmd_off(cfg: Config, args) -> int:
    targets = targets_from(cfg, args)
    select = select_from(cfg, args)
    payload = build_lighting_payload("off")
    print("План: выключить подсветку (mode 0x00) и очистить RGB-хвост")
    print(f"  профили: {', '.join(map(str, targets))}; "
          f"активный после записи: {select}")
    print("  LED payload (64 байта):")
    _print_hex(payload, indent="    ")

    if not args.yes:
        print("\nDRY-RUN: ничего не записано. Добавь --yes, чтобы выключить.")
        return 0

    warn_no_readback()
    with Mouse(cfg.vid, cfg.pid, cfg.interface,
               cfg.usage_page, cfg.usage) as mouse:
        print(f"\nУстройство: {mouse.describe()}")
        for profile in targets:
            mouse.transaction(profile, payload)
            print(f"  профиль {profile}: подсветка выключена")
        if select != targets[-1]:
            mouse.transaction(select, None)
            print(f"  активный профиль: {select}")
    print("\nГотово. Если подсветка осталась — попробуй другой профиль "
          "(--profile 1 / --profile 2).")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args)
    except ConfigError as exc:
        print(f"Ошибка конфига: {exc}", file=sys.stderr)
        return 2

    handlers = {
        "status": cmd_status,
        "probe": cmd_probe,
        "apply": cmd_apply,
        "off": cmd_off,
    }
    try:
        return handlers[args.command](cfg, args)
    except (DeviceNotFound, TransportError) as exc:
        print(f"Ошибка HID: {exc}", file=sys.stderr)
        return 1
    except ProtocolError as exc:
        print(f"Ошибка протокола: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130
