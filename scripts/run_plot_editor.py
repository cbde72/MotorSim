from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# %%
from thermo0d.gui.plot_style_editor import main as gui_main

from thermo0d.gui.signal_catalog import generate_signal_alias_file, generate_signal_catalog_file


def parse_args(args_list: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open the thermo0d plot style editor for a project directory.")
    parser.add_argument("--config", default=None, help="Optionaler Pfad zur config.yaml/config.yml")
    parser.add_argument("--project", default=str((ROOT / "Projekte").resolve()), help="Project directory containing config.yaml and result CSV files.")
    return parser.parse_args(args_list)


def resolve_config_path(config_value: str | None, project_value: str) -> Path | None:
    project_dir = Path(project_value).expanduser().resolve()
    if config_value:
        candidate = Path(config_value).expanduser()
        if candidate.exists():
            return candidate.resolve()
        project_candidate = project_dir / config_value
        if project_candidate.exists():
            return project_candidate.resolve()
        return candidate.resolve()
    for candidate in (project_dir / 'config.yaml', project_dir / 'config.yml'):
        if candidate.exists():
            return candidate.resolve()
    yaml_files = sorted([*project_dir.glob('*.yaml'), *project_dir.glob('*.yml')])
    return yaml_files[0].resolve() if yaml_files else None


def main(args_list: list[str] | None = None) -> int:
    args = parse_args(args_list)
    project_dir = Path(args.project).expanduser().resolve()
    config_path = resolve_config_path(args.config, str(project_dir))
    generate_signal_catalog_file(project_dir)
    generate_signal_alias_file(project_dir)
    os.environ['THERMO0D_DEFAULT_PROJECT'] = str(project_dir)
    if config_path is not None:
        os.environ['THERMO0D_DEFAULT_CONFIG'] = str(config_path)
    os.chdir(project_dir)
    return int(gui_main())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
