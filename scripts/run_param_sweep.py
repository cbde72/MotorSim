from __future__ import annotations

import argparse
import csv
import copy
import math
import re
import shutil
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml


THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT_HINT = THIS_FILE.parents[1] if THIS_FILE.parent.name == 'scripts' else THIS_FILE.parent


_SANITIZE_RE = re.compile(r'[^A-Za-z0-9._-]+')


@dataclass(slots=True)
class SweepRunRecord:
    run_index: int
    run_tag: str
    parameter_path: str
    value_repr: str
    status: str
    temp_config_path: str
    result_dir: str
    main_csv: str
    last_cycle_csv: str
    excel_path: str
    readme_path: str
    copied_plot_count: int
    copied_csv_count: int
    copied_readme_count: int
    error: str


class SweepConfigError(ValueError):
    pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run a parameter sweep for thermo0d configs.')
    parser.add_argument('--sweep-config', required=True, help='Path to the sweep control YAML.')
    parser.add_argument('--dry-run', action='store_true', help='Only generate configs and print the planned runs.')
    return parser.parse_args(argv)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open('r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise SweepConfigError(f'YAML root must be a mapping: {path}')
    return data


def save_yaml(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def sanitize_token(value: Any, *, fallback: str = 'value') -> str:
    if isinstance(value, float):
        if math.isnan(value):
            text = 'nan'
        elif math.isinf(value):
            text = 'inf' if value > 0 else 'ninf'
        else:
            text = format(value, '.12g')
    else:
        text = str(value)
    text = text.strip().replace(' ', '_')
    text = text.replace('+', 'plus').replace('%', 'pct')
    text = _SANITIZE_RE.sub('_', text).strip('._-')
    return text or fallback


def normalize_round_digits(parameter_cfg: dict[str, Any]) -> int | None:
    raw = parameter_cfg.get('round_digits')
    if raw is None:
        return None
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise SweepConfigError(f'parameter.round_digits must be an integer, got {raw!r}')
    if raw < 0:
        raise SweepConfigError('parameter.round_digits must be >= 0')
    return raw


def round_sweep_value(value: Any, round_digits: int | None) -> Any:
    if round_digits is None:
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return value
        rounded = round(value, round_digits)
        if rounded == 0:
            rounded = 0.0
        return rounded
    return value


def format_sweep_value(value: Any, round_digits: int | None) -> str:
    value = round_sweep_value(value, round_digits)
    if isinstance(value, float):
        if math.isnan(value):
            return 'nan'
        if math.isinf(value):
            return 'inf' if value > 0 else '-inf'
        if round_digits is None:
            return format(value, '.12g')
        text = f'{value:.{round_digits}f}'.rstrip('0').rstrip('.')
        return text if text and text != '-0' else '0'
    return str(value)


def _to_decimal(value: Any, *, field: str, section: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SweepConfigError(f'parameter.{section}.{field} must be numeric, got {value!r}') from exc


def _coerce_numeric_for_yaml(value: Decimal, *, prefer_int: bool) -> int | float:
    if prefer_int and value == value.to_integral_value():
        return int(value)
    return float(value)


def expand_parameter_values(parameter_cfg: dict[str, Any], round_digits: int | None) -> list[Any]:
    has_values = 'values' in parameter_cfg
    has_range = 'range' in parameter_cfg
    has_linspace = 'linspace' in parameter_cfg
    modes = int(has_values) + int(has_range) + int(has_linspace)
    if modes != 1:
        raise SweepConfigError('Use exactly one of parameter.values, parameter.range or parameter.linspace')

    if has_values:
        values = parameter_cfg.get('values')
        if not isinstance(values, list) or not values:
            raise SweepConfigError('parameter.values must be a non-empty list')
        return [round_sweep_value(v, round_digits) for v in values]

    if has_range:
        range_cfg = parameter_cfg.get('range')
        if not isinstance(range_cfg, dict):
            raise SweepConfigError('parameter.range must be a mapping with start, step, end')
        for key in ('start', 'step', 'end'):
            if key not in range_cfg:
                raise SweepConfigError(f'parameter.range.{key} is required')

        start_d = _to_decimal(range_cfg['start'], field='start', section='range')
        step_d = _to_decimal(range_cfg['step'], field='step', section='range')
        end_d = _to_decimal(range_cfg['end'], field='end', section='range')

        if step_d == 0:
            raise SweepConfigError('parameter.range.step must not be 0')
        if end_d > start_d and step_d < 0:
            raise SweepConfigError('parameter.range.step must be positive when end > start')
        if end_d < start_d and step_d > 0:
            raise SweepConfigError('parameter.range.step must be negative when end < start')

        prefer_int = all(isinstance(range_cfg[k], int) and not isinstance(range_cfg[k], bool) for k in ('start', 'step', 'end'))
        values: list[Any] = []
        current = start_d
        eps = abs(step_d) / Decimal('1000000') if step_d != 0 else Decimal('0')
        max_steps = 100000

        for _ in range(max_steps):
            if step_d > 0 and current > end_d + eps:
                break
            if step_d < 0 and current < end_d - eps:
                break
            values.append(round_sweep_value(_coerce_numeric_for_yaml(current, prefer_int=prefer_int), round_digits))
            current += step_d
        else:
            raise SweepConfigError('parameter.range generated too many values; check start/step/end')

        if not values:
            raise SweepConfigError('parameter.range produced no values')
        return values

    linspace_cfg = parameter_cfg.get('linspace')
    if not isinstance(linspace_cfg, dict):
        raise SweepConfigError('parameter.linspace must be a mapping with start, end, num')
    for key in ('start', 'end', 'num'):
        if key not in linspace_cfg:
            raise SweepConfigError(f'parameter.linspace.{key} is required')

    start_d = _to_decimal(linspace_cfg['start'], field='start', section='linspace')
    end_d = _to_decimal(linspace_cfg['end'], field='end', section='linspace')
    num = linspace_cfg['num']
    if not isinstance(num, int) or isinstance(num, bool):
        raise SweepConfigError(f'parameter.linspace.num must be an integer, got {num!r}')
    if num <= 0:
        raise SweepConfigError('parameter.linspace.num must be >= 1')

    if num == 1:
        return [round_sweep_value(_coerce_numeric_for_yaml(start_d, prefer_int=isinstance(linspace_cfg['start'], int) and not isinstance(linspace_cfg['start'], bool)), round_digits)]

    prefer_int = all(isinstance(linspace_cfg[k], int) and not isinstance(linspace_cfg[k], bool) for k in ('start', 'end'))
    step_d = (end_d - start_d) / Decimal(num - 1)
    values: list[Any] = []
    for i in range(num):
        current = start_d + step_d * Decimal(i)
        if i == num - 1:
            current = end_d
        values.append(round_sweep_value(_coerce_numeric_for_yaml(current, prefer_int=prefer_int), round_digits))
    return values


def resolve_project_root(sweep_cfg_path: Path, sweep_cfg: dict[str, Any]) -> Path:
    raw = str(sweep_cfg.get('project_root', '')).strip()
    if raw:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = (sweep_cfg_path.parent / candidate).resolve()
        return candidate.resolve()

    here_root = PROJECT_ROOT_HINT.resolve()
    if (here_root / 'src').is_dir() and (here_root / 'Projekte').is_dir():
        return here_root

    current = sweep_cfg_path.resolve().parent
    for parent in [current, *current.parents]:
        if (parent / 'src').is_dir() and (parent / 'Projekte').is_dir():
            return parent.resolve()

    raise SweepConfigError(
        'project_root could not be inferred. Set project_root explicitly in the sweep YAML.'
    )


def resolve_path(base_dir: Path, raw: str | None) -> Path | None:
    text = str(raw or '').strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path.resolve()


def require_mapping(node: dict[str, Any], key: str) -> dict[str, Any]:
    value = node.get(key)
    if not isinstance(value, dict):
        raise SweepConfigError(f'Missing or invalid mapping: {key}')
    return value


def set_nested_value(root: Any, path_text: str, value: Any) -> None:
    parts = [part for part in str(path_text).split('.') if part]
    if not parts:
        raise SweepConfigError('parameter.path must not be empty')
    node = root
    for idx, part in enumerate(parts[:-1]):
        next_part = parts[idx + 1]
        if isinstance(node, list):
            try:
                list_index = int(part)
            except ValueError as exc:
                raise SweepConfigError(f'List index expected in path at {part!r}') from exc
            if list_index < 0 or list_index >= len(node):
                raise SweepConfigError(f'List index out of range in path: {path_text}')
            node = node[list_index]
            continue
        if not isinstance(node, dict):
            raise SweepConfigError(f'Cannot traverse path {path_text!r} through non-container node at {part!r}')
        if part not in node:
            node[part] = [] if next_part.isdigit() else {}
        node = node[part]

    last = parts[-1]
    if isinstance(node, list):
        try:
            list_index = int(last)
        except ValueError as exc:
            raise SweepConfigError(f'List index expected in path at {last!r}') from exc
        if list_index < 0 or list_index >= len(node):
            raise SweepConfigError(f'List index out of range in path: {path_text}')
        node[list_index] = value
        return
    if not isinstance(node, dict):
        raise SweepConfigError(f'Cannot set path {path_text!r} on non-mapping target')
    node[last] = value


def render_template(template: str, ctx: dict[str, Any]) -> str:
    try:
        return template.format(**ctx)
    except KeyError as exc:
        missing = exc.args[0]
        raise SweepConfigError(f'Unknown template field {missing!r} in {template!r}') from exc


def unique_run_tag(run_index: int, parameter_name: str, value: Any) -> str:
    return f'run_{run_index:03d}_{sanitize_token(parameter_name)}_{sanitize_token(value)}'


def ensure_postprocessing_block(config: dict[str, Any]) -> dict[str, Any]:
    node = config.get('postprocessing')
    if not isinstance(node, dict):
        node = {}
        config['postprocessing'] = node
    return node


def copy_with_prefix(src: Path, dest_dir: Path, prefix: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f'{prefix}_{src.name}'
    shutil.copy2(src, dest)
    return dest


def gather_existing_files(paths: list[str | None]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        if not raw:
            continue
        p = Path(raw)
        if p.is_file():
            out.append(p)
    return out


def write_summary_csv(path: Path, rows: list[SweepRunRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        'run_index',
        'run_tag',
        'parameter_path',
        'value_repr',
        'status',
        'temp_config_path',
        'result_dir',
        'main_csv',
        'last_cycle_csv',
        'excel_path',
        'readme_path',
        'copied_plot_count',
        'copied_csv_count',
        'copied_readme_count',
        'error',
    ]
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
        writer.writeheader()
        for row in rows:
            writer.writerow({name: getattr(row, name) for name in fieldnames})


def run_sweep(sweep_cfg_path: Path, *, dry_run: bool = False) -> tuple[list[SweepRunRecord], Path]:
    sweep_cfg = load_yaml(sweep_cfg_path)
    project_root = resolve_project_root(sweep_cfg_path, sweep_cfg)
    src_dir = project_root / 'src'
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    from thermo0d.app.paths import PathManager  # type: ignore
    from thermo0d.app.runner import run_simulation  # type: ignore

    PathManager.override(
        project_root=project_root,
        default_project=project_root / 'Projekte',
        default_test_space=project_root / 'test_space',
        default_variants_dir=project_root / 'Projekte' / 'variants',
    )

    base_config_path = resolve_path(project_root, str(sweep_cfg.get('base_config', '')).strip())
    if base_config_path is None or not base_config_path.is_file():
        raise SweepConfigError('base_config is missing or does not point to a file')

    parameter_cfg = require_mapping(sweep_cfg, 'parameter')
    parameter_path = str(parameter_cfg.get('path', '')).strip()
    if not parameter_path:
        raise SweepConfigError('parameter.path must not be empty')
    parameter_name = parameter_path.split('.')[-1]
    parameter_label = str(parameter_cfg.get('label', '')).strip() or parameter_name
    round_digits = normalize_round_digits(parameter_cfg)

    values = expand_parameter_values(parameter_cfg, round_digits)

    sweep_name = str(sweep_cfg.get('sweep_name', '')).strip() or sanitize_token(base_config_path.stem, fallback='sweep')
    output_dir = resolve_path(project_root, str(sweep_cfg.get('output_dir', '')).strip())
    if output_dir is None:
        output_dir = (project_root / 'Projekte' / 'results' / 'sweeps' / sanitize_token(sweep_name)).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    collect_cfg = sweep_cfg.get('collect') if isinstance(sweep_cfg.get('collect'), dict) else {}
    copy_configs = bool(collect_cfg.get('copy_configs', True))
    copy_csv = bool(collect_cfg.get('copy_csv', True))
    copy_plots = bool(collect_cfg.get('copy_plots', True))
    copy_excel = bool(collect_cfg.get('copy_excel', False))
    copy_readme = bool(collect_cfg.get('copy_readme', False))
    keep_temp_configs = bool(sweep_cfg.get('keep_temp_configs', False))
    excel_override = sweep_cfg.get('excel')
    if excel_override not in (None, True, False):
        raise SweepConfigError('excel must be true, false or omitted')

    description_template = str(sweep_cfg.get('description_template', '')).strip()
    name_template = str(sweep_cfg.get('name_template', '')).strip()
    outdir_template = str(sweep_cfg.get('outdir_template', '')).strip() or '{sweep_name}_{run_tag}'
    csv_name_template = str(sweep_cfg.get('csv_name_template', '')).strip() or '{run_tag}.csv'
    excel_name_template = str(sweep_cfg.get('excel_name_template', '')).strip() or '{run_tag}.xlsx'

    base_config = load_yaml(base_config_path)
    records: list[SweepRunRecord] = []

    for run_index, value in enumerate(values, start=1):
        value = round_sweep_value(value, round_digits)
        value_repr = format_sweep_value(value, round_digits)
        run_tag = unique_run_tag(run_index, parameter_label, value_repr)
        ctx = {
            'index': run_index,
            'run_index': run_index,
            'run_tag': run_tag,
            'value': value,
            'value_repr': value_repr,
            'safe_value': sanitize_token(value_repr),
            'parameter_path': parameter_path,
            'parameter_name': parameter_name,
            'parameter_label': parameter_label,
            'round_digits': round_digits,
            'sweep_name': sweep_name,
            'base_stem': base_config_path.stem,
        }
        config = copy.deepcopy(base_config)
        set_nested_value(config, parameter_path, value)

        if description_template:
            config['test_description'] = render_template(description_template, ctx)
        elif isinstance(config.get('test_description'), str):
            config['test_description'] = f"{config['test_description']} | sweep {parameter_label}={value_repr}"

        if name_template and 'name' in config and isinstance(config['name'], str):
            config['name'] = render_template(name_template, ctx)
        elif 'name' in config and isinstance(config['name'], str):
            config['name'] = f"{config['name']} | {parameter_label}={value_repr}"

        post = ensure_postprocessing_block(config)
        post['outdir'] = sanitize_token(render_template(outdir_template, ctx), fallback=run_tag)
        post['csv_path'] = f"results/{render_template(csv_name_template, ctx)}"
        if excel_override is not False:
            post['excel_path'] = f"results/{render_template(excel_name_template, ctx)}"

        temp_config_path = base_config_path.with_name(f"{base_config_path.stem}__{run_tag}.yaml")
        save_yaml(config, temp_config_path)

        if copy_configs:
            (output_dir / 'configs').mkdir(parents=True, exist_ok=True)
            shutil.copy2(temp_config_path, output_dir / 'configs' / temp_config_path.name)

        if dry_run:
            print(f'[DRY-RUN] {run_tag}: {parameter_path}={value_repr}')
            print(f'          config = {temp_config_path}')
            print(f'          outdir = {post["outdir"]}')
            records.append(
                SweepRunRecord(
                    run_index=run_index,
                    run_tag=run_tag,
                    parameter_path=parameter_path,
                    value_repr=value_repr,
                    status='dry-run',
                    temp_config_path=str(temp_config_path),
                    result_dir='',
                    main_csv='',
                    last_cycle_csv='',
                    excel_path='',
                    readme_path='',
                    copied_plot_count=0,
                    copied_csv_count=0,
                    copied_readme_count=0,
                    error='',
                )
            )
            if not keep_temp_configs:
                temp_config_path.unlink(missing_ok=True)
            continue

        status = 'ok'
        result_dir = ''
        main_csv = ''
        last_cycle_csv = ''
        excel_path = ''
        readme_path = ''
        copied_plot_count = 0
        copied_csv_count = 0
        copied_readme_count = 0
        error_text = ''

        try:
            artifacts = run_simulation(temp_config_path, excel=excel_override)
            result_dir = str(Path(artifacts.csv_path).resolve().parents[1]) if artifacts.csv_path else ''

            csv_sources = gather_existing_files([
                artifacts.csv_path,
                artifacts.last_cycle_uniform_csv_path,
                artifacts.check_report_csv_path,
            ])
            if copy_csv:
                for src in csv_sources:
                    copy_with_prefix(src, output_dir / 'csv', run_tag)
                    copied_csv_count += 1
            if artifacts.csv_path:
                main_csv = str(Path(artifacts.csv_path).resolve())
            if artifacts.last_cycle_uniform_csv_path:
                last_cycle_csv = str(Path(artifacts.last_cycle_uniform_csv_path).resolve())
            if artifacts.excel_path:
                excel_path = str(Path(artifacts.excel_path).resolve())
                if copy_excel and Path(artifacts.excel_path).is_file():
                    copy_with_prefix(Path(artifacts.excel_path), output_dir / 'excel', run_tag)

            if artifacts.readme_path:
                readme_path = str(Path(artifacts.readme_path).resolve())
                if copy_readme and Path(artifacts.readme_path).is_file():
                    copy_with_prefix(Path(artifacts.readme_path), output_dir / 'readme', run_tag)
                    copied_readme_count += 1

            if copy_plots:
                for raw in artifacts.generated_plot_paths:
                    src = Path(raw)
                    if src.is_file():
                        copy_with_prefix(src, output_dir / 'plots', run_tag)
                        copied_plot_count += 1
        except Exception as exc:
            status = 'failed'
            error_text = f'{exc.__class__.__name__}: {exc}'
            print(f'[ERROR] {run_tag} failed: {error_text}', file=sys.stderr)
        finally:
            if status == 'ok' and not keep_temp_configs:
                temp_config_path.unlink(missing_ok=True)

        records.append(
            SweepRunRecord(
                run_index=run_index,
                run_tag=run_tag,
                parameter_path=parameter_path,
                value_repr=str(value),
                status=status,
                temp_config_path=str(temp_config_path),
                result_dir=result_dir,
                main_csv=main_csv,
                last_cycle_csv=last_cycle_csv,
                excel_path=excel_path,
                readme_path=readme_path,
                copied_plot_count=copied_plot_count,
                copied_csv_count=copied_csv_count,
                copied_readme_count=copied_readme_count,
                error=error_text,
            )
        )

    summary_path = output_dir / 'sweep_summary.csv'
    write_summary_csv(summary_path, records)
    return records, summary_path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sweep_cfg_path = Path(args.sweep_config).resolve()
    records, summary_path = run_sweep(sweep_cfg_path, dry_run=bool(args.dry_run))
    total = len(records)
    failed = sum(1 for row in records if row.status == 'failed')
    print(f'[SUMMARY] runs={total} failed={failed} summary={summary_path}')
    return 1 if failed else 0


if __name__ == '__main__':
    this_file = Path(__file__).resolve()
    project_root = this_file.parents[1] if this_file.parent.name == 'scripts' else this_file.parent
# %%
# %%
    default_cfg = project_root / 'Projekte' / 'sweeps' / 'lambda_v15_1_5.yaml'


    print (default_cfg)
    simulated_argv = ['--sweep-config', str(default_cfg)]

    raise SystemExit(main(simulated_argv if len(sys.argv) == 1 else None))
