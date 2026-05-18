from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from thermo0d.app.paths import DEFAULT_PROJECT, DEFAULT_TEST_SPACE, DEFAULT_VARIANTS_DIR, PathManager
from thermo0d.app.postprocessing_variants import (
    default_postprocessing_variants_dir,
    generate_postprocessing_variants,
    resolve_postprocessing_base_config,
)
from thermo0d.app.runner import run_simulation
from thermo0d.input.config_loader import ConfigLoadError
from thermo0d.input.config_resolver import ConfigResolver


def parse_args(args_list: list[str] | None = None):
    parser = argparse.ArgumentParser(description='MotorSim Simulation starten')
    parser.add_argument(
        '--project',
        type=str,
        default=DEFAULT_PROJECT,
        help='Projektordner für config.yaml, data/, out/ usw.',
    )
    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='Expliziter Pfad zu einer config.yaml, zu einem configs-Ordner oder zu einem Projektordner.',
    )
    parser.add_argument(
        '--test-space',
        type=str,
        default=DEFAULT_TEST_SPACE,
        help='Test-Space für Referenzdaten / Reports',
    )
    parser.add_argument('--pick-project', action='store_true', help='Projektordner per Dialog auswählen')
    parser.add_argument('--no-gui-pick', action='store_true', help='Keinen Dialog öffnen, wenn kein Projekt gefunden wurde')
    parser.add_argument(
        '--batch-variants',
        action='store_true',
        help='Alle YAML-Konfigurationen aus configs/variants nacheinander ausführen.',
    )
    parser.add_argument(
        '--batch-postprocessing-variants',
        action='store_true',
        help='Postprocessing-Testvarianten aus Basis-Config erzeugen und den generierten Variantenordner als Batch ausführen.',
    )
    parser.add_argument(
        '--generate-postprocessing-variants',
        action='store_true',
        help='Postprocessing-Testvarianten aus Basis-Config erzeugen, aber nicht automatisch ausführen.',
    )
    parser.add_argument(
        '--variants-dir',
        type=str,
        default=DEFAULT_VARIANTS_DIR,
        help='Ordner mit Varianten-Konfigurationen für den Batch-Modus.',
    )
    parser.add_argument(
        '--postprocessing-variants-dir',
        type=str,
        default=None,
        help='Optionaler Zielordner für generierte Postprocessing-Testvarianten. Standard: <variants-dir>/postprocessing.',
    )
    parser.add_argument(
        '--postprocessing-base-config',
        type=str,
        default=None,
        help='Basis-Konfiguration für die Generierung der Postprocessing-Testvarianten.',
    )
    parser.add_argument(
        '--continue-on-error',
        action='store_true',
        help='Im Batch-Modus nach Fehlern mit der nächsten Variante fortfahren.',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Nur auflösen und anzeigen, welche Konfiguration(en) ausgeführt würden.',
    )
    excel_group = parser.add_mutually_exclusive_group()
    excel_group.add_argument(
        '--excel',
        action='store_true',
        dest='excel',
        help='Excel-Export zusätzlich zu CSV erzwingen.',
    )
    excel_group.add_argument(
        '--no-excel',
        action='store_false',
        dest='excel',
        help='Excel-Export auch dann deaktivieren, wenn er in der config aktiviert ist.',
    )
    parser.set_defaults(excel=None)
    return parser.parse_args(args_list)



def _append_run_log(config_path: str, artifacts) -> None:
    summaries = getattr(artifacts, 'cycle_summaries', None) or []
    if not summaries:
        return
    s = summaries[-1]
    timestamp = datetime.now().strftime('%d/%m//%y %H:%M')
    cfg_name = Path(config_path).name
    total_wall_clock_s = float(getattr(artifacts, 'wall_clock_s', 0.0))
    line = (
        f'{timestamp} {cfg_name} '
        f'[cycle {s.cycle_index:03d}] '
        f'air_mass_mg={s.air_mass_mg:.3f} '
        f'cycle_runtime_s={s.runtime_s:.6f} '
        f'simulation_wall_clock_s={total_wall_clock_s:.6f} '
        f'simtime_s={total_wall_clock_s:.6f} '
        f'pdV_J={s.piston_work_J:.6f} '
        f'pmax_bar={s.pmax_bar:.6f}'
    )
    log_path = PathManager.central_log_dir() / 'run.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('a', encoding='utf-8') as f:
        f.write(line + '\n')



def _append_fail_log(config_path: str, exc: Exception) -> None:
    timestamp = datetime.now().strftime('%d/%m//%y %H:%M')
    cfg_name = Path(config_path).name
    exc_text = str(exc).replace('\r', ' ').replace('\n', ' | ')
    line = f'{timestamp} {cfg_name} {exc.__class__.__name__}: {exc_text}'
    log_path = PathManager.central_log_dir() / 'fail.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('a', encoding='utf-8') as f:
        f.write(line + '\n')



def _resolve_postprocessing_variant_configs(args, resolver: ConfigResolver, project_dir: Path) -> list[Path]:
    variants_dir = (
        Path(args.postprocessing_variants_dir).resolve()
        if args.postprocessing_variants_dir
        else default_postprocessing_variants_dir(project_dir, args.variants_dir)
    )
    base_hint = args.postprocessing_base_config or args.config
    if base_hint is not None:
        base_config = resolver.resolve_single_config(base_hint, project_dir)
    else:
        base_config = resolve_postprocessing_base_config(project_dir)
    generated = generate_postprocessing_variants(
        base_config,
        project_dir=project_dir,
        out_dir=variants_dir,
    )
    return [path.resolve() for path in generated]



def main(args_list: list[str] | None = None) -> int:
    args = parse_args(args_list)
    PathManager.override(
        default_project=args.project,
        default_test_space=args.test_space,
        default_variants_dir=args.variants_dir,
    )
    resolver = ConfigResolver(args.project, args.variants_dir)
    project_dir = resolver.resolve_project_dir(args.project, args.pick_project, args.no_gui_pick)

    config_paths: list[Path]
    if args.batch_postprocessing_variants:
        config_paths = _resolve_postprocessing_variant_configs(args, resolver, project_dir)
    elif args.generate_postprocessing_variants:
        config_paths = _resolve_postprocessing_variant_configs(args, resolver, project_dir)
    elif args.batch_variants:
        config_paths = resolver.resolve_batch_configs(args.variants_dir)
    else:
        config_paths = [resolver.resolve_single_config(args.config, project_dir)]

    for config_path in config_paths:
        print(f'[config] {config_path}')

    if args.generate_postprocessing_variants and not args.batch_postprocessing_variants:
        return 0
    if args.dry_run:
        return 0

    exit_code = 0
    for config_path in config_paths:
        try:
            artifacts = run_simulation(config_path, excel=args.excel)
            _append_run_log(str(config_path), artifacts)
        except ConfigLoadError as exc:
            _append_fail_log(str(config_path), exc)
            exit_code = 2
            print(str(exc), file=sys.stderr)
            if args.continue_on_error:
                print(f'[WARN] Variante fehlgeschlagen: {config_path}', file=sys.stderr)
                continue
            return exit_code
        except Exception as exc:
            _append_fail_log(str(config_path), exc)
            exit_code = 1
            if not args.continue_on_error:
                raise
            print(f'[WARN] Variante fehlgeschlagen: {config_path}', file=sys.stderr)
    return exit_code



def run() -> int:
    return main(sys.argv[1:])
