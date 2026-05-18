#!/usr/bin/env python3
"""Vergleichsskript alt vs. neu für RK4 im Thermo0D/MotorSim-Projekt.

Ziel
----
Dieses Skript führt zwei Projektstände isoliert gegeneinander aus und vergleicht
anschließend die numerischen Exportdaten. Es ist speziell dafür gedacht zu
prüfen, ob ein Refactor (z. B. Wall-Heat / Vibe / Evap / Flow-Partials) die
Ergebnisse unter dem expliziten Solver ``rk4`` verändert hat.

Wichtige Eigenschaften
----------------------
- Jeder Projektstand läuft in einem eigenen Subprozess mit eigenem ``sys.path``.
  Dadurch gibt es keine Modulkonflikte zwischen zwei Ständen, die beide das
  Paket ``thermo0d`` enthalten.
- Die übergebene Konfiguration wird für den Lauf automatisch auf ``solver.kind:
  rk4`` umgeschrieben, ohne die Originaldatei zu verändern.
- Verglichen wird bevorzugt die ``last_cycle_uniform_csv``. Falls diese nicht
  vorhanden ist, wird auf den normalen CSV-Export zurückgefallen.
- Für alle gemeinsamen numerischen Spalten werden Kennzahlen berechnet:
  Maximalabweichung, RMSE, Endwertdifferenz und relative Abweichung.

Typische Nutzung
----------------
1) Vergleich eines alten und eines neuen Projektordners mit jeweils eigener
   Konfigurationsdatei::

    python compare_rk4_old_vs_new.py \
        --old-root "C:/.../old_project" \
        --new-root "C:/.../new_project" \
        --old-config "C:/.../old_project/Projekte/A156A1-2V-REX-V09d.yaml" \
        --new-config "C:/.../new_project/Projekte/A156A1-2V-REX-V09d.yaml" \
        --report-dir "C:/.../rk4_compare"

2) Falls beide Stände dieselbe Python-Umgebung nutzen, sind keine weiteren
   Angaben nötig. Wenn alt/neu unterschiedliche Python-Interpreter brauchen,
   können ``--python-old`` und ``--python-new`` gesetzt werden.

Ausgabe
-------
Im Report-Ordner entstehen u. a.:
- ``comparison_report.txt``      : gut lesbarer Textreport
- ``comparison_summary.json``    : maschinenlesbare Zusammenfassung
- ``old_run.json`` / ``new_run.json`` : Rohdaten der beiden Läufe
- ``column_metrics.csv``         : Kennzahlen pro gemeinsamer numerischer Spalte

Hinweis zur Interpretation
--------------------------
Bei Refactors mit identischer Fachlogik sollten die Unterschiede für RK4 sehr
klein sein. Bitgenaue Gleichheit ist wegen Floating-Point-Reihenfolge, Numba-
Optimierungen und minimal anderen Zwischenvariablen trotzdem nicht garantiert.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class RunResult:
    label: str
    project_root: Path
    config_original: Path
    config_patched: Path
    result_json: Path
    csv_path: Path | None
    summary: dict[str, Any]


@dataclass(slots=True)
class ColumnMetric:
    name: str
    n: int
    max_abs: float
    rmse: float
    max_rel: float
    end_abs: float
    old_end: float
    new_end: float


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Vergleich zweier Projektstände mit solver.kind = rk4")
    p.add_argument("--old-root", required=True, help="Projektwurzel des alten Stands")
    p.add_argument("--new-root", required=True, help="Projektwurzel des neuen Stands")
    p.add_argument("--old-config", required=True, help="YAML-Konfiguration im alten Stand")
    p.add_argument("--new-config", required=True, help="YAML-Konfiguration im neuen Stand")
    p.add_argument("--python-old", default=sys.executable, help="Python-Interpreter für den alten Stand")
    p.add_argument("--python-new", default=sys.executable, help="Python-Interpreter für den neuen Stand")
    p.add_argument(
        "--report-dir",
        default=str(Path.cwd() / "rk4_compare_report"),
        help="Ausgabeordner für Report und Zwischendateien",
    )
    p.add_argument(
        "--prefer-last-cycle-uniform",
        action="store_true",
        default=True,
        help="Bevorzugt last_cycle_uniform_csv statt des Voll-CSV-Exports (Standard: an)",
    )
    p.add_argument(
        "--no-prefer-last-cycle-uniform",
        action="store_false",
        dest="prefer_last_cycle_uniform",
        help="Normalen CSV-Export bevorzugen",
    )
    p.add_argument(
        "--top-columns",
        type=int,
        default=25,
        help="Wie viele Spalten im Textreport detailliert ausgegeben werden sollen",
    )
    return p.parse_args()


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise TypeError(f"Konfiguration ist kein YAML-Mapping: {path}")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def patch_config_to_rk4(original_config: Path, label: str) -> Path:
    """Erzeuge eine temporäre Konfigurationskopie neben der Originaldatei.

    Die Kopie liegt absichtlich im selben Ordner wie die Originaldatei, damit
    relative Pfade in der YAML-Datei weiterhin genauso aufgelöst werden.
    """
    cfg = load_yaml(original_config)
    sim = cfg.setdefault("simulation", {})
    if not isinstance(sim, dict):
        raise TypeError(f"simulation ist kein Mapping in {original_config}")
    solver = sim.setdefault("solver", {})
    if not isinstance(solver, dict):
        raise TypeError(f"simulation.solver ist kein Mapping in {original_config}")
    solver["kind"] = "rk4"

    patched = original_config.with_name(f"{original_config.stem}__rk4_compare_{label}{original_config.suffix}")
    write_yaml(patched, cfg)
    return patched


RUNNER_SNIPPET = r'''
from __future__ import annotations
import json
import sys
from pathlib import Path

project_root = Path(sys.argv[1]).resolve()
config_path = Path(sys.argv[2]).resolve()
result_json = Path(sys.argv[3]).resolve()

src_dir = project_root / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from thermo0d.app.paths import PathManager
from thermo0d.app.runner import run_simulation

# Gleiche Basispfade wie in der normalen App-Konfiguration.
PathManager.override(
    default_project=str(project_root),
    default_test_space=str(project_root / "test_cases"),
    default_variants_dir=str(project_root / "Projekte" / "variants"),
)

artifacts = run_simulation(config_path, excel=False)
summary = None
if getattr(artifacts, "cycle_summaries", None):
    s = artifacts.cycle_summaries[-1]
    summary = {
        "cycle_index": int(getattr(s, "cycle_index", -1)),
        "air_mass_mg": float(getattr(s, "air_mass_mg", float("nan"))),
        "runtime_s": float(getattr(s, "runtime_s", float("nan"))),
        "piston_work_J": float(getattr(s, "piston_work_J", float("nan"))),
        "pmax_bar": float(getattr(s, "pmax_bar", float("nan"))),
    }

payload = {
    "csv_path": artifacts.csv_path,
    "last_cycle_uniform_csv_path": artifacts.last_cycle_uniform_csv_path,
    "check_report_csv_path": artifacts.check_report_csv_path,
    "check_report_html_path": artifacts.check_report_html_path,
    "plot_path": artifacts.last_cycle_pressure_plot_path,
    "summary": summary,
}
result_json.parent.mkdir(parents=True, exist_ok=True)
result_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
'''


def run_case(
    *,
    label: str,
    python_exe: str,
    project_root: Path,
    config_path: Path,
    report_dir: Path,
    prefer_last_cycle_uniform: bool,
) -> RunResult:
    patched_cfg = patch_config_to_rk4(config_path, label)
    result_json = report_dir / f"{label}_run.json"
    cmd = [python_exe, "-c", RUNNER_SNIPPET, str(project_root), str(patched_cfg), str(result_json)]
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")

    try:
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
    except subprocess.CalledProcessError as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        raise RuntimeError(
            f"Lauf '{label}' fehlgeschlagen.\n"
            f"Kommando: {' '.join(cmd)}\n"
            f"STDOUT:\n{stdout}\n\nSTDERR:\n{stderr}"
        ) from exc
    finally:
        # Temporäre Konfigurationskopie wieder entfernen.
        try:
            patched_cfg.unlink(missing_ok=True)
        except Exception:
            pass

    payload = json.loads(result_json.read_text(encoding="utf-8"))
    chosen_csv = payload.get("last_cycle_uniform_csv_path") if prefer_last_cycle_uniform else payload.get("csv_path")
    if not chosen_csv:
        chosen_csv = payload.get("csv_path") or payload.get("last_cycle_uniform_csv_path")

    return RunResult(
        label=label,
        project_root=project_root,
        config_original=config_path,
        config_patched=patched_cfg,
        result_json=result_json,
        csv_path=Path(chosen_csv).resolve() if chosen_csv else None,
        summary=payload,
    )



def _try_float(value: str) -> float | None:
    try:
        v = float(value)
    except Exception:
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v



def load_numeric_columns(csv_path: Path) -> dict[str, list[float]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        data: dict[str, list[float]] = {c: [] for c in cols}
        non_numeric: set[str] = set()
        for row in reader:
            for c in cols:
                if c in non_numeric:
                    continue
                raw = row.get(c, "")
                if raw is None or raw == "":
                    non_numeric.add(c)
                    data.pop(c, None)
                    continue
                v = _try_float(raw)
                if v is None:
                    non_numeric.add(c)
                    data.pop(c, None)
                    continue
                data[c].append(v)
    return data



def build_column_metrics(old_cols: dict[str, list[float]], new_cols: dict[str, list[float]]) -> tuple[list[ColumnMetric], list[str]]:
    common = sorted(set(old_cols) & set(new_cols))
    metrics: list[ColumnMetric] = []
    skipped: list[str] = []
    for name in common:
        a = old_cols[name]
        b = new_cols[name]
        if len(a) != len(b) or not a:
            skipped.append(name)
            continue
        diffs = [bb - aa for aa, bb in zip(a, b)]
        abs_diffs = [abs(d) for d in diffs]
        sq = [d * d for d in diffs]
        rels: list[float] = []
        for aa, bb in zip(a, b):
            denom = max(abs(aa), abs(bb), 1.0e-30)
            rels.append(abs(bb - aa) / denom)
        metrics.append(
            ColumnMetric(
                name=name,
                n=len(a),
                max_abs=max(abs_diffs),
                rmse=(sum(sq) / len(sq)) ** 0.5,
                max_rel=max(rels),
                end_abs=abs(diffs[-1]),
                old_end=a[-1],
                new_end=b[-1],
            )
        )
    metrics.sort(key=lambda m: (m.max_abs, m.rmse, m.max_rel), reverse=True)
    return metrics, skipped



def write_column_metrics_csv(path: Path, metrics: list[ColumnMetric]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["column", "n", "max_abs", "rmse", "max_rel", "end_abs", "old_end", "new_end"])
        for m in metrics:
            writer.writerow([m.name, m.n, m.max_abs, m.rmse, m.max_rel, m.end_abs, m.old_end, m.new_end])



def format_summary_block(label: str, payload: dict[str, Any]) -> str:
    s = payload.get("summary") or {}
    parts = [f"[{label}]", f"csv_path = {payload.get('csv_path')}", f"last_cycle_uniform_csv_path = {payload.get('last_cycle_uniform_csv_path')}"]
    if s:
        for key in ["cycle_index", "air_mass_mg", "runtime_s", "piston_work_J", "pmax_bar"]:
            if key in s:
                parts.append(f"{key} = {s[key]}")
    return "\n".join(parts)



def write_text_report(
    path: Path,
    *,
    old_run: RunResult,
    new_run: RunResult,
    metrics: list[ColumnMetric],
    skipped: list[str],
) -> None:
    top = metrics[:]
    top.sort(key=lambda m: m.max_abs, reverse=True)
    lines: list[str] = []
    lines.append("RK4 Vergleich: alt vs. neu")
    lines.append("=" * 80)
    lines.append("")
    lines.append(format_summary_block("old", old_run.summary))
    lines.append("")
    lines.append(format_summary_block("new", new_run.summary))
    lines.append("")
    lines.append(f"Verglichene numerische Spalten: {len(metrics)}")
    lines.append(f"Übersprungene gemeinsame Spalten (z. B. ungleiche Länge): {len(skipped)}")
    if skipped:
        lines.append("Skipped: " + ", ".join(skipped[:30]) + (" ..." if len(skipped) > 30 else ""))
    lines.append("")
    lines.append("Top-Spalten nach max_abs")
    lines.append("-" * 80)
    for m in top[: min(len(top), 25)]:
        lines.append(
            f"{m.name}: max_abs={m.max_abs:.6e}, rmse={m.rmse:.6e}, "
            f"max_rel={m.max_rel:.6e}, end_abs={m.end_abs:.6e}, "
            f"old_end={m.old_end:.6e}, new_end={m.new_end:.6e}, n={m.n}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")



def write_json_summary(path: Path, *, old_run: RunResult, new_run: RunResult, metrics: list[ColumnMetric], skipped: list[str]) -> None:
    payload = {
        "old": {
            "project_root": str(old_run.project_root),
            "config_original": str(old_run.config_original),
            "result": old_run.summary,
            "compare_csv": str(old_run.csv_path) if old_run.csv_path else None,
        },
        "new": {
            "project_root": str(new_run.project_root),
            "config_original": str(new_run.config_original),
            "result": new_run.summary,
            "compare_csv": str(new_run.csv_path) if new_run.csv_path else None,
        },
        "metrics": [m.__dict__ for m in metrics],
        "skipped_columns": skipped,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")



def main() -> int:
    args = parse_args()
    report_dir = Path(args.report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)

    old_root = Path(args.old_root).resolve()
    new_root = Path(args.new_root).resolve()
    old_cfg = Path(args.old_config).resolve()
    new_cfg = Path(args.new_config).resolve()

    old_run = run_case(
        label="old",
        python_exe=args.python_old,
        project_root=old_root,
        config_path=old_cfg,
        report_dir=report_dir,
        prefer_last_cycle_uniform=args.prefer_last_cycle_uniform,
    )
    new_run = run_case(
        label="new",
        python_exe=args.python_new,
        project_root=new_root,
        config_path=new_cfg,
        report_dir=report_dir,
        prefer_last_cycle_uniform=args.prefer_last_cycle_uniform,
    )

    if old_run.csv_path is None or not old_run.csv_path.exists():
        raise FileNotFoundError(f"Kein Vergleichs-CSV für old gefunden: {old_run.csv_path}")
    if new_run.csv_path is None or not new_run.csv_path.exists():
        raise FileNotFoundError(f"Kein Vergleichs-CSV für new gefunden: {new_run.csv_path}")

    old_cols = load_numeric_columns(old_run.csv_path)
    new_cols = load_numeric_columns(new_run.csv_path)
    metrics, skipped = build_column_metrics(old_cols, new_cols)

    write_column_metrics_csv(report_dir / "column_metrics.csv", metrics)
    write_text_report(report_dir / "comparison_report.txt", old_run=old_run, new_run=new_run, metrics=metrics, skipped=skipped)
    write_json_summary(report_dir / "comparison_summary.json", old_run=old_run, new_run=new_run, metrics=metrics, skipped=skipped)

    print(f"[OK] Report-Ordner: {report_dir}")
    print(f"[OK] Textreport    : {report_dir / 'comparison_report.txt'}")
    print(f"[OK] JSON-Report   : {report_dir / 'comparison_summary.json'}")
    print(f"[OK] Spalten-CSV   : {report_dir / 'column_metrics.csv'}")
    print(f"[OK] old CSV       : {old_run.csv_path}")
    print(f"[OK] new CSV       : {new_run.csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
