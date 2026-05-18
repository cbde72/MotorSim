from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermo0d.gui.topology_config_editor import launch


DEFAULT_PROJECT = (ROOT / "Projekte").resolve()


def parse_args(args_list: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launcher for thermo0d TopologyConfigEditor")
    parser.add_argument("--config", type=str, default=None, help="Pfad oder Name einer config.yaml/config.yml")
    parser.add_argument("--project", type=str, default=str(DEFAULT_PROJECT), help="Projektordner")
    return parser.parse_args(args_list)



def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result



def _candidate_config_roots(project_dir: Path) -> list[Path]:
    return _unique_paths(
        [
            project_dir,
            project_dir / "variants",
            ROOT / "Projekte",
            ROOT / "Projekte" / "variants",
            ROOT / "Projekte" / "variants",
        ]
    )



def _expand_config_name_candidates(config_value: str) -> list[str]:
    raw = config_value.strip()
    if not raw:
        return []
    p = Path(raw)
    suffix = p.suffix.lower()
    candidates = [raw]
    if suffix not in {".yaml", ".yml"}:
        candidates.append(f"{raw}.yaml")
        candidates.append(f"{raw}.yml")
    return candidates



def _resolve_existing_path(candidate: Path) -> Path | None:
    try:
        expanded = candidate.expanduser()
    except Exception:
        expanded = candidate
    if expanded.exists():
        return expanded.resolve()
    return None



def resolve_config_path(config_value: str | None, project_value: str) -> Path | None:
    project_dir = Path(project_value).expanduser().resolve()
    roots = _candidate_config_roots(project_dir)

    if config_value:
        for token in _expand_config_name_candidates(config_value):
            direct = _resolve_existing_path(Path(token))
            if direct is not None:
                return direct
            for root in roots:
                resolved = _resolve_existing_path(root / token)
                if resolved is not None:
                    return resolved
        return Path(config_value).expanduser().resolve()

    env_default = os.environ.get("THERMO0D_DEFAULT_CONFIG", "").strip()
    if env_default:
        resolved = resolve_config_path(env_default, str(project_dir))
        if resolved is not None:
            return resolved

    for root in roots:
        for candidate in (root / "config.yaml", root / "config.yml"):
            resolved = _resolve_existing_path(candidate)
            if resolved is not None:
                return resolved

    for root in roots:
        yaml_files = sorted([*root.glob("*.yaml"), *root.glob("*.yml")])
        if yaml_files:
            return yaml_files[0].resolve()
    return None



def main(args_list: list[str] | None = None) -> int:
    args = parse_args(args_list)
    project_dir = Path(args.project).expanduser().resolve()
    config_path = resolve_config_path(args.config, str(project_dir))

    os.environ["THERMO0D_DEFAULT_PROJECT"] = str(project_dir)
    if config_path is not None:
        os.environ["THERMO0D_DEFAULT_CONFIG"] = str(config_path)
        os.chdir(config_path.parent)
    else:
        os.chdir(project_dir)

    return int(launch(config_path))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
