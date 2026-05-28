from __future__ import annotations

import copy
import json
import re

import yaml
from pathlib import Path
from typing import Any, Mapping

from .version import CURRENT_CONFIG_SCHEMA_VERSION, __version__, normalized_versioning_dict
from .config.initial_state_sync import sync_initial_states_inplace

VERSIONING_KEY = "versioning"
LEGACY_TOP_LEVEL_VERSION_KEYS = (
    "config_schema_version",
    "schema_version",
    "package_version",
    "app_version",
    "loaded_config_schema_version",
    "migration_applied",
)


def extract_raw_versioning(config_data: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the raw version mapping from a loaded config document.

    New files store version metadata below the top-level ``versioning`` block.
    For backwards compatibility we also accept a handful of legacy flat keys.
    """
    if not isinstance(config_data, Mapping):
        return {}
    nested = config_data.get(VERSIONING_KEY)
    if isinstance(nested, Mapping):
        return dict(nested)
    return {key: config_data.get(key) for key in LEGACY_TOP_LEVEL_VERSION_KEYS if key in config_data}


def config_schema_version_from_document(config_data: Mapping[str, Any] | None) -> int:
    raw = extract_raw_versioning(config_data)
    if not raw:
        return 0
    try:
        return int(normalized_versioning_dict(raw).get("config_schema_version", 0))
    except Exception:
        return 0


def requires_version_upgrade(config_data: Mapping[str, Any] | None) -> bool:
    """Return True when the loaded config uses an older schema or has no versioning yet."""
    return config_schema_version_from_document(config_data) < int(CURRENT_CONFIG_SCHEMA_VERSION)


def current_versioning_dict(*, migrated_from: int | None = None, migration_applied: bool = False) -> dict[str, Any]:
    loaded_schema = int(CURRENT_CONFIG_SCHEMA_VERSION if migrated_from is None else migrated_from)
    return {
        "package_version": str(__version__),
        "config_schema_version": int(CURRENT_CONFIG_SCHEMA_VERSION),
        "loaded_config_schema_version": loaded_schema,
        "migration_applied": bool(migration_applied),
    }


def stamp_current_versioning(
    config_data: Mapping[str, Any] | None,
    *,
    migrated_from: int | None = None,
    migration_applied: bool = False,
) -> dict[str, Any]:
    """Return a shallow-copied config dict with current version metadata stamped in."""
    out = dict(config_data or {})
    for key in LEGACY_TOP_LEVEL_VERSION_KEYS:
        out.pop(key, None)
    out[VERSIONING_KEY] = current_versioning_dict(
        migrated_from=migrated_from,
        migration_applied=migration_applied,
    )
    return out


def _deepcopy_mapping(config_data: Mapping[str, Any] | None) -> dict[str, Any]:
    if isinstance(config_data, Mapping):
        return copy.deepcopy(dict(config_data))
    return {}


def _resolve_submodel_reference(
    *,
    library: Mapping[str, Any],
    local_config: Any,
    legacy_ref: Any = None,
    context: str,
) -> dict[str, Any] | Any:
    if not isinstance(local_config, Mapping):
        if legacy_ref is None:
            return local_config
        local: dict[str, Any] = {}
    else:
        local = copy.deepcopy(dict(local_config))

    ref_name = local.pop("ref", None)
    if ref_name is None:
        ref_name = local.pop("reference", None)
    if ref_name is None:
        ref_name = legacy_ref
    if ref_name is None:
        return local

    ref_key = str(ref_name)
    base = library.get(ref_key)
    if not isinstance(base, Mapping):
        raise ValueError(f"{context} references unknown submodel {ref_key!r}")
    resolved = copy.deepcopy(dict(base))
    resolved.update(local)
    return resolved


def _normalize_preprocessing_nested_keys(preprocessing: dict[str, Any]) -> None:
    volumes = preprocessing.get("volumes")
    if isinstance(volumes, list):
        for volume in volumes:
            if not isinstance(volume, dict):
                continue
            combustion = volume.get("combustion")
            if isinstance(combustion, dict) and "angle_ref" in combustion and "angle_reference" not in combustion:
                combustion["angle_reference"] = combustion.pop("angle_ref")

    connections = preprocessing.get("connections")
    if isinstance(connections, list):
        for conn in connections:
            if not isinstance(conn, dict):
                continue
            _rename_if_present(conn, "opening_ref", "opening_reference")
            _rename_if_present(conn, "alphak_file", "alpha_k_file")
            _rename_if_present(conn, "number_of_holes", "number_of_identical_holes")
            _rename_if_present(conn, "forward_discharge_coefficient", "forward_cd")
            _rename_if_present(conn, "reverse_discharge_coefficient", "reverse_cd")


def resolve_preprocessing_submodel_references(config_data: Mapping[str, Any] | None) -> dict[str, Any]:
    """Resolve central preprocessing.submodels references into local config blocks."""
    out = _deepcopy_mapping(config_data)
    preprocessing = out.get("preprocessing")
    if not isinstance(preprocessing, dict):
        return out
    submodels = preprocessing.get("submodels")
    if not isinstance(submodels, Mapping):
        submodels = {}
    volume_library = submodels.get("volumes") if isinstance(submodels.get("volumes"), Mapping) else {}
    wall_heat_library = submodels.get("wall_heat") if isinstance(submodels.get("wall_heat"), Mapping) else {}
    if isinstance(submodels, dict) and "wall_temperatur" in submodels and "wall_temperature" not in submodels:
        submodels["wall_temperature"] = submodels.pop("wall_temperatur")
    wall_temperature_library = submodels.get("wall_temperature") if isinstance(submodels.get("wall_temperature"), Mapping) else {}
    combustion_library = submodels.get("combustion") if isinstance(submodels.get("combustion"), Mapping) else {}
    connection_library = submodels.get("connections") if isinstance(submodels.get("connections"), Mapping) else {}
    volumes = preprocessing.get("volumes")
    if isinstance(volumes, list):
        for index, volume in enumerate(volumes):
            if not isinstance(volume, dict):
                continue
            vol_name = str(volume.get("name", f"volumes[{index}]"))
            ref_present = "ref" in volume or "reference" in volume
            legacy_volume_ref = volume.pop("volume_ref", None)
            if ref_present or legacy_volume_ref is not None:
                resolved_volume = _resolve_submodel_reference(
                    library=volume_library,
                    local_config=volume,
                    legacy_ref=legacy_volume_ref,
                    context=f"preprocessing.volumes[{index}] {vol_name}",
                )
                if isinstance(resolved_volume, dict):
                    volume = resolved_volume
                    volumes[index] = volume
                else:
                    continue
            vol_name = str(volume.get("name", f"volumes[{index}]"))
            wall_heat_config = volume.get("wall_heat")
            wall_heat_ref_present = isinstance(wall_heat_config, Mapping) and ("ref" in wall_heat_config or "reference" in wall_heat_config)
            legacy_wall_heat_ref = volume.pop("wall_heat_ref", None)
            if wall_heat_ref_present or legacy_wall_heat_ref is not None:
                volume["wall_heat"] = _resolve_submodel_reference(
                    library=wall_heat_library,
                    local_config=wall_heat_config,
                    legacy_ref=legacy_wall_heat_ref,
                    context=f"preprocessing.volumes[{index}] {vol_name}.wall_heat",
                )
            if "wall_temperatur" in volume and "wall_temperature" not in volume:
                volume["wall_temperature"] = volume.pop("wall_temperatur")
            wall_temperature_config = volume.get("wall_temperature")
            wall_temperature_ref_present = isinstance(wall_temperature_config, Mapping) and ("ref" in wall_temperature_config or "reference" in wall_temperature_config)
            legacy_wall_temperature_ref = volume.pop("wall_temperature_ref", None)
            legacy_wall_temperatur_ref = volume.pop("wall_temperatur_ref", None)
            if wall_temperature_ref_present or legacy_wall_temperature_ref is not None or legacy_wall_temperatur_ref is not None:
                volume["wall_temperature"] = _resolve_submodel_reference(
                    library=wall_temperature_library,
                    local_config=wall_temperature_config,
                    legacy_ref=legacy_wall_temperature_ref if legacy_wall_temperature_ref is not None else legacy_wall_temperatur_ref,
                    context=f"preprocessing.volumes[{index}] {vol_name}.wall_temperature",
                )
            combustion_config = volume.get("combustion")
            combustion_ref_present = isinstance(combustion_config, Mapping) and ("ref" in combustion_config or "reference" in combustion_config)
            legacy_combustion_ref = volume.pop("combustion_ref", None)
            if combustion_ref_present or legacy_combustion_ref is not None:
                volume["combustion"] = _resolve_submodel_reference(
                    library=combustion_library,
                    local_config=combustion_config,
                    legacy_ref=legacy_combustion_ref,
                    context=f"preprocessing.volumes[{index}] {vol_name}.combustion",
                )
    connections = preprocessing.get("connections")
    if isinstance(connections, list):
        for index, connection in enumerate(connections):
            if not isinstance(connection, dict):
                continue
            conn_name = str(connection.get("name", f"connections[{index}]"))
            ref_present = "ref" in connection or "reference" in connection
            legacy_ref = connection.pop("connection_ref", None)
            if ref_present or legacy_ref is not None:
                connections[index] = _resolve_submodel_reference(
                    library=connection_library,
                    local_config=connection,
                    legacy_ref=legacy_ref,
                    context=f"preprocessing.connections[{index}] {conn_name}",
                )
    return out


def _rename_cool_flame_burn_model_values(value: Any) -> None:
    if isinstance(value, dict):
        if value.get("cool_flame_burn_model") == "beck-vibe_CF":
            value["cool_flame_burn_model"] = "vibe-beck_CF"
        for child in value.values():
            _rename_cool_flame_burn_model_values(child)
    elif isinstance(value, list):
        for child in value:
            _rename_cool_flame_burn_model_values(child)


def migrate_config_data(config_data: Mapping[str, Any] | None) -> dict[str, Any]:
    """Migrate older config dicts to the current schema in memory.

    This is intentionally conservative: only known legacy names are rewritten,
    missing defaults are added, and the result is version-stamped.
    """
    previous_schema = config_schema_version_from_document(config_data)
    out = _deepcopy_mapping(config_data)
    _rename_cool_flame_burn_model_values(out)

    out.setdefault("modeling", {"architecture": "classic"})

    preprocessing = out.get("preprocessing")
    if isinstance(preprocessing, dict):
        features = preprocessing.get("features")
        if isinstance(features, dict) and "heat_transfer" in features and "wall_heat" not in features:
            features["wall_heat"] = features.pop("heat_transfer")

        _normalize_preprocessing_nested_keys(preprocessing)
        out = resolve_preprocessing_submodel_references(out)
        preprocessing = out.get("preprocessing")
        if isinstance(preprocessing, dict):
            _normalize_preprocessing_nested_keys(preprocessing)

    simulation = out.get("simulation")
    if isinstance(simulation, dict):
        solver = simulation.get("solver")
        if isinstance(solver, dict) and "method" in solver and "kind" not in solver:
            solver["kind"] = solver.pop("method")

    postprocessing = out.get("postprocessing")
    if isinstance(postprocessing, dict):
        if "csv_sep" in postprocessing and "csv_separator" not in postprocessing:
            postprocessing["csv_separator"] = postprocessing.pop("csv_sep")
        if "csv_delimiter" in postprocessing and "csv_separator" not in postprocessing:
            postprocessing["csv_separator"] = postprocessing.pop("csv_delimiter")
        if "outdir" in postprocessing and postprocessing.get("outdir") is not None:
            postprocessing["outdir"] = str(postprocessing.get("outdir") or "").strip() or None
        if "auto_update_initial_conditions" not in postprocessing:
            postprocessing["auto_update_initial_conditions"] = True
        if "csv_enabled" not in postprocessing:
            postprocessing["csv_enabled"] = True
        if "excel_enabled" not in postprocessing:
            postprocessing["excel_enabled"] = False
        if "excel_path" not in postprocessing:
            csv_path = str(postprocessing.get("csv_path") or "results/out.csv")
            if csv_path.lower().endswith('.csv'):
                postprocessing["excel_path"] = csv_path[:-4] + '.xlsx'
            else:
                postprocessing["excel_path"] = 'results/out.xlsx'

        sampling = postprocessing.get("sampling")
        if isinstance(sampling, dict):
            if sampling.get("mode") == "angle":
                sampling["mode"] = "crank_angle"
            if "step_ca_deg" in sampling and "step_deg" not in sampling:
                sampling["step_deg"] = sampling.pop("step_ca_deg")
        if "final_cycle_uniform_angle_export" not in postprocessing:
            postprocessing["final_cycle_uniform_angle_export"] = {
                "enabled": False,
                "step_deg": 1.0,
            }
        if "free_piston_last_ut_ot_ut_export" not in postprocessing:
            postprocessing["free_piston_last_ut_ot_ut_export"] = {
                "enabled": False,
                "step_deg": 1.0,
                "axis_min_deg": 0.0,
                "axis_max_deg": 360.0,
            }
        elif isinstance(postprocessing.get("free_piston_last_ut_ot_ut_export"), dict):
            postprocessing["free_piston_last_ut_ot_ut_export"].setdefault("axis_min_deg", 0.0)
            postprocessing["free_piston_last_ut_ot_ut_export"].setdefault("axis_max_deg", 360.0)
        if "check_report" not in postprocessing:
            postprocessing["check_report"] = {
                "enabled": True,
                "html_enabled": False,
            }
        plots = postprocessing.get("plots")
        if not isinstance(plots, dict):
            plots = {
                "enabled": True,
                "source": "last_cycle_uniform",
                "output_dir": "results/plots",
                "layouts": {
                    "auto_create_defaults": True,
                    "entries": [],
                },
            }
            postprocessing["plots"] = plots
        else:
            plots.pop("pressure_plot", None)
            plots.setdefault("enabled", True)
            plots.setdefault("source", "last_cycle_uniform")
            plots.setdefault("output_dir", "results/plots")
            layouts = plots.get("layouts")
            if not isinstance(layouts, dict):
                plots["layouts"] = {"auto_create_defaults": True, "entries": []}
            else:
                layouts.setdefault("auto_create_defaults", True)
                layouts.setdefault("entries", [])
        if "console" not in postprocessing:
            postprocessing["console"] = {
                "run_summary": {"enabled": True},
                "cycle_summary": {"enabled": True},
                "check_report": {"enabled": True},
                "geometry": {"enabled": True},
            }

    sync_initial_states_inplace(out)
    return stamp_current_versioning(
        out,
        migrated_from=previous_schema,
        migration_applied=bool(requires_version_upgrade(config_data)),
    )




def normalize_config_data(config_data: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a canonical current-schema config dict.

    This keeps the current field names, fills a minimal set of missing blocks and
    removes legacy flat version keys in favour of the nested ``versioning`` block.
    """
    out = migrate_config_data(config_data)
    out = _deepcopy_mapping(out)
    out.setdefault("test_description", out.get("test_description") or "")
    out.setdefault("modeling", {"architecture": "classic"})
    pre = out.setdefault("preprocessing", {})
    pre.setdefault("gas_properties", {"cp_J_per_kgK": 1005.0, "cv_J_per_kgK": 718.0, "R_J_per_kgK": 287.0, "thermo_model": "constant"})
    pre.setdefault("features", {"mass_flow": True, "wall_heat": False, "combustion": False, "evaporation": False, "pv_work": True})
    pre.setdefault("submodels", {"volumes": {}, "wall_heat": {}, "wall_temperature": {}, "combustion": {}, "connections": {}})
    pre.setdefault("engine", {"cycle_type": "4t", "speed_rpm": 3000.0})
    pre.setdefault("volumes", [])
    pre.setdefault("connections", [])
    sync_initial_states_inplace(out)

    sim = out.setdefault("simulation", {})
    sim.setdefault("dt_s", 1.0e-5)
    sim.setdefault("total_cycles", 6)
    sim.setdefault("save_last_cycles", 1)
    solver = sim.setdefault("solver", {})
    solver.setdefault("kind", "rk4")
    solver.setdefault("rtol", 1.0e-6)
    solver.setdefault("atol", 1.0e-9)

    post = out.setdefault("postprocessing", {})
    if "outdir" in post and post.get("outdir") is not None:
        post["outdir"] = str(post.get("outdir") or "").strip() or None
    post.setdefault("auto_update_initial_conditions", True)
    post.setdefault("csv_enabled", True)
    post.setdefault("csv_path", "results/out.csv")
    post.setdefault("csv_separator", ";")
    post.setdefault("excel_enabled", False)
    if "excel_path" not in post:
        csv_path = str(post.get("csv_path") or "results/out.csv")
        post["excel_path"] = csv_path[:-4] + ".xlsx" if csv_path.lower().endswith(".csv") else "results/out.xlsx"
    sampling = post.setdefault("sampling", {})
    sampling.setdefault("mode", "crank_angle")
    if sampling.get("mode") == "time":
        sampling.setdefault("step_s", 1.0e-4)
        sampling.pop("step_deg", None)
    else:
        sampling["mode"] = "crank_angle"
        sampling.setdefault("step_deg", 1.0)
        sampling.pop("step_s", None)
    post.setdefault("final_cycle_uniform_angle_export", {"enabled": False, "step_deg": 1.0})
    post.setdefault("free_piston_last_ut_ot_ut_export", {"enabled": False, "step_deg": 1.0, "axis_min_deg": 0.0, "axis_max_deg": 360.0})
    if isinstance(post.get("free_piston_last_ut_ot_ut_export"), dict):
        post["free_piston_last_ut_ot_ut_export"].setdefault("axis_min_deg", 0.0)
        post["free_piston_last_ut_ot_ut_export"].setdefault("axis_max_deg", 360.0)
    post.setdefault("check_report", {"enabled": True, "html_enabled": False})
    post.setdefault("plots", {
        "enabled": True,
        "source": "last_cycle_uniform",
        "output_dir": "results/plots",
        "layouts": {"auto_create_defaults": True, "entries": []},
    })
    if isinstance(post.get("plots"), dict):
        post["plots"].pop("pressure_plot", None)
    post.setdefault("console", {
        "run_summary": {"enabled": True},
        "cycle_summary": {"enabled": True},
        "check_report": {"enabled": True},
        "geometry": {"enabled": True},
    })

    for key in LEGACY_TOP_LEVEL_VERSION_KEYS:
        out.pop(key, None)
    out[VERSIONING_KEY] = current_versioning_dict()
    return out


def diff_config_dicts(old: Mapping[str, Any] | None, new: Mapping[str, Any] | None) -> list[str]:
    """Create a compact line-based diff summary for two nested mappings."""
    lines: list[str] = []

    def walk(prefix: str, left: Any, right: Any) -> None:
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            keys = sorted(set(left.keys()) | set(right.keys()))
            for key in keys:
                next_prefix = f"{prefix}.{key}" if prefix else str(key)
                if key not in left:
                    lines.append(f"+ {next_prefix} = {right[key]!r}")
                elif key not in right:
                    lines.append(f"- {next_prefix} = {left[key]!r}")
                else:
                    walk(next_prefix, left[key], right[key])
            return
        if isinstance(left, list) and isinstance(right, list):
            if left != right:
                lines.append(f"~ {prefix} = {left!r} -> {right!r}")
            return
        if left != right:
            lines.append(f"~ {prefix} = {left!r} -> {right!r}")

    walk("", dict(old or {}), dict(new or {}))
    return lines

def build_upgrade_message(path: Path, loaded_schema: int) -> str:
    return (
        f'Die Konfiguration "{path.name}" verwendet die alte Schema-Version {loaded_schema}.\n\n'
        f"Aktuell erwartet der Editor Schema-Version {CURRENT_CONFIG_SCHEMA_VERSION}.\n"
        "Bei Bestätigung wird die Datei auf die aktuelle Version aktualisiert."
    )


def migrate_yaml_text(text: str, upgraded_config: Mapping[str, Any] | None) -> str:
    """Apply migration changes textually so comments remain intact as far as possible."""
    result = text
    replacements = [
        (r"(?m)^(\s*)heat_transfer(\s*:)" , r"\1wall_heat\2"),
        (r"(?m)^(\s*)method(\s*:)" , r"\1kind\2"),
        (r"(?m)^(\s*)csv_sep(\s*:)" , r"\1csv_separator\2"),
        (r"(?m)^(\s*)csv_delimiter(\s*:)" , r"\1csv_separator\2"),
        (r"(?m)^(\s*)step_ca_deg(\s*:)" , r"\1step_deg\2"),
        (r"(?m)^(\s*)angle_ref(\s*:)" , r"\1angle_reference\2"),
        (r"(?m)^(\s*)opening_ref(\s*:)" , r"\1opening_reference\2"),
        (r"(?m)^(\s*)alphak_file(\s*:)" , r"\1alpha_k_file\2"),
        (r"(?m)^(\s*)number_of_holes(\s*:)" , r"\1number_of_identical_holes\2"),
        (r"(?m)^(\s*)forward_discharge_coefficient(\s*:)" , r"\1forward_cd\2"),
        (r"(?m)^(\s*)reverse_discharge_coefficient(\s*:)" , r"\1reverse_cd\2"),
    ]
    for pattern, repl in replacements:
        result = re.sub(pattern, repl, result)
    result = re.sub(r"(?m)^(\s*mode\s*:)\s*angle\s*(#.*)?$", r"\1 crank_angle \2", result)
    result = re.sub(r"(?m)[ \t]+$", "", result)

    result = _ensure_yaml_postprocessing_defaults(result, upgraded_config)
    versioning = extract_raw_versioning(upgraded_config)
    return _rewrite_yaml_versioning_block(result, versioning)


def migrate_config_file_in_place(path: Path, loaded_config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Update the on-disk config version metadata and return the upgraded document.

    For YAML files the update is applied textually so that existing user comments are
    preserved. For JSON files the updated document is written back as formatted JSON.
    """
    path = Path(path)
    upgraded = migrate_config_data(loaded_config)
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        original_text = path.read_text(encoding="utf-8")
        updated_text = migrate_yaml_text(original_text, upgraded)
        path.write_text(updated_text, encoding="utf-8")
    else:
        path.write_text(json.dumps(upgraded, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return upgraded


def _rename_if_present(data: dict[str, Any], old_key: str, new_key: str) -> None:
    if old_key in data and new_key not in data:
        data[new_key] = data.pop(old_key)


def _ensure_yaml_postprocessing_defaults(text: str, upgraded_config: Mapping[str, Any] | None) -> str:
    result = text
    postprocessing = upgraded_config.get("postprocessing") if isinstance(upgraded_config, Mapping) else None
    if not isinstance(postprocessing, Mapping):
        return result

    lines = result.splitlines(keepends=True)
    insert_at = None
    post_indent = ""
    for idx, line in enumerate(lines):
        m = re.match(r"^(\s*)postprocessing\s*:\s*(#.*)?(?:\n)?$", line)
        if not m:
            continue
        post_indent = m.group(1)
        insert_at = idx + 1
        j = idx + 1
        while j < len(lines):
            raw = lines[j]
            stripped = raw.strip()
            if stripped == "":
                j += 1
                continue
            current_indent = len(raw) - len(raw.lstrip(" "))
            if current_indent <= len(post_indent):
                insert_at = j
                break
            insert_at = j + 1
            j += 1
        break

    blocks_to_add: list[tuple[str, Mapping[str, Any]]] = []
    for key in ("auto_update_initial_conditions", "final_cycle_uniform_angle_export", "free_piston_last_ut_ot_ut_export", "check_report", "plots", "console"):
        value = postprocessing.get(key)
        if isinstance(value, Mapping):
            blocks_to_add.append((key, value))

    if insert_at is None:
        if not blocks_to_add:
            return result
        block_data = {"postprocessing": {key: value for key, value in blocks_to_add}}
        block = yaml.safe_dump(block_data, sort_keys=False, allow_unicode=True)
        return result.rstrip() + "\n" + block

    child_indent = post_indent + "  "
    blocks: list[str] = []
    for key, value in blocks_to_add:
        if re.search(rf"(?m)^\s*{re.escape(key)}\s*:", result):
            continue
        dumped = yaml.safe_dump({key: value}, sort_keys=False, allow_unicode=True).rstrip()
        indented = "\n".join((child_indent + line) if line else line for line in dumped.splitlines()) + "\n"
        blocks.append(indented)
    if not blocks:
        return result
    lines.insert(insert_at, "".join(blocks))
    return "".join(lines)


def _rewrite_yaml_versioning_block(text: str, versioning: Mapping[str, Any]) -> str:
    block_text = _yaml_versioning_block(versioning)
    body = re.sub(r"(?ms)^versioning:\s*\n(?:^[ \t].*\n|^\s*\n)*", "", text)
    for key in LEGACY_TOP_LEVEL_VERSION_KEYS:
        body = re.sub(rf"(?m)^{re.escape(key)}\s*:\s*.*(?:\n|$)", "", body)
    lines = body.splitlines(keepends=True)
    insert_at = _yaml_insert_index(lines)
    result = "".join(lines[:insert_at] + [block_text] + lines[insert_at:])
    return re.sub(r"\n{3,}", "\n\n", result)


def _yaml_insert_index(lines: list[str]) -> int:
    idx = 0
    while idx < len(lines):
        stripped = lines[idx].strip()
        if idx == 0 and stripped.startswith("%YAML"):
            idx += 1
            continue
        if stripped == "---":
            idx += 1
            continue
        if stripped == "" or lines[idx].lstrip().startswith("#"):
            idx += 1
            continue
        break
    return idx


def _yaml_versioning_block(versioning: Mapping[str, Any]) -> str:
    pkg = str(versioning.get("package_version", __version__))
    schema = int(versioning.get("config_schema_version", CURRENT_CONFIG_SCHEMA_VERSION))
    loaded_schema = int(versioning.get("loaded_config_schema_version", schema))
    migrated = "true" if bool(versioning.get("migration_applied", False)) else "false"
    return (
        "# Versionsstand dieser Konfigurationsdatei.\n"
        "# Dieser Block wird von den Editoren beim Laden geprüft und bei Bedarf aktualisiert.\n"
        "versioning:\n"
        f"  package_version: '{pkg}'\n"
        f"  config_schema_version: {schema}\n"
        f"  loaded_config_schema_version: {loaded_schema}\n"
        f"  migration_applied: {migrated}\n\n"
    )
