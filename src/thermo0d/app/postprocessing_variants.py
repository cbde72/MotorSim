from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

POSTPROCESSING_VARIANTS_SUBDIR = 'postprocessing'
DEFAULT_POSTPROCESSING_BASE_CONFIG = 'A156A1-2V-REX-V09d_WH02-Vibe_PP_RK45.yaml'


@dataclass(frozen=True, slots=True)
class PostprocessingVariantSpec:
    suffix: str
    description: str
    csv_enabled: bool = True
    excel_enabled: bool = True
    csv_separator: str = ';'
    sampling_mode: str = 'crank_angle'
    sampling_step: float = 1.0
    final_cycle_uniform_enabled: bool = True
    final_cycle_uniform_step_deg: float = 1.0
    check_report_enabled: bool = True
    check_report_html_enabled: bool = True
    plots_enabled: bool = True
    plots_source: str = 'last_cycle_uniform'
    plots_auto_create_defaults: bool = False
    plot_layout_entries: tuple[dict[str, Any], ...] = (
        {'enabled': True, 'path': 'plot_configs/plot.yaml', 'prefix': ''},
        {'enabled': True, 'path': 'plot_configs/plot10.yaml', 'prefix': 'plot10'},
    )


DEFAULT_VARIANT_SPECS: tuple[PostprocessingVariantSpec, ...] = (
    PostprocessingVariantSpec(
        suffix='pp01_ref_all',
        description='Referenzfall mit allen relevanten Postprocessing-Artefakten aktiv: CSV, Excel, Check-Report CSV+HTML, Uniform-Last-Cycle und zwei Plot-Layouts.',
    ),
    PostprocessingVariantSpec(
        suffix='pp02_no_csv',
        description='Testet deaktivierte Haupt-CSV bei weiterhin aktivem Excel-, Check-Report-, Uniform-Last-Cycle- und Plot-Export.',
        csv_enabled=False,
    ),
    PostprocessingVariantSpec(
        suffix='pp03_no_xlsx',
        description='Testet deaktivierten Excel-Export bei aktivem CSV-, Check-Report-, Uniform-Last-Cycle- und Plot-Export.',
        excel_enabled=False,
    ),
    PostprocessingVariantSpec(
        suffix='pp04_no_chk',
        description='Testet vollständig deaktivierten Check-Report bei sonst aktivem CSV-, Excel-, Uniform-Last-Cycle- und Plot-Export.',
        check_report_enabled=False,
        check_report_html_enabled=False,
    ),
    PostprocessingVariantSpec(
        suffix='pp05_no_plots',
        description='Testet deaktivierte Plot-Ausgabe bei weiterhin aktivem CSV-, Excel-, Check-Report- und Uniform-Last-Cycle-Export.',
        plots_enabled=False,
        plot_layout_entries=(),
    ),
    PostprocessingVariantSpec(
        suffix='pp06_rows_src',
        description='Testet Plot-Rendering aus export_rows statt aus last_cycle_uniform bei ansonsten vollständigem Artefakt-Set.',
        plots_source='export_rows',
    ),
    PostprocessingVariantSpec(
        suffix='pp07_no_uniform',
        description='Testet deaktivierten zusätzlichen Last-Cycle-Uniform-Export bei weiterhin aktivem CSV-, Excel-, Check-Report- und Plot-Export.',
        final_cycle_uniform_enabled=False,
    ),
    PostprocessingVariantSpec(
        suffix='pp08_uniform_5deg',
        description='Testet gröberes Raster des zusätzlichen Last-Cycle-Uniform-Exports mit 5 deg.',
        final_cycle_uniform_step_deg=5.0,
    ),
    PostprocessingVariantSpec(
        suffix='pp09_ca_5deg',
        description='Testet crank-angle-basiertes Export-Sampling mit 5 deg Schrittweite.',
        sampling_step=5.0,
    ),
    PostprocessingVariantSpec(
        suffix='pp10_time_1e4',
        description='Testet zeitbasiertes Export-Sampling mit 1e-4 s und Plot-Quelle export_rows.',
        sampling_mode='time',
        sampling_step=1.0e-4,
        plots_source='export_rows',
    ),
    PostprocessingVariantSpec(
        suffix='pp11_auto_layouts',
        description='Testet automatische Standard-Layout-Erzeugung mit plot.yaml und plot10.yaml statt expliziter Layout-Liste.',
        plots_auto_create_defaults=True,
        plot_layout_entries=(),
    ),
    PostprocessingVariantSpec(
        suffix='pp12_plot10_only',
        description='Testet ein alternatives Plot-Set mit nur einem expliziten Einzelplot-Layout.',
        plot_layout_entries=(
            {'enabled': True, 'path': 'plot_configs/plot10.yaml', 'prefix': 'plot10'},
        ),
    ),
    PostprocessingVariantSpec(
        suffix='pp13_rows_csv_comma',
        description='Testet alternatives CSV-Trennzeichen , zusammen mit Plot-Ausgabe aus export_rows und einem einzelnen Plot-Layout.',
        csv_separator=',',
        plots_source='export_rows',
        plot_layout_entries=(
            {'enabled': True, 'path': 'plot_configs/plot.yaml', 'prefix': ''},
        ),
    ),
)


def default_postprocessing_variants_dir(project_dir: str | Path, variants_dir: str | Path | None = None) -> Path:
    project_path = Path(project_dir).resolve()
    base_variants_dir = Path(variants_dir).resolve() if variants_dir is not None else (project_path / 'variants').resolve()
    return (base_variants_dir / POSTPROCESSING_VARIANTS_SUBDIR).resolve()



def _ensure_dict(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        value = {}
        parent[key] = value
    return value



def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    if not isinstance(raw, dict):
        raise ValueError(f'Config root must be a mapping: {path}')
    return raw



def _relocate_existing_relative_paths(node: Any, *, from_dir: Path, to_dir: Path, key_path: tuple[str, ...] = ()) -> Any:
    if isinstance(node, dict):
        return {
            key: _relocate_existing_relative_paths(value, from_dir=from_dir, to_dir=to_dir, key_path=key_path + (str(key),))
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [
            _relocate_existing_relative_paths(value, from_dir=from_dir, to_dir=to_dir, key_path=key_path)
            for value in node
        ]
    if not isinstance(node, str):
        return node

    raw = node.strip()
    if not raw or raw.startswith('${'):
        return node
    path = Path(raw)
    if path.is_absolute():
        return node
    if key_path[:2] == ('postprocessing', 'csv_path'):
        return node
    if key_path[:2] == ('postprocessing', 'excel_path'):
        return node
    if key_path[:3] == ('postprocessing', 'plots', 'output_dir'):
        return node

    candidate = (from_dir / path).resolve()
    if not candidate.exists():
        return node
    relative = os.path.relpath(candidate, to_dir)
    return Path(relative).as_posix()



def _variant_name(base_stem: str, spec: PostprocessingVariantSpec) -> str:
    return f'{base_stem}__{spec.suffix}'



def _result_dir_relative(variant_dir: Path, project_dir: Path, variant_name: str) -> str:
    target = (project_dir / 'results' / variant_name).resolve()
    return Path(os.path.relpath(target, variant_dir)).as_posix()



def _layout_entries_relative(base_dir: Path, variant_dir: Path, entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entry in entries:
        mapped = dict(entry)
        raw_path = str(mapped.get('path', '') or '').strip()
        if raw_path:
            candidate = (base_dir / raw_path).resolve()
            if candidate.exists():
                mapped['path'] = Path(os.path.relpath(candidate, variant_dir)).as_posix()
            else:
                mapped['path'] = raw_path.replace('\\', '/')
        result.append(mapped)
    return result



def _apply_postprocessing_variant(
    base_cfg: dict[str, Any],
    *,
    spec: PostprocessingVariantSpec,
    base_config_path: Path,
    out_dir: Path,
    project_dir: Path,
) -> tuple[str, dict[str, Any]]:
    cfg = deepcopy(base_cfg)
    cfg = _relocate_existing_relative_paths(cfg, from_dir=base_config_path.parent, to_dir=out_dir)
    variant_name = _variant_name(base_config_path.stem, spec)
    result_dir_rel = _result_dir_relative(out_dir, project_dir, variant_name)

    post = _ensure_dict(cfg, 'postprocessing')
    sampling = _ensure_dict(post, 'sampling')
    uniform = _ensure_dict(post, 'final_cycle_uniform_angle_export')
    check_report = _ensure_dict(post, 'check_report')
    plots = _ensure_dict(post, 'plots')
    layouts = _ensure_dict(plots, 'layouts')

    post['csv_enabled'] = bool(spec.csv_enabled)
    post['csv_separator'] = spec.csv_separator
    post['csv_path'] = f'{result_dir_rel}/{variant_name}.csv'
    post['excel_enabled'] = bool(spec.excel_enabled)
    post['excel_path'] = f'{result_dir_rel}/{variant_name}.xlsx'

    sampling['mode'] = spec.sampling_mode
    if spec.sampling_mode == 'crank_angle':
        sampling.pop('step_s', None)
        sampling['step_deg'] = float(spec.sampling_step)
    else:
        sampling.pop('step_deg', None)
        sampling['step_s'] = float(spec.sampling_step)

    uniform['enabled'] = bool(spec.final_cycle_uniform_enabled)
    uniform['step_deg'] = float(spec.final_cycle_uniform_step_deg)

    check_report['enabled'] = bool(spec.check_report_enabled)
    check_report['html_enabled'] = bool(spec.check_report_html_enabled)

    plots['enabled'] = bool(spec.plots_enabled)
    plots['source'] = spec.plots_source
    plots['output_dir'] = f'{result_dir_rel}/plots'
    layouts['auto_create_defaults'] = bool(spec.plots_auto_create_defaults)
    layouts['entries'] = _layout_entries_relative(base_config_path.parent, out_dir, spec.plot_layout_entries)

    cfg['test_description'] = f'Postprocessing-Testvariante {spec.suffix}: {spec.description}'
    return variant_name, cfg



def generate_postprocessing_variants(
    base_config_path: str | Path,
    *,
    project_dir: str | Path,
    out_dir: str | Path | None = None,
    specs: Iterable[PostprocessingVariantSpec] | None = None,
) -> list[Path]:
    base_config = Path(base_config_path).resolve()
    project_path = Path(project_dir).resolve()
    target_dir = Path(out_dir).resolve() if out_dir is not None else default_postprocessing_variants_dir(project_path)
    target_dir.mkdir(parents=True, exist_ok=True)

    base_cfg = _load_yaml_mapping(base_config)
    written: list[Path] = []
    for spec in tuple(specs or DEFAULT_VARIANT_SPECS):
        variant_name, variant_cfg = _apply_postprocessing_variant(
            base_cfg,
            spec=spec,
            base_config_path=base_config,
            out_dir=target_dir,
            project_dir=project_path,
        )
        target = target_dir / f'{variant_name}.yaml'
        target.write_text(yaml.safe_dump(variant_cfg, sort_keys=False, allow_unicode=True), encoding='utf-8')
        written.append(target)
    return written



def resolve_postprocessing_base_config(project_dir: str | Path, config_value: str | Path | None = None) -> Path:
    project_path = Path(project_dir).resolve()
    if config_value is not None:
        candidate = Path(config_value)
        if not candidate.is_absolute():
            direct = (project_path / candidate).resolve()
            if direct.exists():
                return direct
        return candidate.resolve()

    default_candidate = (project_path / DEFAULT_POSTPROCESSING_BASE_CONFIG).resolve()
    if default_candidate.exists():
        return default_candidate

    fallback = (project_path / 'config.yaml').resolve()
    if fallback.exists():
        return fallback

    yaml_candidates = sorted([*project_path.glob('*.yaml'), *project_path.glob('*.yml')])
    if len(yaml_candidates) == 1:
        return yaml_candidates[0].resolve()
    raise FileNotFoundError(
        f'Keine Basis-Konfiguration für Postprocessing-Testvarianten gefunden in {project_path}'
    )
