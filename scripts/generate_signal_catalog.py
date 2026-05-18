from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermo0d.gui.signal_catalog import generate_signal_alias_file, generate_signal_catalog_file


def parse_args(args_list: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate thermo0d signal catalog YAML from current project metadata and available outputs.")
    parser.add_argument("--project", default=str((ROOT / "Projekte").resolve()), help="Projektordner")
    parser.add_argument("--output", default=None, help="Optionaler Zielpfad für die Katalogdatei")
    return parser.parse_args(args_list)


def main(args_list: list[str] | None = None) -> int:
    args = parse_args(args_list)
    out = generate_signal_catalog_file(Path(args.project), Path(args.output) if args.output else None)
    alias_out = generate_signal_alias_file(Path(args.project))
    print(f"[OK] Signal catalog: {out}")
    print(f"[OK] Signal aliases: {alias_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
