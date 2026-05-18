from __future__ import annotations

"""Run Jacobian/solver benchmarks and write an HTML report to test_cases/benchmarks.

The benchmark compares selected solver strategies on a curated subset of YAML
configs. In particular it highlights the difference between pure finite-
difference stiff solves, sparsity-assisted finite differences and the current
hybrid Jacobian that adds analytic flow/energy contributions.
"""

from dataclasses import dataclass
from html import escape
from pathlib import Path
from time import perf_counter
import json
import csv

import numpy as np

from thermo0d.app.paths import PathManager
from thermo0d.compute.analysis import CycleIndexCalculator, CycleSummaryCalculator
from thermo0d.compute.executor import TimeGridBuilder
from thermo0d.compute.solvers import SolverFactory
from thermo0d.input.config_loader import ConfigLoader
from thermo0d.input.model_builder import build_model_bundle
from thermo0d.physics.rhs import RHSWrapper


@dataclass(slots=True)
class BenchmarkCase:
    config_name: str
    test_description: str
    mode: str
    elapsed_s: float | None
    ok: bool
    error: str | None
    final_air_mass_mg: float | None
    final_pmax_bar: float | None


def _report_dir() -> Path:
    root = PathManager.settings().project_root
    out = root / "test_cases" / "benchmarks"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _load_bundle(config_path: Path):
    cfg = ConfigLoader.load(config_path)
    return cfg, build_model_bundle(cfg, config_path)


def _solve_mode(bundle, mode: str):
    dt = bundle.simulation.dt_s
    t_end = bundle.simulation.total_cycles * bundle.cycle_period_s
    t_eval = TimeGridBuilder.build(dt, t_end)
    rhs = RHSWrapper(bundle)
    kwargs = {}
    if mode == "rk4":
        solver = SolverFactory.create("rk4")
    elif mode == "scipy_rk45":
        solver = SolverFactory.create("scipy_rk45")
    elif mode == "scipy_bdf_fd":
        solver = SolverFactory.create("scipy_bdf")
    elif mode == "scipy_bdf_sparse_fd":
        solver = SolverFactory.create("scipy_bdf")
        kwargs["jac_sparsity"] = bundle.jac_sparsity
    elif mode == "scipy_bdf_hybrid":
        solver = SolverFactory.create("scipy_bdf")
        kwargs["jac_sparsity"] = bundle.jac_sparsity
        kwargs["jac"] = rhs.jacobian
    elif mode == "scipy_radau_hybrid":
        solver = SolverFactory.create("scipy_radau")
        kwargs["jac_sparsity"] = bundle.jac_sparsity
        kwargs["jac"] = rhs.jacobian
    else:
        raise KeyError(mode)

    started = perf_counter()
    result = solver(rhs, bundle.y_init.copy(), t_eval, bundle.simulation.rtol, bundle.simulation.atol, **kwargs)
    elapsed = perf_counter() - started
    return elapsed, result.t, result.y


def _run_one(config_path: Path, mode: str) -> BenchmarkCase:
    cfg, bundle = _load_bundle(config_path)
    try:
        elapsed, t, y = _solve_mode(bundle, mode)
        cycle_idx = CycleIndexCalculator.compute(t, bundle.cycle_period_s)
        summaries = CycleSummaryCalculator.compute(bundle, t, y, cycle_idx)
        last = summaries[-1] if summaries else None
        return BenchmarkCase(
            config_name=config_path.name,
            test_description=cfg.test_description or "",
            mode=mode,
            elapsed_s=elapsed,
            ok=True,
            error=None,
            final_air_mass_mg=None if last is None else last.air_mass_mg,
            final_pmax_bar=None if last is None else last.pmax_bar,
        )
    except Exception as exc:  # pragma: no cover - benchmark robustness path
        return BenchmarkCase(
            config_name=config_path.name,
            test_description=cfg.test_description or "",
            mode=mode,
            elapsed_s=None,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
            final_air_mass_mg=None,
            final_pmax_bar=None,
        )


def _write_csv(rows: list[BenchmarkCase], out_dir: Path) -> Path:
    path = out_dir / "benchmark_results.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(["config", "test_description", "mode", "ok", "elapsed_s", "final_air_mass_mg", "final_pmax_bar", "error"])
        for r in rows:
            writer.writerow([
                r.config_name,
                r.test_description,
                r.mode,
                int(r.ok),
                "" if r.elapsed_s is None else f"{r.elapsed_s:.6f}",
                "" if r.final_air_mass_mg is None else f"{r.final_air_mass_mg:.6f}",
                "" if r.final_pmax_bar is None else f"{r.final_pmax_bar:.6f}",
                "" if r.error is None else r.error,
            ])
    return path


def _write_json(rows: list[BenchmarkCase], out_dir: Path) -> Path:
    path = out_dir / "benchmark_results.json"
    from dataclasses import asdict
    payload = [asdict(r) for r in rows]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _svg_bar_chart(rows: list[BenchmarkCase], width: int = 900, height: int = 340) -> str:
    oks = [r for r in rows if r.ok and r.elapsed_s is not None]
    if not oks:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="160"><text x="24" y="48" font-size="20">Keine erfolgreichen Benchmarkdaten vorhanden.</text></svg>'
    max_v = max(r.elapsed_s for r in oks)
    left, top, plot_h, bar_h = 220, 24, height - 60, 18
    gap = 8
    total_h = len(oks) * (bar_h + gap)
    svg_h = max(height, total_h + 48)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{svg_h}" viewBox="0 0 {width} {svg_h}">']
    parts.append('<rect x="0" y="0" width="100%" height="100%" fill="#0f172a"/>')
    parts.append('<text x="24" y="24" fill="#e2e8f0" font-size="20" font-family="Arial">Benchmark-Laufzeiten [s]</text>')
    y = 40
    colors = {
        "rk4": "#475569",
        "scipy_rk45": "#38bdf8",
        "scipy_bdf_fd": "#f59e0b",
        "scipy_bdf_sparse_fd": "#a78bfa",
        "scipy_bdf_hybrid": "#22c55e",
        "scipy_radau_hybrid": "#ef4444",
    }
    for r in oks:
        label = f"{r.config_name} | {r.mode}"
        bar_w = 0 if max_v <= 0 else (r.elapsed_s / max_v) * (width - left - 80)
        parts.append(f'<text x="24" y="{y+13}" fill="#cbd5e1" font-size="12" font-family="Arial">{escape(label)}</text>')
        parts.append(f'<rect x="{left}" y="{y}" width="{bar_w:.1f}" height="{bar_h}" fill="{colors.get(r.mode, "#94a3b8")}" rx="4" ry="4"/>')
        parts.append(f'<text x="{left + bar_w + 8:.1f}" y="{y+13}" fill="#e2e8f0" font-size="12" font-family="Arial">{r.elapsed_s:.4f}</text>')
        y += bar_h + gap
    parts.append('</svg>')
    return ''.join(parts)


def _write_html(rows: list[BenchmarkCase], out_dir: Path) -> Path:
    path = out_dir / "index.html"
    svg = _svg_bar_chart(rows)
    by_cfg: dict[str, list[BenchmarkCase]] = {}
    for row in rows:
        by_cfg.setdefault(row.config_name, []).append(row)
    sections = []
    for cfg_name, cfg_rows in sorted(by_cfg.items()):
        desc = escape(cfg_rows[0].test_description)
        body = []
        for r in sorted(cfg_rows, key=lambda x: x.mode):
            status = 'ok' if r.ok else 'fail'
            elapsed = '' if r.elapsed_s is None else f'{r.elapsed_s:.6f}'
            am = '' if r.final_air_mass_mg is None else f'{r.final_air_mass_mg:.3f}'
            pm = '' if r.final_pmax_bar is None else f'{r.final_pmax_bar:.3f}'
            err = '' if r.error is None else escape(r.error)
            body.append(f'<tr><td>{escape(r.mode)}</td><td class="{status}">{status}</td><td>{elapsed}</td><td>{am}</td><td>{pm}</td><td>{err}</td></tr>')
        sections.append(f'''<section><h2>{escape(cfg_name)}</h2><p>{desc}</p><table><thead><tr><th>Mode</th><th>Status</th><th>Zeit [s]</th><th>air_mass_mg</th><th>pmax_bar</th><th>Fehler</th></tr></thead><tbody>{''.join(body)}</tbody></table></section>''')
    html = f'''<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Thermo0D Benchmarks</title>
<style>
body{{font-family:Inter,Arial,sans-serif;background:#020617;color:#e2e8f0;margin:0;padding:24px}}
h1,h2{{margin:0 0 12px}}main{{display:grid;gap:20px}}section{{background:#111827;border:1px solid #334155;border-radius:14px;padding:18px}}table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #334155;padding:8px;vertical-align:top}}th{{background:#1e293b}}.ok{{color:#4ade80}}.fail{{color:#f87171}}code{{background:#0b1220;padding:2px 6px;border-radius:6px}}
</style></head><body>
<h1>Thermo0D Solver-/Jacobian-Benchmarks</h1>
<p>Verglichene Modi: <code>rk4</code>, <code>scipy_rk45</code>, <code>scipy_bdf_fd</code>, <code>scipy_bdf_sparse_fd</code>, <code>scipy_bdf_hybrid</code>, <code>scipy_radau_hybrid</code>.</p>
<main><section><h2>Übersicht</h2>{svg}</section>
<section><h2>Interpretation</h2><ul><li><strong>scipy_bdf_fd</strong>: steifer Solver ohne Jacobian-Hilfen.</li><li><strong>scipy_bdf_sparse_fd</strong>: gleiche Methode mit topologischer Sparsity.</li><li><strong>scipy_bdf_hybrid</strong>: Sparsity + hybrider Jacobian mit analytischen Flow-/Energie-Beiträgen.</li><li><strong>scipy_radau_hybrid</strong>: gleiche Jacobian-Strategie mit Radau.</li></ul></section>
{''.join(sections)}</main></body></html>'''
    path.write_text(html, encoding='utf-8')
    return path


def main() -> int:
    root = PathManager.settings().project_root
    config_dir = root / 'test_cases' / 'configs'
    out_dir = _report_dir()
    selected = [
        config_dir / 'config_01_4t_base.yaml',
        config_dir / 'config_22_4t_conv_scipy.yaml',
    ]
    modes = ['rk4', 'scipy_rk45', 'scipy_bdf_sparse_fd', 'scipy_bdf_hybrid']
    rows: list[BenchmarkCase] = []
    for cfg in selected:
        if not cfg.exists():
            continue
        for mode in modes:
            print(f'[bench] {cfg.name} | {mode}')
            rows.append(_run_one(cfg, mode))
    _write_csv(rows, out_dir)
    _write_json(rows, out_dir)
    html_path = _write_html(rows, out_dir)
    print(f'[bench] HTML report: {html_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
