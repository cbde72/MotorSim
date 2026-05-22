from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from thermo0d.model.free_piston.cycle_metrics import detect_turning_points
from thermo0d.model.free_piston.geometry import bounce_volume_from_position
from thermo0d.output.reconstruction import SignalReconstructionService


_AUTO_COMMENT_TAG = "previous_auto_initial_state_from_last_compression_at_x0_m"


@dataclass(slots=True, frozen=True)
class RestartStateSample:
    t_s: float
    cycle_index: int
    x_target_m: float
    x_sample_m: float
    v_sample_m_per_s: float
    start_sample_index: int
    end_sample_index: int
    columns: dict[str, float]


@dataclass(slots=True, frozen=True)
class ConfigUpdateResult:
    changed: bool
    changed_entries: int
    sample: RestartStateSample | None = None
    reason: str | None = None


@dataclass(slots=True, frozen=True)
class _BlockRange:
    line_index: int
    indent: int
    body_start: int
    body_end: int


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except Exception:
        return None
    if not math.isfinite(out):
        return None
    return out


def _format_yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite float cannot be written to YAML")
        return repr(float(value))
    return str(value)


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_volume_defs_from_yaml_text(text: str) -> list[tuple[str, str]]:
    try:
        raw = yaml.safe_load(text)
    except Exception:
        return []
    if not isinstance(raw, dict):
        return []
    preprocessing = raw.get("preprocessing")
    if not isinstance(preprocessing, dict):
        return []
    submodel_volume_types: dict[str, str] = {}
    submodels = preprocessing.get("submodels")
    if isinstance(submodels, dict):
        submodel_volumes = submodels.get("volumes")
        if isinstance(submodel_volumes, dict):
            for ref_name, ref_payload in submodel_volumes.items():
                if not isinstance(ref_payload, dict):
                    continue
                ref_type = str(ref_payload.get("type") or "").strip()
                if ref_type:
                    submodel_volume_types[str(ref_name).strip()] = ref_type
    volumes = preprocessing.get("volumes")
    if not isinstance(volumes, list):
        return []
    out: list[tuple[str, str]] = []
    for vol in volumes:
        if not isinstance(vol, dict):
            continue
        name = str(vol.get("name") or "").strip()
        vtype = str(vol.get("type") or "").strip()
        if not vtype:
            ref_name = str(vol.get("ref") or "").strip()
            vtype = submodel_volume_types.get(ref_name, "")
        if name:
            out.append((name, vtype))
    return out


def _is_blank_or_comment(line: str) -> bool:
    stripped = line.strip()
    return stripped == "" or stripped.startswith("#")


def _find_mapping_block(lines: list[str], start: int, end: int, key: str, indent: int) -> _BlockRange | None:
    pattern = re.compile(rf"^{' ' * indent}{re.escape(key)}\s*:\s*(?:#.*)?$")
    idx = start
    while idx < end:
        line = lines[idx].rstrip("\n")
        if pattern.match(line):
            body_start = idx + 1
            body_end = end
            j = idx + 1
            while j < end:
                raw = lines[j].rstrip("\n")
                if _is_blank_or_comment(raw):
                    j += 1
                    continue
                raw_indent = _line_indent(raw)
                if raw_indent < indent:
                    body_end = j
                    break
                if raw_indent == indent and not raw.lstrip().startswith("-"):
                    body_end = j
                    break
                j += 1
            return _BlockRange(idx, indent, body_start, body_end)
        idx += 1
    return None


def _find_list_item_block_by_name(lines: list[str], start: int, end: int, item_indent: int, name_value: str) -> _BlockRange | None:
    inline_pattern = re.compile(rf"^{' ' * item_indent}-\s*name\s*:\s*(.*?)\s*(?:#.*)?$")
    key_pattern = re.compile(rf"^{' ' * (item_indent + 2)}name\s*:\s*(.*?)\s*(?:#.*)?$")
    idx = start
    wanted = str(name_value).strip()
    while idx < end:
        raw = lines[idx].rstrip("\n")
        m_inline = inline_pattern.match(raw)
        item_start = None
        found_name = None
        if m_inline:
            item_start = idx
            found_name = m_inline.group(1).strip().strip('"\'')
        elif re.match(rf"^{' ' * item_indent}-\s*(?:#.*)?$", raw):
            j = idx + 1
            while j < end:
                inner = lines[j].rstrip("\n")
                if _is_blank_or_comment(inner):
                    j += 1
                    continue
                if _line_indent(inner) <= item_indent:
                    break
                m_key = key_pattern.match(inner)
                if m_key:
                    item_start = idx
                    found_name = m_key.group(1).strip().strip('"\'')
                    break
                j += 1
        if item_start is not None and found_name == wanted:
            body_start = item_start + 1
            body_end = end
            j = item_start + 1
            while j < end:
                inner = lines[j].rstrip("\n")
                if _is_blank_or_comment(inner):
                    j += 1
                    continue
                if _line_indent(inner) < item_indent:
                    body_end = j
                    break
                if _line_indent(inner) == item_indent and inner.lstrip().startswith("-"):
                    body_end = j
                    break
                j += 1
            return _BlockRange(item_start, item_indent, body_start, body_end)
        idx += 1
    return None


def _replace_scalar_in_block(lines: list[str], block: _BlockRange, key: str, value: Any, *, allow_insert: bool = True) -> bool:
    child_indent = block.indent + 2
    pattern = re.compile(rf"^{' ' * child_indent}{re.escape(key)}\s*:\s*(.*?)(\s+#.*)?$")
    comment_pattern = re.compile(rf"^{' ' * child_indent}#\s*{re.escape(_AUTO_COMMENT_TAG)}:\s*{re.escape(key)}\s*:")
    new_value = _format_yaml_scalar(value)

    scalar_matches: list[tuple[int, str, str]] = []
    comment_indices: list[int] = []
    idx = block.body_start
    while idx < block.body_end:
        raw = lines[idx].rstrip("\n")
        m = pattern.match(raw)
        if m:
            scalar_matches.append((idx, m.group(1).rstrip(), m.group(2) or ""))
        elif comment_pattern.match(raw):
            comment_indices.append(idx)
        idx += 1

    if scalar_matches:
        first_idx = min([scalar_matches[0][0], *comment_indices]) if comment_indices else scalar_matches[0][0]
        old_value = scalar_matches[-1][1]
        suffix = scalar_matches[-1][2]
        new_line = f"{' ' * child_indent}{key}: {new_value}{suffix}\n"
        changed = (old_value != new_value) or bool(comment_indices) or (len(scalar_matches) != 1)
        remove_indices = sorted({*comment_indices, *(idx for idx, _, _ in scalar_matches)}, reverse=True)
        for remove_idx in remove_indices:
            del lines[remove_idx]
        insert_at = first_idx
        for remove_idx in remove_indices:
            if remove_idx < first_idx:
                insert_at -= 1
        if changed and old_value != new_value:
            comment_line = f"{' ' * child_indent}# {_AUTO_COMMENT_TAG}: {key}: {old_value}\n"
            lines.insert(insert_at, comment_line)
            insert_at += 1
        lines.insert(insert_at, new_line)
        return changed

    if not allow_insert:
        return False
    insert_at = block.body_end
    line = f"{' ' * child_indent}{key}: {new_value}\n"
    lines.insert(insert_at, line)
    return True


def _sample_last_compression_at_x0(bundle, t: np.ndarray, y: np.ndarray, cycle_indices: np.ndarray) -> RestartStateSample | None:
    if getattr(bundle, "architecture", "classic") != "free_piston":
        return None
    fp = getattr(bundle, "free_piston", None)
    if fp is None:
        return None
    t_arr = np.asarray(t, dtype=np.float64)
    y_arr = np.asarray(y, dtype=np.float64)
    cycle_idx_arr = np.asarray(cycle_indices, dtype=np.int64)
    if t_arr.ndim != 1 or y_arr.ndim != 2 or t_arr.size < 5 or y_arr.shape[1] != t_arr.size:
        return None

    x_idx = int(fp.x_state_index)
    v_idx = int(fp.v_state_index)
    if x_idx < 0 or v_idx < 0 or x_idx >= y_arr.shape[0] or v_idx >= y_arr.shape[0]:
        return None

    x_arr = np.asarray(y_arr[x_idx], dtype=np.float64)
    v_arr = np.asarray(y_arr[v_idx], dtype=np.float64)
    max_v = float(np.max(np.abs(v_arr))) if v_arr.size else 0.0
    turning_points = detect_turning_points(t_arr, x_arr, v_arr, eps=max(1.0e-10, 1.0e-6 * max_v))
    if len(turning_points) < 3:
        return None

    triplet = None
    for i in range(len(turning_points) - 3, -1, -1):
        a = turning_points[i]
        b = turning_points[i + 1]
        c = turning_points[i + 2]
        if a.sample_index >= b.sample_index or b.sample_index >= c.sample_index:
            continue
        if float(a.x_m) > float(b.x_m) and float(c.x_m) > float(b.x_m):
            triplet = (a, b, c)
            break
    if triplet is None:
        return None

    tp_ut0, tp_ot, _tp_ut1 = triplet
    i0 = int(tp_ut0.sample_index)
    i1 = int(tp_ot.sample_index)
    if i1 <= i0:
        return None

    x_target = float(fp.x0_m)
    pair_index = None
    frac = 0.0
    tol = 1.0e-12
    for j in range(i0, i1):
        xa = float(x_arr[j])
        xb = float(x_arr[j + 1])
        in_range = (xa - x_target) * (xb - x_target) <= 0.0
        if not in_range:
            continue
        dx = xb - xa
        if abs(dx) <= tol:
            frac = 0.0
        else:
            frac = (x_target - xa) / dx
        frac = min(max(frac, 0.0), 1.0)
        v_est = (1.0 - frac) * float(v_arr[j]) + frac * float(v_arr[j + 1])
        if v_est > 1.0e-9:
            continue
        pair_index = j
        break
    if pair_index is None:
        return None

    j = int(pair_index)
    t_sample = float(t_arr[j] + frac * (t_arr[j + 1] - t_arr[j]))
    y_sample = y_arr[:, j] + frac * (y_arr[:, j + 1] - y_arr[:, j])
    cycle_sample = int(cycle_idx_arr[min(j, cycle_idx_arr.size - 1)]) if cycle_idx_arr.size else 0

    series = SignalReconstructionService.build(
        bundle,
        np.asarray([t_sample], dtype=np.float64),
        np.asarray(y_sample, dtype=np.float64).reshape((-1, 1)),
        np.asarray([cycle_sample], dtype=np.int64),
    )
    columns: dict[str, float] = {}
    for key, arr in series.as_columns().items():
        arr_np = np.asarray(arr)
        if arr_np.size != 1:
            continue
        value = _as_float(arr_np.reshape(-1)[0])
        if value is None:
            continue
        columns[str(key)] = float(value)
    x_sample = columns.get("free_piston_x_m", x_target)
    v_sample = columns.get("free_piston_v_m_per_s", float(y_sample[v_idx]))
    bounce_volume_m3 = bounce_volume_from_position(
        float(fp.bounce_chamber_volume0_m3),
        float(fp.bounce_area_m2),
        float(x_sample),
        float(fp.x_min_m),
        float(fp.x_max_m),
    )
    if bounce_volume_m3 > 1.0e-18:
        bounce_ratio = float(fp.bounce_chamber_volume0_m3) / float(bounce_volume_m3)
        bounce_n = float(fp.bounce_polytropic_exponent)
        bounce_pressure = float(fp.bounce_p0_Pa) * (bounce_ratio ** bounce_n)
        bounce_temperature = float(fp.bounce_temperature_K) * (bounce_ratio ** (bounce_n - 1.0))
        bounce_model = str(getattr(fp, "bounce_model", "")).strip().lower()
        if bounce_model != "gas_exchange":
            columns["bounce_pressure_Pa"] = bounce_pressure
            columns["bounce_p_Pa"] = bounce_pressure
            columns["bounce_T_K"] = bounce_temperature
        else:
            columns.setdefault("bounce_pressure_Pa", bounce_pressure)
            columns.setdefault("bounce_p_Pa", columns["bounce_pressure_Pa"])
            columns.setdefault("bounce_T_K", bounce_temperature)
    return RestartStateSample(
        t_s=t_sample,
        cycle_index=cycle_sample,
        x_target_m=x_target,
        x_sample_m=float(x_sample),
        v_sample_m_per_s=float(v_sample),
        start_sample_index=j,
        end_sample_index=j + 1,
        columns=columns,
    )


def _update_free_piston_initial_conditions(lines: list[str], sample: RestartStateSample, *, has_stateful_bounce: bool) -> int:
    changed = 0
    fp_block = _find_mapping_block(lines, 0, len(lines), "free_piston", 0)
    if fp_block is None:
        return 0
    init_block = _find_mapping_block(lines, fp_block.body_start, fp_block.body_end, "initial_conditions", 2)
    if init_block is None:
        return 0

    if _replace_scalar_in_block(lines, init_block, "v0_m_per_s", sample.v_sample_m_per_s, allow_insert=True):
        changed += 1
        init_block = _find_mapping_block(lines, fp_block.body_start, fp_block.body_end + 8, "initial_conditions", 2) or init_block

    cyl_block = _find_mapping_block(lines, init_block.body_start, init_block.body_end, "cylinder", 4)
    if cyl_block is not None:
        p = sample.columns.get("cylinder_p_Pa")
        T = sample.columns.get("cylinder_T_K")
        if p is not None and _replace_scalar_in_block(lines, cyl_block, "pressure_Pa", p, allow_insert=True):
            changed += 1
            cyl_block = _find_mapping_block(lines, init_block.body_start, len(lines), "cylinder", 4) or cyl_block
        if T is not None and _replace_scalar_in_block(lines, cyl_block, "temperature_K", T, allow_insert=True):
            changed += 1

    combustion_state_block = _find_mapping_block(lines, init_block.body_start, len(lines), "combustion_state", 4)
    if combustion_state_block is not None:
        cylinder_mass = sample.columns.get("cylinder_m_kg")
        cylinder_burned_mass = sample.columns.get("cylinder_m_burned_kg")
        if cylinder_mass is not None and cylinder_burned_mass is not None and cylinder_mass > 1.0e-18:
            burned_fraction = max(0.0, min(1.0, float(cylinder_burned_mass) / float(cylinder_mass)))
            if _replace_scalar_in_block(lines, combustion_state_block, "burned_fraction_0to1", burned_fraction, allow_insert=True):
                changed += 1
                combustion_state_block = _find_mapping_block(lines, init_block.body_start, len(lines), "combustion_state", 4) or combustion_state_block
            if _replace_scalar_in_block(lines, combustion_state_block, "burned_mass_percent", 100.0 * burned_fraction, allow_insert=True):
                changed += 1

    bounce_block = _find_mapping_block(lines, init_block.body_start, len(lines), "bounce", 4)
    if bounce_block is not None:
        bounce_p = sample.columns.get("bounce_p_Pa") if has_stateful_bounce else sample.columns.get("bounce_pressure_Pa")
        bounce_T = sample.columns.get("bounce_T_K") if has_stateful_bounce else None
        if bounce_p is not None and _replace_scalar_in_block(lines, bounce_block, "pressure_Pa", bounce_p, allow_insert=True):
            changed += 1
            bounce_block = _find_mapping_block(lines, init_block.body_start, len(lines), "bounce", 4) or bounce_block
        if bounce_T is not None and _replace_scalar_in_block(lines, bounce_block, "temperature_K", bounce_T, allow_insert=True):
            changed += 1

    return changed


def _update_preprocessing_volume_initials(lines: list[str], sample: RestartStateSample, volume_defs: list[tuple[str, str]], *, bounce_temperature_fallback_K: float | None = None) -> int:
    changed = 0
    pre_block = _find_mapping_block(lines, 0, len(lines), "preprocessing", 0)
    if pre_block is None:
        return 0
    vols_block = _find_mapping_block(lines, pre_block.body_start, pre_block.body_end, "volumes", 2)
    if vols_block is None:
        return 0

    for name, vtype in volume_defs:
        vtype_norm = str(vtype).strip().lower()
        if vtype_norm not in {"cylinder", "plenum", "bounce_chamber"}:
            continue

        vols_block = _find_mapping_block(lines, pre_block.body_start, len(lines), "volumes", 2) or vols_block
        item_block = _find_list_item_block_by_name(lines, vols_block.body_start, vols_block.body_end, vols_block.indent + 2, name)
        if item_block is None:
            continue

        p = sample.columns.get(f"{name}_p_Pa")
        T = sample.columns.get(f"{name}_T_K")
        m = sample.columns.get(f"{name}_m_kg")
        m_burned = sample.columns.get(f"{name}_m_burned_kg")

        if vtype_norm == "cylinder":
            if p is None:
                p = sample.columns.get("cylinder_p_Pa")
            if T is None:
                T = sample.columns.get("cylinder_T_K")
            if m is None:
                m = sample.columns.get("cylinder_m_kg")
            if m_burned is None:
                m_burned = sample.columns.get("cylinder_m_burned_kg")
        elif vtype_norm == "bounce_chamber":
            p = p if p is not None else sample.columns.get("bounce_pressure_Pa")
            if T is None:
                T = sample.columns.get("bounce_T_K")
            if T is None and bounce_temperature_fallback_K is not None and math.isfinite(float(bounce_temperature_fallback_K)):
                T = float(bounce_temperature_fallback_K)

        burned_fraction = None
        if m is not None and m_burned is not None and m > 1.0e-18:
            burned_fraction = max(0.0, min(1.0, float(m_burned) / float(m)))

        if p is not None and _replace_scalar_in_block(lines, item_block, "initial_pressure_Pa", p, allow_insert=True):
            changed += 1
            vols_block = _find_mapping_block(lines, pre_block.body_start, len(lines), "volumes", 2) or vols_block
            item_block = _find_list_item_block_by_name(lines, vols_block.body_start, vols_block.body_end, vols_block.indent + 2, name) or item_block

        if T is not None and _replace_scalar_in_block(lines, item_block, "initial_temperature_K", T, allow_insert=True):
            changed += 1
            vols_block = _find_mapping_block(lines, pre_block.body_start, len(lines), "volumes", 2) or vols_block
            item_block = _find_list_item_block_by_name(lines, vols_block.body_start, vols_block.body_end, vols_block.indent + 2, name) or item_block

        if m is not None and _replace_scalar_in_block(lines, item_block, "initial_mass_kg", m, allow_insert=False):
            changed += 1
            vols_block = _find_mapping_block(lines, pre_block.body_start, len(lines), "volumes", 2) or vols_block
            item_block = _find_list_item_block_by_name(lines, vols_block.body_start, vols_block.body_end, vols_block.indent + 2, name) or item_block

        if burned_fraction is not None and _replace_scalar_in_block(lines, item_block, "initial_burned_fraction_0to1", burned_fraction, allow_insert=True):
            changed += 1
            vols_block = _find_mapping_block(lines, pre_block.body_start, len(lines), "volumes", 2) or vols_block
            item_block = _find_list_item_block_by_name(lines, vols_block.body_start, vols_block.body_end, vols_block.indent + 2, name) or item_block

        if burned_fraction is not None and _replace_scalar_in_block(lines, item_block, "initial_burned_mass_percent", 100.0 * burned_fraction, allow_insert=True):
            changed += 1
    return changed


def update_config_initials_from_last_compression_at_x0(
    config_path: str | Path,
    *,
    bundle,
    t: np.ndarray,
    y: np.ndarray,
    cycle_indices: np.ndarray,
    enabled: bool = True,
) -> ConfigUpdateResult:
    if not enabled:
        return ConfigUpdateResult(changed=False, changed_entries=0, reason="disabled")
    path = Path(config_path).resolve()
    if path.suffix.lower() not in {".yaml", ".yml"}:
        return ConfigUpdateResult(changed=False, changed_entries=0, reason="unsupported-format")
    if getattr(bundle, "architecture", "classic") != "free_piston":
        return ConfigUpdateResult(changed=False, changed_entries=0, reason="not-free-piston")

    sample = _sample_last_compression_at_x0(bundle, t, y, cycle_indices)
    if sample is None:
        return ConfigUpdateResult(changed=False, changed_entries=0, reason="no-last-compression-crossing-at-x0")

    try:
        original_text = path.read_text(encoding="utf-8")
    except OSError:
        return ConfigUpdateResult(changed=False, changed_entries=0, sample=sample, reason="read-failed")

    lines = original_text.splitlines(keepends=True)
    volume_defs = _parse_volume_defs_from_yaml_text(original_text)
    has_stateful_bounce = bool("bounce_p_Pa" in sample.columns and "bounce_T_K" in sample.columns)
    changed = 0
    changed += _update_free_piston_initial_conditions(lines, sample, has_stateful_bounce=has_stateful_bounce)
    changed += _update_preprocessing_volume_initials(
        lines,
        sample,
        volume_defs,
        bounce_temperature_fallback_K=getattr(getattr(bundle, "free_piston", None), "bounce_temperature_K", None),
    )

    if changed <= 0:
        return ConfigUpdateResult(changed=False, changed_entries=0, sample=sample, reason="no-config-lines-updated")

    updated_text = "".join(lines)
    if updated_text == original_text:
        return ConfigUpdateResult(changed=False, changed_entries=0, sample=sample, reason="unchanged")

    try:
        path.write_text(updated_text, encoding="utf-8")
    except OSError:
        return ConfigUpdateResult(changed=False, changed_entries=0, sample=sample, reason="write-failed")
    return ConfigUpdateResult(changed=True, changed_entries=changed, sample=sample, reason=None)
