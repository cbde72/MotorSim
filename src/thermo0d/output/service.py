from __future__ import annotations

from dataclasses import dataclass, field
import csv
from pathlib import Path
from time import perf_counter

import numpy as np

from thermo0d.app.paths import PathManager
from thermo0d.model.free_piston.cycle_metrics import detect_turning_points
from thermo0d.output.check_report import LastCycleCheckReportBuilder
from thermo0d.output.console import ConsoleArtifactReporter, ConsoleProgressReporter, ConsoleTimingReporter
from thermo0d.output.engineering_units import (
    ExportLayoutSpec,
    convert_export_key_to_engineering_units,
    convert_rows_to_engineering_units,
    convert_rows_to_layout_units,
)
from thermo0d.output.exporters import CsvExporter, ExcelExporter
from thermo0d.output.reconstruction import ReconstructedSeries, SignalReconstructionService
from thermo0d.output.rows import ResultRowBuilder
from thermo0d.output.sampling import OutputSampler


@dataclass(slots=True)
class PostprocessingArtifacts:
    csv_path: str | None
    excel_path: str | None
    export_rows: list[dict[str, float | int]]
    last_cycle_uniform_csv_path: str | None = None
    last_cycle_uniform_rows: list[dict[str, float | int]] | None = None
    free_piston_last_ut_ot_ut_csv_path: str | None = None
    free_piston_last_ut_ot_ut_rows: list[dict[str, float | int]] | None = None
    check_report_csv_path: str | None = None
    check_report_html_path: str | None = None
    check_report_metrics: list[object] | None = None
    export_series: ReconstructedSeries | None = None
    last_cycle_uniform_series: ReconstructedSeries | None = None
    free_piston_last_ut_ot_ut_series: ReconstructedSeries | None = None
    timings: dict[str, float] = field(default_factory=dict)


class PostprocessingService:
    def __init__(self, bundle, config_path: str | Path):
        self.bundle = bundle
        self.config_path = Path(config_path).resolve()

    def _configured_outdir(self) -> str | None:
        raw = getattr(self.bundle.postprocessing, 'outdir', None)
        if raw is None:
            return None
        text = str(raw).strip()
        return text or None

    def _output_dir(self) -> Path:
        return PathManager.resolve_output_dir(self.config_path, self._configured_outdir())

    def _resolve_output_path(self, path_text: str | None, *, fallback_name: str) -> Path:
        return PathManager.resolve_output_file(
            self.config_path,
            configured_outdir=self._configured_outdir(),
            configured_path=path_text,
            fallback_name=fallback_name,
        )

    def _base_csv_path(self) -> Path:
        return self._resolve_output_path(getattr(self.bundle.postprocessing, 'csv_path', None), fallback_name='out.csv')

    def _excel_path(self) -> Path:
        configured = str(getattr(self.bundle.postprocessing, 'excel_path', '') or '').strip()
        if configured:
            return self._resolve_output_path(configured, fallback_name='out.xlsx')
        csv_path = self._base_csv_path()
        return csv_path.with_suffix('.xlsx')

    def _is_safe_layout_path(self, path: Path) -> bool:
        resolved = path.resolve()
        allowed_roots = [
            self.config_path.parent.resolve(),
            self.config_path.parent.parent.resolve(),
            self._output_dir().resolve(),
            Path.cwd().resolve(),
        ]
        for root in allowed_roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def _configured_export_layout_path(self) -> Path | None:
        raw = str(getattr(self.bundle.postprocessing, 'csv_export_layout', '') or '').strip()
        if not raw:
            return None
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = self.config_path.parent / candidate
        candidate = candidate.resolve()
        if not self._is_safe_layout_path(candidate):
            ConsoleArtifactReporter.print_status('csv:layout', 'warn', reason=f'unsafe-path: {candidate}')
            return None
        return candidate

    def _export_layout_candidates(self) -> list[Path]:
        names = ('thermo0d_signal_export_layout.csv',)
        configured = self._configured_export_layout_path()
        dirs = [
            self.config_path.parent,
            self.config_path.parent.parent,
            self._output_dir(),
            Path.cwd(),
        ]
        candidates: list[Path] = []
        seen: set[Path] = set()
        if configured is not None:
            candidates.append(configured)
            seen.add(configured)
        for base in dirs:
            for name in names:
                candidate = (base / name).resolve()
                if candidate in seen:
                    continue
                seen.add(candidate)
                candidates.append(candidate)
        return candidates

    def _discover_export_layout_path(self) -> Path | None:
        mode = str(getattr(self.bundle.postprocessing, 'csv_export_mode', 'auto') or 'auto').strip().lower()
        if mode == 'all':
            return None
        for candidate in self._export_layout_candidates():
            if candidate.exists() and candidate.is_file():
                return candidate
        if mode == 'selected':
            policy = str(getattr(self.bundle.postprocessing, 'csv_export_missing_layout', 'warn_all') or 'warn_all').strip().lower()
            message = 'CSV export mode selected, aber keine sichere Export-Layout-Datei gefunden.'
            if policy == 'fail':
                raise FileNotFoundError(message)
            ConsoleArtifactReporter.print_status('csv:layout', 'warn', reason='missing-layout; exporting all columns')
        return None

    def _load_export_layout_spec(self, path: Path | None = None) -> ExportLayoutSpec | None:
        if path is None:
            path = self._discover_export_layout_path()
        if path is None:
            return None
        try:
            sample = path.read_text(encoding='utf-8-sig')
        except Exception:
            return None
        if not sample.strip():
            return None
        delimiter = ';'
        try:
            dialect = csv.Sniffer().sniff(sample[:4096], delimiters=';,	,')
            delimiter = getattr(dialect, 'delimiter', ';') or ';'
        except Exception:
            delimiter = ';' if ';' in sample else ','
        try:
            with path.open('r', encoding='utf-8-sig', newline='') as f:
                rows = list(csv.reader(f, delimiter=delimiter))
        except Exception:
            return None
        if not rows:
            return None

        def _clean_unique(values: list[str]) -> list[str]:
            cleaned: list[str] = []
            seen: set[str] = set()
            for cell in values:
                key = str(cell).strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                cleaned.append(key)
            return cleaned

        keys = _clean_unique(rows[0])
        if not keys:
            return None

        def _row_values(index: int) -> list[str]:
            if index >= len(rows):
                return [''] * len(keys)
            values = [str(cell).strip() for cell in rows[index][:len(keys)]]
            if len(values) < len(keys):
                values.extend([''] * (len(keys) - len(values)))
            return values

        return ExportLayoutSpec(
            keys=keys,
            display_names=_row_values(1),
            short_names=_row_values(2),
            display_units=_row_values(3),
        )

    def _load_export_layout_keys(self) -> list[str]:
        spec = self._load_export_layout_spec()
        return list(spec.keys) if spec is not None else []

    def _layout_header_rows(self, layout: ExportLayoutSpec | None) -> list[list[object]]:
        if layout is None:
            return []
        return [
            list(layout.keys),
            list(layout.display_names),
            list(layout.short_names),
            list(layout.display_units),
        ]

    def _filter_rows_by_keys(self, rows: list[dict[str, float | int]], keys: list[str]) -> list[dict[str, float | int | None]]:
        if not rows or not keys:
            return rows
        return [{key: row.get(key) for key in keys} for row in rows]

    @staticmethod
    def _expand_requested_export_keys(keys: list[str]) -> list[str]:
        expanded = {str(key).strip() for key in keys if str(key).strip()}
        direct_sources = {
            '_wall_heat_cycle_J': '_wall_heat_W',
            '_wall_cylinder_heat_cycle_J': '_wall_cylinder_heat_W',
            '_wall_head_heat_cycle_J': '_wall_head_heat_W',
            '_wall_piston_heat_cycle_J': '_wall_piston_heat_W',
            '_wall_heat_zones_sum_cycle_J': '_wall_heat_zones_sum_W',
            '_added_energy_cycle_J': '_added_energy_W',
            '_enthalpy_in_cycle_J': '_enthalpy_in_W',
            '_enthalpy_out_cycle_J': '_enthalpy_out_W',
            '_piston_work_cycle_J': '_piston_work_W',
            '_evaporation_sink_cycle_J': '_evaporation_sink_W',
            '_mdot_in_cycle_kg': '_mdot_in_kg_per_s',
            '_mdot_out_cycle_kg': '_mdot_out_kg_per_s',
        }
        for key in list(expanded):
            for target_suffix, source_suffix in direct_sources.items():
                if key.endswith(target_suffix):
                    expanded.add(key[:-len(target_suffix)] + source_suffix)

            energy_derived_suffixes = (
                '_delta_U_cycle_J',
                '_enthalpy_net_cycle_J',
                '_energy_balance_residual_J',
                '_indicated_power_W',
            )
            for target_suffix in energy_derived_suffixes:
                if key.endswith(target_suffix):
                    prefix = key[:-len(target_suffix)]
                    for source_suffix in (
                        '_U_J',
                        '_enthalpy_in_W',
                        '_enthalpy_out_W',
                        '_wall_heat_W',
                        '_added_energy_W',
                        '_evaporation_sink_W',
                        '_piston_work_W',
                    ):
                        expanded.add(prefix + source_suffix)

            mass_derived_suffixes = ('_delta_m_cycle_kg', '_mass_balance_residual_kg')
            for target_suffix in mass_derived_suffixes:
                if key.endswith(target_suffix):
                    prefix = key[:-len(target_suffix)]
                    for source_suffix in ('_m_kg', '_mdot_in_kg_per_s', '_mdot_out_kg_per_s'):
                        expanded.add(prefix + source_suffix)
        return sorted(expanded)

    def _validate_export_layout_keys(self, layout_keys: list[str], rows: list[dict[str, float | int]]) -> None:
        if not layout_keys or not rows:
            return
        available = set(rows[0].keys())
        missing = [key for key in layout_keys if key not in available]
        if not missing:
            return
        preview = ', '.join(missing[:12])
        suffix = '' if len(missing) <= 12 else f', ... +{len(missing) - 12}'
        reason = f'{len(missing)} unknown signal(s): {preview}{suffix}'
        policy = str(getattr(self.bundle.postprocessing, 'csv_export_unknown_signals', 'warn_empty') or 'warn_empty').strip().lower()
        if policy == 'fail':
            raise KeyError(reason)
        ConsoleArtifactReporter.print_status('csv:layout', 'warn', reason=reason)

    def _prepare_export_rows(self, export_rows: list[dict[str, float | int]], layout: ExportLayoutSpec | None = None) -> tuple[list[dict[str, float | int | None]], list[dict[str, float | int | None]], list[list[object]], list[str]]:
        if layout is None:
            layout = self._load_export_layout_spec()
        if layout is None or not layout.keys:
            return export_rows, convert_rows_to_engineering_units(export_rows), [], []
        filtered_rows = self._filter_rows_by_keys(export_rows, layout.keys)
        converted_rows = convert_rows_to_layout_units(filtered_rows, layout)
        header_rows = self._layout_header_rows(layout)
        return converted_rows, converted_rows, header_rows, list(layout.keys)

    def _keep_last_cycles(self, t, y, cycle_indices):
        keep_last = int(getattr(self.bundle.simulation, 'save_last_cycles', 0) or 0)
        if keep_last <= 0:
            return t, y, cycle_indices
        if len(cycle_indices) == 0:
            return t, y, cycle_indices
        max_cycle = int(np.max(cycle_indices))
        keep_from_cycle = max(0, max_cycle - keep_last + 1)
        mask = cycle_indices >= keep_from_cycle
        return t[mask], y[:, mask], cycle_indices[mask]

    def _apply_sampling(self, t: np.ndarray, y: np.ndarray, cycle_indices: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        del cycle_indices
        return OutputSampler.resample(
            t,
            y,
            self.bundle.cycle_period_s,
            self.bundle.cycle_deg,
            self.bundle.postprocessing.sampling_mode,
            self.bundle.postprocessing.sampling_step,
            self.bundle.simulation.total_cycles,
        )

    def _build_reconstructed_rows(self, series: ReconstructedSeries | None) -> list[dict[str, float | int]]:
        """Zentralisierte Methode für Row-Erstellung und Cycle-Integral-Berechnung"""
        if series is None:
            return []
        rows = ResultRowBuilder.from_reconstructed(series)
        return self._add_cycle_integrals(rows)

    def _build_uniform_last_cycle_series(self, t: np.ndarray, y: np.ndarray) -> ReconstructedSeries | None:
        if t.size == 0:
            return None
        step_deg = float(self.bundle.postprocessing.final_cycle_uniform_angle_export_step_deg)
        if step_deg <= 0.0:
            return None
        cycle_period_s = float(self.bundle.cycle_period_s)
        cycle_deg = float(self.bundle.cycle_deg)
        t_end = float(np.asarray(t, dtype=np.float64)[-1])
        last_cycle_index = max(0, int(np.floor(t_end / cycle_period_s - 1.0e-12)))
        cycle_start_s = float(last_cycle_index) * cycle_period_s
        available_theta_end = max(0.0, min(cycle_deg, (t_end - cycle_start_s) * cycle_deg / cycle_period_s))
        if available_theta_end <= 1.0e-12:
            return None
        theta_targets = OutputSampler._grid_targets(0.0, available_theta_end, step_deg, include_endpoint=True)
        if theta_targets.size == 0:
            return None
        omega_deg_per_s = cycle_deg / cycle_period_s
        sample_t = cycle_start_s + theta_targets / omega_deg_per_s
        sample_t = sample_t[sample_t <= t_end + 1.0e-12]
        if sample_t.size == 0:
            return None
        sample_y = OutputSampler.interpolate_states(np.asarray(t, dtype=np.float64), np.asarray(y, dtype=np.float64), sample_t)
        sample_cycles = np.full(sample_t.shape, last_cycle_index, dtype=np.int64)
        series = SignalReconstructionService.build(self.bundle, sample_t, sample_y, sample_cycles)
        if series.n_samples > 0:
            theta_written = np.asarray(theta_targets[:series.n_samples], dtype=np.float64)
            series.theta_local_deg[:] = theta_written
            series.theta_deg[:] = theta_written
            if 'theta_local_deg' in series.columns:
                series.columns['theta_local_deg'][:] = theta_written
            if 'theta_deg' in series.columns:
                series.columns['theta_deg'][:] = theta_written
        return series

    def _build_free_piston_last_ut_ot_ut_series(self, t: np.ndarray, y: np.ndarray, cycle_indices: np.ndarray) -> ReconstructedSeries | None:
        if getattr(self.bundle, 'architecture', 'classic') != 'free_piston':
            return None
        fp = getattr(self.bundle, 'free_piston', None)
        if fp is None or t.size < 5:
            return None
        step_deg = float(getattr(self.bundle.postprocessing, 'free_piston_last_ut_ot_ut_export_step_deg', 0.0) or 0.0)
        axis_min_deg = float(getattr(self.bundle.postprocessing, 'free_piston_last_ut_ot_ut_export_axis_min_deg', 0.0) or 0.0)
        axis_max_deg = float(getattr(self.bundle.postprocessing, 'free_piston_last_ut_ot_ut_export_axis_max_deg', 0.0) or 0.0)
        if step_deg <= 0.0:
            return None
        if axis_max_deg <= axis_min_deg:
            return None

        t_arr = np.asarray(t, dtype=np.float64)
        y_arr = np.asarray(y, dtype=np.float64)
        cycle_idx_arr = np.asarray(cycle_indices, dtype=np.int64)
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

        tp_ut0, tp_ot, tp_ut1 = triplet
        i0 = int(tp_ut0.sample_index)
        i1 = int(tp_ot.sample_index)
        i2 = int(tp_ut1.sample_index)
        if i2 - i0 < 2 or i1 <= i0 or i2 <= i1:
            return None

        x0 = float(x_arr[i0])
        x1 = float(x_arr[i1])
        x2 = float(x_arr[i2])
        dx01 = x0 - x1
        dx12 = x2 - x1
        if abs(dx01) <= 1.0e-15 or abs(dx12) <= 1.0e-15:
            return None

        theta_first = 180.0 * (x0 - x_arr[i0:i1 + 1]) / dx01
        theta_second = 180.0 + 180.0 * (x_arr[i1:i2 + 1] - x1) / dx12
        theta_first = np.clip(theta_first, 0.0, 180.0)
        theta_second = np.clip(theta_second, 180.0, 360.0)
        theta_first = np.maximum.accumulate(theta_first)
        theta_second = np.maximum.accumulate(theta_second)
        theta_seg = np.concatenate([theta_first[:-1], theta_second])
        t_seg = t_arr[i0:i2 + 1]
        theta_seg[0] = 0.0
        theta_seg[i1 - i0] = 180.0
        theta_seg[-1] = 360.0
        theta_seg = np.maximum.accumulate(theta_seg)

        theta_unique, unique_idx = np.unique(theta_seg, return_index=True)
        if theta_unique.size < 2:
            return None
        t_unique = t_seg[unique_idx]
        theta_targets = OutputSampler._grid_targets(0.0, 360.0, step_deg, include_endpoint=True)
        if theta_targets.size == 0:
            return None
        sample_t = np.interp(theta_targets, theta_unique, t_unique)
        if sample_t.size == 0:
            return None
        sample_y = OutputSampler.interpolate_states(t_arr, y_arr, sample_t)
        ref_cycle_index = int(cycle_idx_arr[min(i2, cycle_idx_arr.size - 1)]) if cycle_idx_arr.size else 0
        sample_cycles = np.full(sample_t.shape, ref_cycle_index, dtype=np.int64)
        series = SignalReconstructionService.build(self.bundle, sample_t, sample_y, sample_cycles)
        if series.n_samples > 0:
            theta_base = np.asarray(theta_targets[:series.n_samples], dtype=np.float64)
            theta_written = axis_min_deg + (axis_max_deg - axis_min_deg) * (theta_base / 360.0)
            series.theta_local_deg[:] = theta_written
            series.theta_deg[:] = theta_written
            if 'theta_local_deg' in series.columns:
                series.columns['theta_local_deg'][:] = theta_written
            if 'theta_deg' in series.columns:
                series.columns['theta_deg'][:] = theta_written
        return series

    @staticmethod
    def _collect_integral_fields(rows: list[dict[str, float | int]]) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[str]]:
        if not rows:
            return [], [], []
        sample = rows[0]
        power_suffixes = {
            '_wall_heat_W': '_wall_heat_cycle_J',
            '_wall_cylinder_heat_W': '_wall_cylinder_heat_cycle_J',
            '_wall_head_heat_W': '_wall_head_heat_cycle_J',
            '_wall_piston_heat_W': '_wall_piston_heat_cycle_J',
            '_wall_heat_zones_sum_W': '_wall_heat_zones_sum_cycle_J',
            '_added_energy_W': '_added_energy_cycle_J',
            '_enthalpy_in_W': '_enthalpy_in_cycle_J',
            '_enthalpy_out_W': '_enthalpy_out_cycle_J',
            '_piston_work_W': '_piston_work_cycle_J',
            '_evaporation_sink_W': '_evaporation_sink_cycle_J',
        }
        flow_suffixes = {
            '_mdot_in_kg_per_s': '_mdot_in_cycle_kg',
            '_mdot_out_kg_per_s': '_mdot_out_cycle_kg',
        }
        power_fields: list[tuple[str, str]] = []
        flow_fields: list[tuple[str, str]] = []
        energy_prefixes: list[str] = []
        for field in sample.keys():
            for suffix, target_suffix in power_suffixes.items():
                if field.endswith(suffix):
                    power_fields.append((field, field[:-len(suffix)] + target_suffix))
                    break
            for suffix, target_suffix in flow_suffixes.items():
                if field.endswith(suffix):
                    flow_fields.append((field, field[:-len(suffix)] + target_suffix))
                    break
            if field.endswith('_U_J'):
                energy_prefixes.append(field[:-len('_U_J')])
        return power_fields, flow_fields, energy_prefixes

    @classmethod
    def _add_cycle_integrals(cls, rows: list[dict[str, float | int]]) -> list[dict[str, float | int]]:
        if not rows:
            return rows
        power_fields, flow_fields, energy_prefixes = cls._collect_integral_fields(rows)
        accumulators: dict[tuple[int, str], float] = {}
        cycle_starts: dict[tuple[int, str], float] = {}
        prev_row = None
        prev_cycle_index = -1

        for row in rows:
            cycle_index = int(row.get('cycle_index', 0))
            same_cycle = prev_row is not None and prev_cycle_index == cycle_index
            dt = 0.0 if not same_cycle else max(0.0, float(row['t_s']) - float(prev_row['t_s']))

            for source, target in power_fields:
                acc_key = (cycle_index, target)
                accumulators.setdefault(acc_key, 0.0)
                if same_cycle and prev_row is not None:
                    prev_val = float(prev_row.get(source, 0.0))
                    cur_val = float(row.get(source, 0.0))
                    accumulators[acc_key] += 0.5 * (prev_val + cur_val) * dt
                row[target] = float(accumulators[acc_key])

            for source, target in flow_fields:
                acc_key = (cycle_index, target)
                accumulators.setdefault(acc_key, 0.0)
                if same_cycle and prev_row is not None:
                    prev_val = float(prev_row.get(source, 0.0))
                    cur_val = float(row.get(source, 0.0))
                    accumulators[acc_key] += 0.5 * (prev_val + cur_val) * dt
                row[target] = float(accumulators[acc_key])

            for prefix in energy_prefixes:
                u_key = prefix + '_U_J'
                start_key = (cycle_index, u_key)
                u_value = float(row.get(u_key, 0.0))
                cycle_starts.setdefault(start_key, u_value)
                delta_u = u_value - cycle_starts[start_key]
                row[prefix + '_delta_U_cycle_J'] = delta_u

                h_in = float(row.get(prefix + '_enthalpy_in_cycle_J', 0.0))
                h_out = float(row.get(prefix + '_enthalpy_out_cycle_J', 0.0))
                h_net = h_in - h_out
                row[prefix + '_enthalpy_net_cycle_J'] = h_net

                q_wall = float(row.get(prefix + '_wall_heat_cycle_J', 0.0))
                q_add = float(row.get(prefix + '_added_energy_cycle_J', 0.0))
                q_evap = float(row.get(prefix + '_evaporation_sink_cycle_J', 0.0))
                w_pv = float(row.get(prefix + '_piston_work_cycle_J', 0.0))
                row[prefix + '_energy_balance_residual_J'] = float(delta_u - (h_net + q_wall + q_add - q_evap - w_pv))
                t0 = float(cycle_starts.setdefault((cycle_index, prefix + '_cycle_start_t_s'), float(row['t_s'])))
                elapsed_s = max(0.0, float(row['t_s']) - t0)
                row[prefix + '_indicated_power_W'] = float(w_pv / elapsed_s) if elapsed_s > 1.0e-15 else 0.0

                m_key = prefix + '_m_kg'
                if m_key in row:
                    m0 = float(cycle_starts.setdefault((cycle_index, m_key), float(row[m_key])))
                    delta_m = float(row[m_key]) - m0
                    m_in = float(row.get(prefix + '_mdot_in_cycle_kg', 0.0))
                    m_out = float(row.get(prefix + '_mdot_out_cycle_kg', 0.0))
                    row[prefix + '_delta_m_cycle_kg'] = delta_m
                    row[prefix + '_mass_balance_residual_kg'] = float(delta_m - (m_in - m_out))

            prev_row = row
            prev_cycle_index = cycle_index
        return rows

    def _effective_excel_enabled(self, excel_override: bool | None) -> bool:
        if excel_override is None:
            return bool(getattr(self.bundle.postprocessing, 'excel_enabled', False))
        return bool(excel_override)

    def _write_csv_export(self, path: Path, rows: list[dict[str, float | int]], header_rows: list[list[object]] | None = None, timing_key: str = 'csv', timings: dict[str, float] | None = None) -> str | None:
        """Zentralisierte CSV-Export-Methode"""
        if not rows:
            return None
        started = perf_counter()
        CsvExporter.write(path, self.bundle.postprocessing.csv_separator, rows, header_rows=header_rows or None)
        elapsed = perf_counter() - started
        if timings is not None:
            timings[timing_key] = elapsed
        return str(path)

    def _needs_export_rows(self, excel_override: bool | None) -> bool:
        return (
            bool(getattr(self.bundle.postprocessing, 'csv_enabled', True))
            or self._effective_excel_enabled(excel_override)
            or (
                bool(getattr(self.bundle.postprocessing, 'plots_enabled', True))
                and str(getattr(self.bundle.postprocessing, 'plots_source', 'last_cycle_uniform') or 'last_cycle_uniform').lower() == 'export_rows'
            )
            or (
                bool(getattr(self.bundle.postprocessing, 'check_report_enabled', True))
                and not self._needs_uniform_rows()
            )
        )

    def _needs_uniform_rows(self) -> bool:
        return (
            bool(getattr(self.bundle.postprocessing, 'final_cycle_uniform_angle_export_enabled', False))
            or bool(getattr(self.bundle.postprocessing, 'check_report_enabled', True))
            or (
                bool(getattr(self.bundle.postprocessing, 'plots_enabled', True))
                and str(getattr(self.bundle.postprocessing, 'plots_source', 'last_cycle_uniform') or 'last_cycle_uniform').lower() == 'last_cycle_uniform'
            )
        )

    def run(self, t: np.ndarray, y: np.ndarray, cycle_indices: np.ndarray, *, excel: bool | None = None) -> PostprocessingArtifacts:
        timings: dict[str, float] = {}
        total_started = perf_counter()
        ConsoleProgressReporter.print('Postprocessing: starte Ausgabeaufbereitung')

        base_csv_path = self._base_csv_path()
        base_excel_path = self._excel_path()
        csv_enabled = bool(getattr(self.bundle.postprocessing, 'csv_enabled', True))
        excel_enabled = self._effective_excel_enabled(excel)
        final_uniform_export_enabled = bool(getattr(self.bundle.postprocessing, 'final_cycle_uniform_angle_export_enabled', False))
        free_piston_ut_ot_ut_export_enabled = bool(getattr(self.bundle.postprocessing, 'free_piston_last_ut_ot_ut_export_enabled', False))
        check_report_enabled = bool(getattr(self.bundle.postprocessing, 'check_report_enabled', True))
        check_report_html_enabled = bool(getattr(self.bundle.postprocessing, 'check_report_html_enabled', False))

        export_layout_path = self._discover_export_layout_path()
        export_layout_spec = self._load_export_layout_spec(export_layout_path) if export_layout_path is not None else None
        export_layout_keys = list(export_layout_spec.keys) if export_layout_spec is not None else []
        if export_layout_path is not None and export_layout_keys:
            ConsoleProgressReporter.print(f'Postprocessing: verwende Export-Layout {export_layout_path.name} mit {len(export_layout_keys)} Spalten und 4 Kopfzeilen')
        else:
            ConsoleProgressReporter.print('Postprocessing: kein Export-Layout gefunden, exportiere alle Spalten')

        started = perf_counter()
        kept_t, kept_y, kept_cycles = self._keep_last_cycles(t, y, cycle_indices)
        timings['postprocessing:keep-last-cycles'] = perf_counter() - started
        ConsoleTimingReporter.print('postprocessing:keep-last-cycles', timings['postprocessing:keep-last-cycles'])

        started = perf_counter()
        sampled_t, sampled_y, sampled_cycles = self._apply_sampling(kept_t, kept_y, kept_cycles)
        timings['postprocessing:sampling'] = perf_counter() - started
        ConsoleTimingReporter.print('postprocessing:sampling', timings['postprocessing:sampling'])

        export_series: ReconstructedSeries | None = None
        export_rows: list[dict[str, float | int]] = []
        if self._needs_export_rows(excel):
            started = perf_counter()
            requested_export_keys = self._expand_requested_export_keys(export_layout_keys) if export_layout_keys else None
            export_series = SignalReconstructionService.build(
                self.bundle,
                sampled_t,
                sampled_y,
                sampled_cycles,
                requested_keys=requested_export_keys,
            )
            raw_export_rows = ResultRowBuilder.from_reconstructed(export_series)
            export_rows = self._add_cycle_integrals(raw_export_rows)
            self._validate_export_layout_keys(export_layout_keys, export_rows)
            timings['postprocessing:build-rows'] = perf_counter() - started
            ConsoleTimingReporter.print('postprocessing:build-rows', timings['postprocessing:build-rows'], rows=len(export_rows))
        else:
            timings['postprocessing:build-rows'] = 0.0
            ConsoleTimingReporter.print('postprocessing:build-rows', timings['postprocessing:build-rows'], rows=0)

        filtered_excel_rows: list[dict[str, float | int]] = export_rows
        filtered_csv_rows: list[dict[str, float | int]] = []
        export_header_rows: list[list[object]] = []
        if export_rows:
            filtered_excel_rows, filtered_csv_rows, export_header_rows, _ = self._prepare_export_rows(export_rows, export_layout_spec)

        csv_path: str | None = None
        if csv_enabled:
            csv_path = self._write_csv_export(base_csv_path, filtered_csv_rows, header_rows=export_header_rows or None, timing_key='csv', timings=timings)
            if csv_path:
                ConsoleArtifactReporter.print_path_status('csv', csv_path, elapsed_s=timings['csv'])
            else:
                ConsoleArtifactReporter.print_status('csv', 'warn', elapsed_s=timings.get('csv', 0.0), reason='no-rows')
        else:
            timings['csv'] = 0.0
            ConsoleArtifactReporter.print_skipped('csv', elapsed_s=timings['csv'])

        excel_path: str | None = None
        if excel_enabled:
            if filtered_excel_rows:
                started = perf_counter()
                ExcelExporter.write(base_excel_path, filtered_excel_rows, header_rows=export_header_rows or None)
                timings['xlsx'] = perf_counter() - started
                excel_path = str(base_excel_path)
                ConsoleArtifactReporter.print_path_status('xlsx', excel_path, elapsed_s=timings['xlsx'])
            else:
                timings['xlsx'] = 0.0
                ConsoleArtifactReporter.print_status('xlsx', 'warn', elapsed_s=timings['xlsx'], reason='no-rows')
        else:
            timings['xlsx'] = 0.0
            ConsoleArtifactReporter.print_skipped('xlsx', elapsed_s=timings['xlsx'])

        uniform_last_cycle_series: ReconstructedSeries | None = None
        uniform_last_cycle_rows: list[dict[str, float | int]] = []
        if self._needs_uniform_rows():
            started = perf_counter()
            uniform_last_cycle_series = self._build_uniform_last_cycle_series(t, y)
            uniform_last_cycle_rows = self._build_reconstructed_rows(uniform_last_cycle_series)
            timings['postprocessing:build-last-cycle-uniform'] = perf_counter() - started
        else:
            timings['postprocessing:build-last-cycle-uniform'] = 0.0
        ConsoleTimingReporter.print('postprocessing:build-last-cycle-uniform', timings['postprocessing:build-last-cycle-uniform'], rows=len(uniform_last_cycle_rows))

        last_cycle_uniform_csv_path: str | None = None
        if final_uniform_export_enabled:
            if uniform_last_cycle_rows:
                last_cycle_uniform_path = base_csv_path.with_name(base_csv_path.stem + '_last_cycle_uniform.csv')
                _, uniform_csv_rows, _, _ = self._prepare_export_rows(uniform_last_cycle_rows)
                last_cycle_uniform_csv_path = self._write_csv_export(last_cycle_uniform_path, uniform_csv_rows, timing_key='csv:last-cycle-uniform', timings=timings)
                if last_cycle_uniform_csv_path:
                    ConsoleArtifactReporter.print_path_status('csv:last-cycle-uniform', last_cycle_uniform_csv_path, elapsed_s=timings['csv:last-cycle-uniform'])
            else:
                timings['csv:last-cycle-uniform'] = 0.0
                ConsoleArtifactReporter.print_status('csv:last-cycle-uniform', 'warn', elapsed_s=timings['csv:last-cycle-uniform'], reason='no-rows')
        else:
            timings['csv:last-cycle-uniform'] = 0.0
            ConsoleArtifactReporter.print_skipped('csv:last-cycle-uniform', elapsed_s=timings['csv:last-cycle-uniform'])

        fp_last_ut_ot_ut_series: ReconstructedSeries | None = None
        free_piston_last_ut_ot_ut_rows: list[dict[str, float | int]] = []
        free_piston_last_ut_ot_ut_csv_path: str | None = None
        if free_piston_ut_ot_ut_export_enabled:
            started = perf_counter()
            fp_last_ut_ot_ut_series = self._build_free_piston_last_ut_ot_ut_series(t, y, cycle_indices)
            free_piston_last_ut_ot_ut_rows = self._build_reconstructed_rows(fp_last_ut_ot_ut_series)
            timings['postprocessing:build-free-piston-last-ut-ot-ut'] = perf_counter() - started
            ConsoleTimingReporter.print('postprocessing:build-free-piston-last-ut-ot-ut', timings['postprocessing:build-free-piston-last-ut-ot-ut'], rows=len(free_piston_last_ut_ot_ut_rows))
            if free_piston_last_ut_ot_ut_rows:
                fp_last_ut_ot_ut_path = base_csv_path.with_name(base_csv_path.stem + '_last_ut_ot_ut.csv')
                _, fp_csv_rows, fp_header_rows, _ = self._prepare_export_rows(free_piston_last_ut_ot_ut_rows)
                free_piston_last_ut_ot_ut_csv_path = self._write_csv_export(fp_last_ut_ot_ut_path, fp_csv_rows, header_rows=fp_header_rows or None, timing_key='csv:last-ut-ot-ut', timings=timings)
                if free_piston_last_ut_ot_ut_csv_path:
                    ConsoleArtifactReporter.print_path_status('csv:last-ut-ot-ut', free_piston_last_ut_ot_ut_csv_path, elapsed_s=timings['csv:last-ut-ot-ut'])
            else:
                timings['csv:last-ut-ot-ut'] = 0.0
                ConsoleArtifactReporter.print_status('csv:last-ut-ot-ut', 'warn', elapsed_s=timings['csv:last-ut-ot-ut'], reason='no-rows')
        else:
            timings['postprocessing:build-free-piston-last-ut-ot-ut'] = 0.0
            timings['csv:last-ut-ot-ut'] = 0.0
            ConsoleTimingReporter.print('postprocessing:build-free-piston-last-ut-ot-ut', timings['postprocessing:build-free-piston-last-ut-ot-ut'], rows=0)
            ConsoleArtifactReporter.print_skipped('csv:last-ut-ot-ut', elapsed_s=timings['csv:last-ut-ot-ut'])

        check_report_csv_path: str | None = None
        check_report_html_path: str | None = None
        check_report_metrics = None
        report_rows = (export_rows or uniform_last_cycle_rows) if getattr(self.bundle, 'architecture', 'classic') == 'free_piston' else (uniform_last_cycle_rows or export_rows)
        if check_report_enabled and report_rows:
            started = perf_counter()
            check_report_metrics = LastCycleCheckReportBuilder.build_metrics(
                report_rows,
                cycle_deg=float(self.bundle.cycle_deg),
                bundle=self.bundle,
            )
            timings['check-report:metrics'] = perf_counter() - started
            ConsoleTimingReporter.print('check-report:metrics', timings['check-report:metrics'])
            if check_report_metrics:
                started = perf_counter()
                check_csv_path = base_csv_path.with_name(base_csv_path.stem + '_check_report.csv')
                check_report_csv_path = LastCycleCheckReportBuilder.write_csv(
                    check_csv_path,
                    self.bundle.postprocessing.csv_separator,
                    check_report_metrics,
                )
                timings['csv:check-report'] = perf_counter() - started
                ConsoleArtifactReporter.print_path_status('csv:check-report', check_report_csv_path, elapsed_s=timings['csv:check-report'])
                if check_report_html_enabled:
                    started = perf_counter()
                    check_html_path = base_csv_path.with_name(base_csv_path.stem + '_check_report.html')
                    check_report_html_path = LastCycleCheckReportBuilder.write_html(
                        check_html_path,
                        check_report_metrics,
                        title=f'Last Cycle Check Report - {self.config_path.stem}',
                    )
                    timings['html:check-report'] = perf_counter() - started
                    ConsoleArtifactReporter.print_path_status('html:check-report', check_report_html_path, elapsed_s=timings['html:check-report'])
                else:
                    timings['html:check-report'] = 0.0
                    ConsoleArtifactReporter.print_skipped('html:check-report', elapsed_s=timings['html:check-report'])
            else:
                timings['csv:check-report'] = 0.0
                timings['html:check-report'] = 0.0
                ConsoleArtifactReporter.print_status('csv:check-report', 'warn', elapsed_s=timings['csv:check-report'], reason='no-metrics')
                if check_report_html_enabled:
                    ConsoleArtifactReporter.print_status('html:check-report', 'warn', elapsed_s=timings['html:check-report'], reason='no-metrics')
                else:
                    ConsoleArtifactReporter.print_skipped('html:check-report', elapsed_s=timings['html:check-report'])
        else:
            timings['check-report:metrics'] = 0.0
            timings['csv:check-report'] = 0.0
            timings['html:check-report'] = 0.0
            ConsoleTimingReporter.print('check-report:metrics', timings['check-report:metrics'])
            if check_report_enabled:
                ConsoleArtifactReporter.print_status('csv:check-report', 'warn', elapsed_s=timings['csv:check-report'], reason='no-rows')
                if check_report_html_enabled:
                    ConsoleArtifactReporter.print_status('html:check-report', 'warn', elapsed_s=timings['html:check-report'], reason='no-rows')
                else:
                    ConsoleArtifactReporter.print_skipped('html:check-report', elapsed_s=timings['html:check-report'])
            else:
                ConsoleArtifactReporter.print_skipped('csv:check-report', elapsed_s=timings['csv:check-report'])
                ConsoleArtifactReporter.print_skipped('html:check-report', elapsed_s=timings['html:check-report'])

        timings['postprocessing'] = perf_counter() - total_started
        ConsoleTimingReporter.print('postprocessing', timings['postprocessing'])

        return PostprocessingArtifacts(
            csv_path=csv_path,
            excel_path=excel_path,
            export_rows=export_rows,
            last_cycle_uniform_csv_path=last_cycle_uniform_csv_path,
            last_cycle_uniform_rows=uniform_last_cycle_rows or None,
            free_piston_last_ut_ot_ut_csv_path=free_piston_last_ut_ot_ut_csv_path,
            free_piston_last_ut_ot_ut_rows=free_piston_last_ut_ot_ut_rows or None,
            check_report_csv_path=check_report_csv_path,
            check_report_html_path=check_report_html_path,
            check_report_metrics=check_report_metrics,
            export_series=export_series,
            last_cycle_uniform_series=uniform_last_cycle_series,
            free_piston_last_ut_ot_ut_series=fp_last_ut_ot_ut_series,
            timings=timings,
        )
