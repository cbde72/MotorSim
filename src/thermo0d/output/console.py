from __future__ import annotations

import math
from pathlib import Path

from thermo0d.compute.analysis import CycleSummary
from thermo0d.output.check_report import CheckMetric
from thermo0d.output.geometry_report import build_geometry_entries


class ConsoleRunReporter:
    @staticmethod
    def print_run_summary(*, wall_clock_s: float, solver_kind: str) -> None:
        print(f'[run] wall_clock_s={wall_clock_s:.6f} solver={solver_kind}')


class ConsoleCycleReporter:
    @staticmethod
    def print_one(summary: CycleSummary) -> None:
        print(
            f'[cycle {summary.cycle_index:03d}] '
            f'air_mass_mg={summary.air_mass_mg:.3f} '
            f'runtime_s={summary.runtime_s:.6f} '
            f'piston_work_J={summary.piston_work_J:.6f} '
            f'pmax_bar={summary.pmax_bar:.6f}'
        )

    @classmethod
    def print(cls, cycle_summaries: list[CycleSummary]) -> None:
        for summary in cycle_summaries:
            cls.print_one(summary)


class ConsoleProgressReporter:
    @staticmethod
    def print(message: str) -> None:
        text = str(message).strip()
        if not text:
            return
        print(f'[status] {text}')


class ConsoleTimingReporter:
    @staticmethod
    def print(label: str, elapsed_s: float, **extra: object) -> None:
        parts = [f'[{label}] elapsed_s={float(elapsed_s):.6f}']
        for key, value in extra.items():
            if value is None:
                continue
            parts.append(f'{key}={value}')
        print(' '.join(parts))


class ConsoleCheckReportReporter:
    @staticmethod
    def print(metrics: list[CheckMetric] | None) -> None:
        if not metrics:
            return
        print('[check-report] last-cycle summary')
        for metric in metrics:
            value = metric.value
            if isinstance(value, float):
                value_text = f'{value:.12g}'
            else:
                value_text = str(value)
            unit = f' {metric.unit}' if metric.unit and metric.unit != '-' else ''
            print(f'[check {metric.status}] {metric.name}={value_text}{unit}')


class ConsoleGeometryReporter:
    @staticmethod
    def _format_value(value: float) -> str:
        if math.isfinite(float(value)):
            return f'{float(value):.12g}'
        return str(value)

    @classmethod
    def build_lines(cls, bundle) -> list[str]:
        grouped: dict[tuple[str, str], list[tuple[str, float]]] = {}
        for entry in build_geometry_entries(bundle):
            grouped.setdefault((entry.category, entry.entity_name), []).append((entry.metric_name, entry.value, entry.unit))
        lines: list[str] = []
        for (category, entity_name), pairs in grouped.items():
            payload = ' '.join(f'{metric_name}={cls._format_value(value)} {unit}'.rstrip() for metric_name, value, unit in pairs)
            lines.append(f'[geometry:{category}] {entity_name} {payload}')
        return lines

    @classmethod
    def print(cls, bundle) -> None:
        for line in cls.build_lines(bundle):
            print(line)


class ConsoleArtifactReporter:
    @staticmethod
    def _status_for_path(path: str | Path | None) -> str:
        if path is None:
            return 'warn'
        return 'ok' if Path(path).exists() else 'failed'

    @classmethod
    def _status_for_many(cls, paths: list[str | Path] | tuple[str | Path, ...] | None) -> str:
        seq = list(paths or [])
        if not seq:
            return 'warn'
        states = [cls._status_for_path(path) for path in seq]
        if 'failed' in states:
            return 'failed'
        if 'ok' in states:
            return 'ok'
        return 'warn'

    @staticmethod
    def _label(status: str) -> str:
        return {
            'ok': 'OK',
            'warn': 'WARN',
            'failed': 'FAILED',
            'skip': 'SKIP',
        }.get(str(status).lower(), str(status).upper())

    @classmethod
    def print_status(cls, label: str, status: str, *, elapsed_s: float | None = None, reason: str | None = None) -> None:
        text = f'[{label}] {cls._label(status)}'
        if elapsed_s is not None:
            text += f' elapsed_s={float(elapsed_s):.6f}'
        if reason:
            text += f' reason={reason}'
        print(text)

    @classmethod
    def print_path_status(cls, label: str, path: str | Path | None, *, elapsed_s: float | None = None, reason: str | None = None) -> None:
        cls.print_status(label, cls._status_for_path(path), elapsed_s=elapsed_s, reason=reason)

    @classmethod
    def print_many_status(cls, label: str, paths: list[str | Path] | tuple[str | Path, ...] | None, *, elapsed_s: float | None = None, reason: str | None = None) -> None:
        cls.print_status(label, cls._status_for_many(paths), elapsed_s=elapsed_s, reason=reason)

    @classmethod
    def print_skipped(cls, label: str, *, elapsed_s: float | None = None, reason: str | None = 'disabled') -> None:
        cls.print_status(label, 'skip', elapsed_s=elapsed_s, reason=reason)
