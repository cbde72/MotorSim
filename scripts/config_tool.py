from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermo0d.config.models import RootConfig
from thermo0d.config_versioning import (
    config_schema_version_from_document,
    diff_config_dicts,
    migrate_config_data,
    migrate_yaml_text,
    normalize_config_data,
)
from thermo0d.input.config_loader import ConfigLoadError, ConfigLoader


def _load_text_and_raw(path: Path) -> tuple[str, dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise RuntimeError(f"Top-level YAML muss ein Mapping sein: {path}")
    return text, raw


def _dump_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _validated_without_versioning(data: dict[str, Any]) -> RootConfig:
    return RootConfig.model_validate({k: v for k, v in data.items() if k != "versioning"})


def cmd_validate(path: Path) -> int:
    try:
        ConfigLoader.load(path)
    except ConfigLoadError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"[OK] valid: {path}")
    return 0


def cmd_upgrade(path: Path, write: bool, output: Path | None) -> int:
    original_text, raw = _load_text_and_raw(path)
    upgraded = migrate_config_data(raw)
    _validated_without_versioning(upgraded)
    if write and output is not None:
        raise RuntimeError("--write und --output schließen sich aus")
    target = path if write else (output or path.with_name(path.stem + "_upgraded" + path.suffix))
    if target.suffix.lower() in {".yaml", ".yml"}:
        upgraded_text = migrate_yaml_text(original_text, upgraded)
        target.write_text(upgraded_text, encoding="utf-8")
    else:
        target.write_text(json.dumps(upgraded, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[OK] upgraded: {target}")
    return 0


def cmd_normalize(path: Path, output: Path | None) -> int:
    _, raw = _load_text_and_raw(path)
    normalized = normalize_config_data(migrate_config_data(raw))
    _validated_without_versioning(normalized)
    target = output or path.with_name(path.stem + "_normalized" + path.suffix)
    target.write_text(_dump_yaml(normalized), encoding="utf-8")
    print(f"[OK] normalized: {target}")
    return 0


def cmd_explain(path: Path, path_key: str | None) -> int:
    _, raw = _load_text_and_raw(path)
    upgraded = migrate_config_data(raw)
    normalized = normalize_config_data(upgraded)
    if path_key:
        value: Any = normalized
        for part in path_key.split("."):
            if not isinstance(value, dict) or part not in value:
                print(f"[MISS] {path_key}")
                return 1
            value = value[part]
        print(yaml.safe_dump(value, sort_keys=False, allow_unicode=True).rstrip())
        return 0

    print(f"Datei           : {path}")
    print(f"Geladenes Schema: {config_schema_version_from_document(raw)}")
    print(f"Aktuelles Schema: {upgraded.get('versioning', {}).get('config_schema_version')}")
    print(f"Volumes         : {len(((normalized.get('preprocessing') or {}).get('volumes') or []))}")
    print(f"Connections     : {len(((normalized.get('preprocessing') or {}).get('connections') or []))}")
    print(f"Solver          : {(((normalized.get('simulation') or {}).get('solver') or {}).get('kind'))}")
    print(f"Sampling        : {(((normalized.get('postprocessing') or {}).get('sampling') or {}).get('mode'))}")
    print("\nÄnderungen zur kanonischen Form:")
    for line in diff_config_dicts(raw, normalized)[:200]:
        print(line)
    return 0


def cmd_diff(left: Path, right: Path | None) -> int:
    if right is None:
        _, raw = _load_text_and_raw(left)
        canonical = normalize_config_data(migrate_config_data(raw))
        diff = diff_config_dicts(raw, canonical)
        if not diff:
            print("[OK] no canonical diff")
            return 0
        for line in diff:
            print(line)
        return 0

    left_lines = left.read_text(encoding="utf-8").splitlines()
    right_lines = right.read_text(encoding="utf-8").splitlines()
    text = "\n".join(difflib.unified_diff(left_lines, right_lines, fromfile=str(left), tofile=str(right), lineterm=""))
    if not text:
        print("[OK] no diff")
        return 0
    print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Thermo0D config validate/upgrade/normalize/explain/diff")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="YAML laden und gegen aktuelles Schema validieren")
    p.add_argument("config", type=Path)

    p = sub.add_parser("upgrade", help="Alte Feldnamen/Schemata migrieren")
    p.add_argument("config", type=Path)
    p.add_argument("--write", action="store_true")
    p.add_argument("--output", type=Path, default=None)

    p = sub.add_parser("normalize", help="Konfiguration semantisch unverändert normalisieren")
    p.add_argument("config", type=Path)
    p.add_argument("--output", type=Path, default=None)

    p = sub.add_parser("explain", help="Kurzzusammenfassung oder Pfadinhalt ausgeben")
    p.add_argument("config", type=Path)
    p.add_argument("--path-key", default=None)

    p = sub.add_parser("diff", help="Zwei Konfigurationen oder eine Konfiguration gegen die kanonische Form vergleichen")
    p.add_argument("left", type=Path)
    p.add_argument("right", nargs="?", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "validate":
            return cmd_validate(args.config.resolve())
        if args.cmd == "upgrade":
            out = args.output.resolve() if args.output else None
            return cmd_upgrade(args.config.resolve(), bool(args.write), out)
        if args.cmd == "normalize":
            out = args.output.resolve() if args.output else None
            return cmd_normalize(args.config.resolve(), out)
        if args.cmd == "explain":
            return cmd_explain(args.config.resolve(), args.path_key)
        if args.cmd == "diff":
            right = args.right.resolve() if args.right else None
            return cmd_diff(args.left.resolve(), right)
        raise SystemExit(2)
    except (RuntimeError, yaml.YAMLError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
