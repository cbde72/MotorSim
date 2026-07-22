from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from more_itertools import only
import yaml

from thermo0d.app.paths import PathManager
from thermo0d.output.pipeline import run_pipeline_from_raw_archive

from render_pipeline_csv_plots import render_pipeline_csv_plots


SIMULATED_ARG_PRESETS: dict[str, list[str]] = {
    "free_piston_v25": [
        "--simulation-config", str(ROOT / "Projekte" / "variants" / "free_piston_GenSet_V25.yaml"),
        "--config", str(ROOT / "Projekte" / "variants" / "postprocessing.yaml"),
    ],
    "free_piston_v25_reprocessed": [
        "--simulation-config", str(ROOT / "Projekte" / "variants" / "free_piston_GenSet_V25.yaml"),
        "--config", str(ROOT / "Projekte" / "variants" / "postprocessing.yaml"),
        "--outdir", str(ROOT / "Projekte" / "variants" / "results" / "free_piston_GenSet_V25_reprocessed"),
    ],
    "free_piston_plots": [
        "--simulation-config", str(ROOT / "Projekte" / "variants" / "free_piston_GenSet_V25.yaml"),
        "--config", str(ROOT / "Projekte" / "variants" / "postprocessing.yaml"),
        "--plots-cycle-only",
    ],
}

# Nur diesen Namen umstellen, wenn du ohne echte CLI-Argumente ein anderes Setup starten willst.
SELECTED_PRESET = "free_piston_plots"


def _resolve_simulated_args(preset_name: str) -> list[str]:
    simulated_args = SIMULATED_ARG_PRESETS.get(preset_name)
    if simulated_args is None:
        available = ", ".join(sorted(SIMULATED_ARG_PRESETS))
        raise SystemExit(
            f"[ERROR] Unbekanntes simulated_args-Preset: {preset_name!r}. Verfügbar: {available}"
        )
    return list(simulated_args)


def _infer_raw_archive_from_simulation_config(config_path: str | Path) -> Path:
    config = Path(config_path).expanduser().resolve()
    return (PathManager.resolve_output_dir(config) / "raw" / "run_raw.npz").resolve()


def parse_args(args_list: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the lightweight thermo0d postprocessing pipeline from an existing raw archive."
    )
    parser.add_argument("--raw", default=None, help="Path to raw/run_raw.npz written by postprocessing.mode=pipeline.")
    parser.add_argument("--simulation-config", default=None, help="Simulation config used to infer the default raw/run_raw.npz path.")
    parser.add_argument("--config", default=None, help="Path to the separate postprocessing.yaml pipeline config.")
    parser.add_argument("--outdir", default=None, help="Optional output directory for regenerated CSV and summary files.")
    parser.add_argument("--plots", dest="plots", action="store_true", default=None, help="Render plot_CFG layouts from the generated pipeline CSV.")
    parser.add_argument("--no-plots", dest="plots", action="store_false", help="Only run the pipeline export, do not render plots.")
    parser.add_argument(
        "--plots-cycle-only",
        "--cycle-plots-only",
        dest="plots_cycle_only",
        action="store_true",
        help="Only render the last_ut_ot_ut/cycle plot layouts, e.g. plot_cycle -> plots_cycle.",
    )
    parser.add_argument("--plot-cfg", default=None, help="Plot YAML file or directory with *.yaml layouts.")
    parser.add_argument("--plots-outdir", default=None, help="Optional output directory for rendered plot PNG files.")
    parser.add_argument("--plot-prefix", default=None, help="Optional filename prefix for rendered plot PNG files.")
    return parser.parse_args(args_list)


def _load_pipeline_config_data(config_path: str | Path | None) -> dict[str, Any]:
    if not config_path:
        return {}
    path = Path(config_path).expanduser().resolve()
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _plot_config_block(config_data: dict[str, Any]) -> dict[str, Any]:
    plots = config_data.get("plots")
    return plots if isinstance(plots, dict) else {}


def _cycle_plot_config_block(plot_cfg: dict[str, Any]) -> dict[str, Any]:
    cycle_cfg = plot_cfg.get("last_ut_ot_ut") if isinstance(plot_cfg.get("last_ut_ot_ut"), dict) else {}
    if cycle_cfg:
        return cycle_cfg
    return {
        "enabled": True,
        "layout_path": "plot_cycle",
        "output_dir": "plots_cycle",
        "prefix": None,
        "clean": True,
    }


def _resolve_config_relative(value: str | Path, config_path: str | Path | None) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    base = Path(config_path).expanduser().resolve().parent if config_path else ROOT
    return (base / path).resolve()


def _resolve_result_relative(value: str | Path, result_dir: Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (result_dir / path).resolve()


def _default_plot_output_dir(csv_path: Path) -> Path:
    result_dir = csv_path.parent.parent if csv_path.parent.name.lower() == "csv" else csv_path.parent
    return result_dir / "plots_pipeline_csv"


def _default_plot_prefix(csv_path: Path) -> str:
    result_dir = csv_path.parent.parent if csv_path.parent.name.lower() == "csv" else csv_path.parent
    return f"{result_dir.name}_pipeline"


def _render_configured_plots(
    *,
    csv_path: Path,
    result_dir: Path,
    plot_cfg: dict[str, Any],
    args: argparse.Namespace,
    run_config_path: Path | None,
    config_path: str | Path | None,
    default_output_name: str,
    default_prefix_suffix: str,
) -> tuple[Path, list[str]]:
    plot_cfg_raw = args.plot_cfg or plot_cfg.get("layout_path") or plot_cfg.get("path") or (ROOT / "Projekte" / "variants" / "plot_CFG")
    plot_cfg_path = _resolve_config_relative(plot_cfg_raw, config_path)
    outdir_raw = args.plots_outdir or plot_cfg.get("output_dir") or default_output_name
    plots_outdir = _resolve_result_relative(outdir_raw, result_dir)
    default_prefix = f"{result_dir.name}_{default_prefix_suffix}".strip("_")
    plot_prefix = str(args.plot_prefix or plot_cfg.get("prefix") or default_prefix)
    rendered = render_pipeline_csv_plots(
        csv_path,
        plot_cfg_path,
        plots_outdir,
        plot_prefix,
        run_config_path=run_config_path,
        clean=bool(plot_cfg.get("clean", True)),
    )
    return plots_outdir, rendered


def main(args_list: list[str] | None = None) -> int:
    args = parse_args(args_list)
    raw_path = Path(args.raw).expanduser().resolve() if args.raw else None
    output_dir = Path(args.outdir).expanduser().resolve() if args.outdir else None
    if raw_path is None and args.simulation_config:
        raw_path = _infer_raw_archive_from_simulation_config(args.simulation_config)
        if output_dir is None:
            output_dir = PathManager.resolve_output_dir(args.simulation_config).resolve()
    if raw_path is None:
        raise SystemExit("[ERROR] Bitte --raw oder --simulation-config angeben.")
    if output_dir is None and raw_path.parent.name.lower() == "raw":
        output_dir = raw_path.parent.parent.resolve()
    artifacts = run_pipeline_from_raw_archive(raw_path, args.config, output_dir=output_dir)
    if artifacts.csv_path:
        print(f"[pipeline-offline] csv={artifacts.csv_path}")
    if artifacts.results_csv_path:
        print(f"[pipeline-offline] results_csv={artifacts.results_csv_path}")
    if artifacts.last_ut_ot_ut_csv_path:
        print(f"[pipeline-offline] last_ut_ot_ut_csv={artifacts.last_ut_ot_ut_csv_path}")
    if artifacts.summary_path:
        print(f"[pipeline-offline] summary={artifacts.summary_path}")
    if artifacts.summary_text_path:
        print(f"[pipeline-offline] summary_text={artifacts.summary_text_path}")
    print(f"[pipeline-offline] signals={len(artifacts.signal_specs)}")
    config_data = _load_pipeline_config_data(args.config)
    plot_cfg = _plot_config_block(config_data)
    plots_enabled = (
        True
        if args.plots_cycle_only
        else (bool(plot_cfg.get("enabled", True)) if args.plots is None else bool(args.plots))
    )
    primary_csv = artifacts.last_ut_ot_ut_csv_path if args.plots_cycle_only else artifacts.csv_path
    if plots_enabled and primary_csv:
        csv_path = Path(primary_csv).expanduser().resolve()
        result_dir = csv_path.parent.parent if csv_path.parent.name.lower() == "csv" else csv_path.parent
        run_config_path = Path(args.simulation_config).expanduser().resolve() if args.simulation_config else None
        if not args.plots_cycle_only:
            if not artifacts.csv_path:
                raise SystemExit("[ERROR] Keine pipeline CSV zum Plotten gefunden.")
            csv_path = Path(artifacts.csv_path).expanduser().resolve()
            plots_outdir, rendered = _render_configured_plots(
                csv_path=csv_path,
                result_dir=result_dir,
                plot_cfg=plot_cfg,
                args=args,
                run_config_path=run_config_path,
                config_path=args.config,
                default_output_name=str(_default_plot_output_dir(csv_path).name),
                default_prefix_suffix="pipeline",
            )
            print(f"[pipeline-offline] plots_outdir={plots_outdir}")
            print(f"[pipeline-offline] plots={len(rendered)}")
        last_plot_cfg = _cycle_plot_config_block(plot_cfg)
        if (args.plots_cycle_only or bool(last_plot_cfg.get("enabled", False))) and artifacts.last_ut_ot_ut_csv_path:
            last_csv_path = Path(artifacts.last_ut_ot_ut_csv_path).expanduser().resolve()
            last_outdir, last_rendered = _render_configured_plots(
                csv_path=last_csv_path,
                result_dir=result_dir,
                plot_cfg=last_plot_cfg,
                args=args,
                run_config_path=run_config_path,
                config_path=args.config,
                default_output_name="plots_pipeline_csv_last_ut_ot_ut",
                default_prefix_suffix="last_ut_ot_ut",
            )
            print(f"[pipeline-offline] last_ut_ot_ut_plots_outdir={last_outdir}")
            print(f"[pipeline-offline] last_ut_ot_ut_plots={len(last_rendered)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(main(sys.argv[1:]))

    simulated_args = _resolve_simulated_args(SELECTED_PRESET)
    print(f"[INFO] Keine Terminal-Argumente erkannt. Nutze Preset: {SELECTED_PRESET}")
    print(f"[INFO] simulated_args = {simulated_args}")
    raise SystemExit(main(simulated_args))
