from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from shutil import copy2
from time import perf_counter
from typing import Any

import numpy as np

from thermo0d.compute.analysis import CycleIndexCalculator, CycleSummary, CycleSummaryCalculator
from thermo0d.compute.executor import SimulationExecutor
from thermo0d.core.model_bundle import ModelBundle, PlotLayoutEntryOptions
from thermo0d.app.paths import PathManager
from thermo0d.input.config_loader import ConfigLoader
from thermo0d.input.model_builder import build_model_bundle
from thermo0d.output.console import (
    ConsoleArtifactReporter,
    ConsoleCheckReportReporter,
    ConsoleGeometryReporter,
    ConsoleProgressReporter,
    ConsoleRunReporter,
    ConsoleTimingReporter,
)
from thermo0d.output.geometry_report import write_geometry_readme
from thermo0d.output.plot_layout import ensure_default_plot10_yaml, ensure_default_plot_yaml, render_plot_project
from thermo0d.output.plots import (
    write_free_piston_last_ut_ot_ut_diagnostic_plots,
    write_free_piston_last_ut_ot_ut_pv_plot,
    write_free_piston_last_ut_ot_ut_species_plot,
)
from thermo0d.output.service import PostprocessingService
from thermo0d.config.restart_state_update import update_config_initials_from_last_compression_at_x0


@dataclass(slots=True)
class RunArtifacts:
    bundle: ModelBundle
    t: np.ndarray
    y: np.ndarray
    cycle_indices: np.ndarray
    cycle_summaries: list[CycleSummary]
    wall_clock_s: float
    csv_path: str | None
    excel_path: str | None
    rhs_derivatives_csv_path: str | None
    export_rows: list[dict[str, float | int]]
    last_cycle_uniform_csv_path: str | None
    check_report_csv_path: str | None
    check_report_html_path: str | None
    readme_path: str | None
    plot_layout_path: str | None
    plot10_layout_path: str | None
    generated_plot_paths: list[str]
    plot_layout_paths: list[str] = field(default_factory=list)


class SimulationAppRunner:
    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path).resolve()
        self.cfg = ConfigLoader.load(self.config_path)
        self.bundle = build_model_bundle(self.cfg, self.config_path)

    def _resolve_optional_path(self, path_text: str | None) -> Path | None:
        if path_text is None:
            return None
        raw = str(path_text).strip()
        if not raw:
            return None
        path = Path(raw)
        if not path.is_absolute():
            path = (self.config_path.parent / path).resolve()
        return path

    def _configured_outdir(self) -> str | None:
        raw = getattr(self.bundle.postprocessing, 'outdir', None)
        if raw is None:
            return None
        text = str(raw).strip()
        return text or None

    def _plot_output_dir(self) -> Path | None:
        return PathManager.resolve_plot_output_dir(self.config_path, self._configured_outdir())

    def _result_dir(self) -> Path:
        return PathManager.resolve_output_dir(self.config_path, self._configured_outdir())

    @staticmethod
    def _flatten_relative_target(raw_path: str) -> Path:
        raw = str(raw_path or '').strip()
        if not raw:
            return Path('inputs')
        normalized = Path(raw.replace('\\', '/'))
        safe_parts = [part for part in normalized.parts if part not in ('', '.', '..', '/')]
        if not safe_parts:
            return Path('inputs') / normalized.name
        return Path(*safe_parts)

    def _iter_input_file_references(self, node: Any, key_path: tuple[str, ...] = ()):
        if isinstance(node, dict):
            for key, value in node.items():
                yield from self._iter_input_file_references(value, key_path + (str(key),))
            return
        if isinstance(node, list):
            for value in node:
                yield from self._iter_input_file_references(value, key_path)
            return
        if not isinstance(node, str):
            return

        raw = node.strip()
        if not raw or raw.startswith('${'):
            return
        if key_path[:2] == ('postprocessing', 'csv_path'):
            return
        if key_path[:2] == ('postprocessing', 'excel_path'):
            return
        if key_path[:3] == ('postprocessing', 'plots', 'output_dir'):
            return

        candidate = Path(raw)
        if candidate.is_absolute():
            if candidate.is_file():
                yield candidate.resolve(), Path('inputs') / candidate.name
            return

        resolved = (self.config_path.parent / candidate).resolve()
        if resolved.is_file():
            yield resolved, self._flatten_relative_target(raw)

    def _copy_input_snapshot(self, result_dir: Path, plot_layout_paths: list[str]) -> None:
        result_dir.mkdir(parents=True, exist_ok=True)
        config_target = (result_dir / self.config_path.name).resolve()
        if config_target != self.config_path.resolve():
            copy2(self.config_path, config_target)

        seen: dict[Path, Path] = {}
        config_data = self.cfg.model_dump(mode='python')
        for src, rel_target in self._iter_input_file_references(config_data):
            seen.setdefault(src, rel_target)
        for layout_path in plot_layout_paths:
            src = Path(layout_path).resolve()
            if src.is_file():
                try:
                    rel_target = self._flatten_relative_target(src.relative_to(self.config_path.parent).as_posix())
                except ValueError:
                    rel_target = Path('plot_layouts') / src.name
                seen.setdefault(src, rel_target)

        if not any(rel.parts and rel.parts[0] == 'data' for rel in seen.values()):
            fallback_data_dir = (self.config_path.parent / 'data').resolve()
            if fallback_data_dir.is_dir():
                for file_path in sorted(fallback_data_dir.rglob('*')):
                    if file_path.is_file():
                        seen.setdefault(file_path.resolve(), Path('data') / file_path.relative_to(fallback_data_dir))

        for src, rel_target in sorted(seen.items(), key=lambda item: item[1].as_posix()):
            target = (result_dir / rel_target).resolve()
            if target == src.resolve():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            copy2(src, target)

    def _select_plot_rows(self, post) -> list[dict[str, float | int]]:
        source = str(getattr(self.bundle.postprocessing, 'plots_source', 'last_cycle_uniform') or 'last_cycle_uniform').lower()
        if source == 'export_rows':
            return list(post.export_rows or [])
        return list(post.last_cycle_uniform_rows or post.export_rows or [])

    def _default_layout_entries(self) -> list[PlotLayoutEntryOptions]:
        return [
            PlotLayoutEntryOptions(enabled=True, path='plot.yaml', prefix=''),
            PlotLayoutEntryOptions(enabled=True, path='plot10.yaml', prefix='plot10'),
        ]

    def _prepare_layout_paths(self) -> list[tuple[PlotLayoutEntryOptions, Path]]:
        entries = list(getattr(self.bundle.postprocessing, 'plot_layout_entries', []) or [])
        auto_defaults = bool(getattr(self.bundle.postprocessing, 'plot_layout_auto_create_defaults', True))
        if not entries and auto_defaults:
            entries = self._default_layout_entries()
        resolved: list[tuple[PlotLayoutEntryOptions, Path]] = []
        for entry in entries:
            if not bool(getattr(entry, 'enabled', True)):
                continue
            path_text = str(getattr(entry, 'path', '') or '').strip()
            if not path_text:
                continue
            out_path = PathManager.resolve_layout_path(
                self.config_path,
                path_text,
                configured_outdir=self._configured_outdir(),
                prefer_output_dir_when_missing=auto_defaults,
            )
            if auto_defaults and not out_path.exists():
                name = out_path.name.lower()
                if name == 'plot.yaml':
                    ensure_default_plot_yaml(self.bundle, self.config_path, output_path=out_path)
                elif name == 'plot10.yaml':
                    ensure_default_plot10_yaml(self.bundle, self.config_path, output_path=out_path)
            resolved.append((entry, out_path))
        return resolved

    def run(self, excel: bool | None = None) -> RunArtifacts:
        ConsoleProgressReporter.print(f'Simulation: starte Solver für {self.config_path.name}')
        execution = SimulationExecutor(self.bundle).run()

        if getattr(self.bundle, 'architecture', 'classic') == 'free_piston':
            ConsoleProgressReporter.print('Analyse: berechne cycle_index')
            started = perf_counter()
            cycle_indices = CycleIndexCalculator.compute(execution.t, self.bundle.cycle_period_s, self.bundle.simulation.total_cycles)
            ConsoleTimingReporter.print('analysis:cycle-index', perf_counter() - started)

            cycle_summaries = []
            if bool(getattr(self.bundle.postprocessing, 'console_run_summary_enabled', True)):
                ConsoleRunReporter.print_run_summary(wall_clock_s=execution.wall_clock_s, solver_kind=execution.solver_kind)

            post = PostprocessingService(self.bundle, self.config_path).run(execution.t, execution.y, cycle_indices, excel=excel)

            plot_layout_paths: list[str] = []
            generated_plot_paths: list[str] = []
            if bool(getattr(self.bundle.postprocessing, 'plots_enabled', True)):
                plot_rows = self._select_plot_rows(post)
                if plot_rows:
                    output_dir = self._plot_output_dir()
                    for entry, layout_path in self._prepare_layout_paths():
                        if not layout_path.exists():
                            ConsoleArtifactReporter.print_status(layout_path.name, 'warn', elapsed_s=0.0, reason='layout-missing')
                            continue
                        ConsoleProgressReporter.print(f'Plot: rendere {layout_path.name}')
                        prefix_parts = [self.config_path.stem]
                        entry_prefix = str(getattr(entry, 'prefix', '') or '').strip()
                        if entry_prefix:
                            prefix_parts.append(entry_prefix)
                        prefix = '__'.join(prefix_parts)
                        started = perf_counter()
                        rendered_paths = render_plot_project(plot_rows, layout_path, output_dir=output_dir, prefix=prefix, run_config_path=self.config_path)
                        elapsed = perf_counter() - started
                        generated_plot_paths.extend(rendered_paths)
                        plot_layout_paths.append(str(layout_path))
                        ConsoleArtifactReporter.print_many_status(layout_path.name, rendered_paths, elapsed_s=elapsed)
                else:
                    for entry, layout_path in self._prepare_layout_paths():
                        ConsoleArtifactReporter.print_skipped(layout_path.name, elapsed_s=0.0, reason='no-rows')

            if bool(getattr(self.bundle.postprocessing, 'plots_enabled', True)):
                pv_plot_rows = list(post.export_rows or [])
                if pv_plot_rows:
                    output_dir = self._plot_output_dir()
                    pv_plot_path = output_dir / f"{self.config_path.stem}__last_ut_ot_ut_pv.png"
                    started = perf_counter()
                    written_pv_paths = write_free_piston_last_ut_ot_ut_pv_plot(self.bundle, pv_plot_rows, pv_plot_path, run_config_path=self.config_path)
                    elapsed = perf_counter() - started
                    if written_pv_paths:
                        generated_plot_paths.extend(written_pv_paths)
                        ConsoleArtifactReporter.print_many_status('plot:last-ut-ot-ut-pv', written_pv_paths, elapsed_s=elapsed)
                    else:
                        ConsoleArtifactReporter.print_status('plot:last-ut-ot-ut-pv', 'warn', elapsed_s=elapsed, reason='no-complete-ut-ot-ut')
                    species_plot_path = output_dir / f"{self.config_path.stem}__last_ut_ot_ut_species.png"
                    started = perf_counter()
                    written_species_path = write_free_piston_last_ut_ot_ut_species_plot(self.bundle, pv_plot_rows, species_plot_path, run_config_path=self.config_path)
                    elapsed = perf_counter() - started
                    if written_species_path is not None:
                        generated_plot_paths.append(written_species_path)
                        ConsoleArtifactReporter.print_path_status('plot:last-ut-ot-ut-species', written_species_path, elapsed_s=elapsed)
                    else:
                        ConsoleArtifactReporter.print_status('plot:last-ut-ot-ut-species', 'warn', elapsed_s=elapsed, reason='no-complete-ut-ot-ut')
                    started = perf_counter()
                    written_diagnostic_paths = write_free_piston_last_ut_ot_ut_diagnostic_plots(self.bundle, pv_plot_rows, output_dir, self.config_path.stem, run_config_path=self.config_path)
                    elapsed = perf_counter() - started
                    if written_diagnostic_paths:
                        generated_plot_paths.extend(written_diagnostic_paths)
                        ConsoleArtifactReporter.print_many_status('plot:last-ut-ot-ut-diagnostics', written_diagnostic_paths, elapsed_s=elapsed)
                    else:
                        ConsoleArtifactReporter.print_status('plot:last-ut-ot-ut-diagnostics', 'warn', elapsed_s=elapsed, reason='no-complete-ut-ot-ut')
                else:
                    ConsoleArtifactReporter.print_skipped('plot:last-ut-ot-ut-pv', elapsed_s=0.0, reason='no-rows')
                    ConsoleArtifactReporter.print_skipped('plot:last-ut-ot-ut-species', elapsed_s=0.0, reason='no-rows')
                    ConsoleArtifactReporter.print_skipped('plot:last-ut-ot-ut-diagnostics', elapsed_s=0.0, reason='no-rows')
        else:
            ConsoleProgressReporter.print('Analyse: berechne cycle_index')
            started = perf_counter()
            cycle_indices = CycleIndexCalculator.compute(execution.t, self.bundle.cycle_period_s, self.bundle.simulation.total_cycles)
            ConsoleTimingReporter.print('analysis:cycle-index', perf_counter() - started)

            ConsoleProgressReporter.print('Analyse: berechne Cycle Summary')
            started = perf_counter()
            cycle_summaries = CycleSummaryCalculator.compute(self.bundle, execution.t, execution.y, cycle_indices)
            cycle_summary_elapsed = perf_counter() - started
            ConsoleTimingReporter.print('analysis:cycle-summary', cycle_summary_elapsed, cycles=len(cycle_summaries))

            if bool(getattr(self.bundle.postprocessing, 'console_run_summary_enabled', True)):
                ConsoleRunReporter.print_run_summary(wall_clock_s=execution.wall_clock_s, solver_kind=execution.solver_kind)

            post = PostprocessingService(self.bundle, self.config_path).run(execution.t, execution.y, cycle_indices, excel=excel)

            plot_layout_paths: list[str] = []
            generated_plot_paths: list[str] = []
            if bool(getattr(self.bundle.postprocessing, 'plots_enabled', True)):
                plot_rows = self._select_plot_rows(post)
                if plot_rows:
                    output_dir = self._plot_output_dir()
                    for entry, layout_path in self._prepare_layout_paths():
                        if not layout_path.exists():
                            ConsoleArtifactReporter.print_status(layout_path.name, 'warn', elapsed_s=0.0, reason='layout-missing')
                            continue
                        ConsoleProgressReporter.print(f'Plot: rendere {layout_path.name}')
                        prefix_parts = [self.config_path.stem]
                        entry_prefix = str(getattr(entry, 'prefix', '') or '').strip()
                        if entry_prefix:
                            prefix_parts.append(entry_prefix)
                        prefix = '__'.join(prefix_parts)
                        started = perf_counter()
                        rendered_paths = render_plot_project(plot_rows, layout_path, output_dir=output_dir, prefix=prefix, run_config_path=self.config_path)
                        elapsed = perf_counter() - started
                        generated_plot_paths.extend(rendered_paths)
                        plot_layout_paths.append(str(layout_path))
                        ConsoleArtifactReporter.print_many_status(layout_path.name, rendered_paths, elapsed_s=elapsed)
                else:
                    for entry, layout_path in self._prepare_layout_paths():
                        ConsoleArtifactReporter.print_skipped(layout_path.name, elapsed_s=0.0, reason='no-rows')

            if bool(getattr(self.bundle.postprocessing, 'plots_enabled', True)):
                pv_plot_rows = list(post.export_rows or [])
                if pv_plot_rows:
                    output_dir = self._plot_output_dir()
                    pv_plot_path = output_dir / f"{self.config_path.stem}__last_ut_ot_ut_pv.png"
                    started = perf_counter()
                    written_pv_paths = write_free_piston_last_ut_ot_ut_pv_plot(self.bundle, pv_plot_rows, pv_plot_path, run_config_path=self.config_path)
                    elapsed = perf_counter() - started
                    if written_pv_paths:
                        generated_plot_paths.extend(written_pv_paths)
                        ConsoleArtifactReporter.print_many_status('plot:last-ut-ot-ut-pv', written_pv_paths, elapsed_s=elapsed)
                    else:
                        ConsoleArtifactReporter.print_status('plot:last-ut-ot-ut-pv', 'warn', elapsed_s=elapsed, reason='no-complete-ut-ot-ut')
                    species_plot_path = output_dir / f"{self.config_path.stem}__last_ut_ot_ut_species.png"
                    started = perf_counter()
                    written_species_path = write_free_piston_last_ut_ot_ut_species_plot(self.bundle, pv_plot_rows, species_plot_path, run_config_path=self.config_path)
                    elapsed = perf_counter() - started
                    if written_species_path is not None:
                        generated_plot_paths.append(written_species_path)
                        ConsoleArtifactReporter.print_path_status('plot:last-ut-ot-ut-species', written_species_path, elapsed_s=elapsed)
                    else:
                        ConsoleArtifactReporter.print_status('plot:last-ut-ot-ut-species', 'warn', elapsed_s=elapsed, reason='no-complete-ut-ot-ut')
                    started = perf_counter()
                    written_diagnostic_paths = write_free_piston_last_ut_ot_ut_diagnostic_plots(self.bundle, pv_plot_rows, output_dir, self.config_path.stem, run_config_path=self.config_path)
                    elapsed = perf_counter() - started
                    if written_diagnostic_paths:
                        generated_plot_paths.extend(written_diagnostic_paths)
                        ConsoleArtifactReporter.print_many_status('plot:last-ut-ot-ut-diagnostics', written_diagnostic_paths, elapsed_s=elapsed)
                    else:
                        ConsoleArtifactReporter.print_status('plot:last-ut-ot-ut-diagnostics', 'warn', elapsed_s=elapsed, reason='no-complete-ut-ot-ut')
                else:
                    ConsoleArtifactReporter.print_skipped('plot:last-ut-ot-ut-pv', elapsed_s=0.0, reason='no-rows')
                    ConsoleArtifactReporter.print_skipped('plot:last-ut-ot-ut-species', elapsed_s=0.0, reason='no-rows')
                    ConsoleArtifactReporter.print_skipped('plot:last-ut-ot-ut-diagnostics', elapsed_s=0.0, reason='no-rows')

        update_enabled = bool(getattr(self.bundle.postprocessing, 'auto_update_initial_conditions', True))
        started = perf_counter()
        cfg_update = update_config_initials_from_last_compression_at_x0(
            self.config_path,
            bundle=self.bundle,
            t=execution.t,
            y=execution.y,
            cycle_indices=cycle_indices,
            enabled=update_enabled,
        )
        cfg_elapsed = perf_counter() - started
        if cfg_update.changed:
            sample = cfg_update.sample
            ConsoleArtifactReporter.print_status(
                'config:auto-initial-update',
                'ok',
                elapsed_s=cfg_elapsed,
                reason=(
                    f'entries={cfg_update.changed_entries} '
                    f'x0_m={sample.x_target_m:.12g} '
                    f't_s={sample.t_s:.12g}'
                ) if sample is not None else f'entries={cfg_update.changed_entries}',
            )
        else:
            if update_enabled:
                ConsoleArtifactReporter.print_status(
                    'config:auto-initial-update',
                    'warn',
                    elapsed_s=cfg_elapsed,
                    reason=str(cfg_update.reason or 'not-updated'),
                )
            else:
                ConsoleArtifactReporter.print_skipped('config:auto-initial-update', elapsed_s=cfg_elapsed, reason='disabled')

        result_dir = self._result_dir()
        self._copy_input_snapshot(result_dir, plot_layout_paths)

        if bool(getattr(self.bundle.postprocessing, 'console_check_report_enabled', True)):
            started = perf_counter()
            ConsoleCheckReportReporter.print(post.check_report_metrics)
            ConsoleTimingReporter.print('console:check-report', perf_counter() - started)
        if bool(getattr(self.bundle.postprocessing, 'console_geometry_enabled', True)):
            started = perf_counter()
            ConsoleGeometryReporter.print(self.bundle)
            ConsoleTimingReporter.print('console:geometry', perf_counter() - started)

        started = perf_counter()
        readme_rows = post.export_rows or post.last_cycle_uniform_rows
        readme_path = write_geometry_readme(self.bundle, result_dir, filename='README.md', rows=readme_rows)
        ConsoleArtifactReporter.print_path_status('readme:geometry', readme_path, elapsed_s=perf_counter() - started)

        plot_layout_path = plot_layout_paths[0] if plot_layout_paths else None
        plot10_layout_path = plot_layout_paths[1] if len(plot_layout_paths) > 1 else None

        return RunArtifacts(
            bundle=self.bundle,
            t=execution.t,
            y=execution.y,
            cycle_indices=cycle_indices,
            cycle_summaries=cycle_summaries,
            wall_clock_s=execution.wall_clock_s,
            csv_path=post.csv_path,
            excel_path=post.excel_path,
            rhs_derivatives_csv_path=post.rhs_derivatives_csv_path,
            export_rows=post.export_rows,
            last_cycle_uniform_csv_path=post.last_cycle_uniform_csv_path,
            check_report_csv_path=post.check_report_csv_path,
            check_report_html_path=post.check_report_html_path,
            readme_path=str(readme_path.resolve()) if readme_path is not None else None,
            plot_layout_path=plot_layout_path,
            plot10_layout_path=plot10_layout_path,
            generated_plot_paths=generated_plot_paths,
            plot_layout_paths=plot_layout_paths,
        )



def run_simulation(config_path: str | Path, excel: bool | None = None) -> RunArtifacts:
    return SimulationAppRunner(config_path).run(excel=excel)
