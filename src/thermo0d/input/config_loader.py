from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from thermo0d.config.models import RootConfig
from thermo0d.config_versioning import VERSIONING_KEY, migrate_config_data


class ConfigLoadError(RuntimeError):
    """Benutzerfreundlicher Fehler beim Lesen oder Validieren einer Konfiguration."""

    def __init__(self, path: str | Path, message: str, *, kind: str = 'config_load_error') -> None:
        self.path = Path(path).resolve()
        self.kind = kind
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


SIMULATION_ROOT_KEYS = frozenset({'preprocessing', 'simulation', 'postprocessing'})
PLOT_LAYOUT_ROOT_KEYS = frozenset({'figures'})


def parse_yaml_mapping(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).resolve()
    try:
        text = resolved.read_text(encoding='utf-8')
    except OSError as exc:
        raise ConfigLoadError(
            resolved,
            _format_os_error(resolved, exc),
            kind='file_error',
        ) from exc

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigLoadError(
            resolved,
            _format_yaml_error(resolved, exc),
            kind='yaml_error',
        ) from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigLoadError(
            resolved,
            _format_non_mapping_error(resolved, raw),
            kind='yaml_structure_error',
        )
    return raw


def is_simulation_config_mapping(raw: dict[str, Any]) -> bool:
    return any(key in raw for key in SIMULATION_ROOT_KEYS)


def is_plot_layout_mapping(raw: dict[str, Any]) -> bool:
    return 'figures' in raw and not is_simulation_config_mapping(raw)


class ConfigLoader:
    @staticmethod
    def load(path: str | Path) -> RootConfig:
        resolved = Path(path).resolve()
        raw = parse_yaml_mapping(resolved)

        if is_plot_layout_mapping(raw):
            raise ConfigLoadError(
                resolved,
                _format_plot_layout_error(resolved, raw),
                kind='plot_layout_instead_of_simulation_config',
            )

        try:
            migrated = migrate_config_data(raw)
        except ValueError as exc:
            raise ConfigLoadError(
                resolved,
                _format_config_normalization_error(resolved, exc),
                kind='config_normalization_error',
            ) from exc
        validated_input = dict(migrated)
        validated_input.pop(VERSIONING_KEY, None)

        try:
            return RootConfig.model_validate(validated_input)
        except ValidationError as exc:
            raise ConfigLoadError(
                resolved,
                _format_pydantic_validation_error(resolved, exc),
                kind='pydantic_validation_error',
            ) from exc


def load_config(path: str | Path) -> RootConfig:
    return ConfigLoader.load(path)


_LINE = '=' * 72
_SUBLINE = '-' * 72


def _format_os_error(path: Path, exc: OSError) -> str:
    return '\n'.join([
        _LINE,
        'KONFIGURATION KONNTE NICHT GELESEN WERDEN',
        _SUBLINE,
        f'Datei   : {path}',
        f'Fehler  : {exc.__class__.__name__}: {exc}',
        _LINE,
    ])



def _format_yaml_error(path: Path, exc: yaml.YAMLError) -> str:
    lines = [
        _LINE,
        'YAML-SYNTAXFEHLER IN DER KONFIGURATION',
        _SUBLINE,
        f'Datei   : {path}',
    ]
    mark = getattr(exc, 'problem_mark', None)
    problem = getattr(exc, 'problem', None)
    context = getattr(exc, 'context', None)
    if mark is not None:
        lines.append(f'Position: Zeile {mark.line + 1}, Spalte {mark.column + 1}')
    if problem:
        lines.append(f'Problem : {problem}')
    if context:
        lines.append(f'Kontext : {context}')
    lines.extend([
        _SUBLINE,
        'Bitte YAML-Einrückung, Doppelpunkte, Bindestriche und Listenstruktur prüfen.',
        _LINE,
    ])
    return '\n'.join(lines)



def _format_non_mapping_error(path: Path, raw: Any) -> str:
    return '\n'.join([
        _LINE,
        'UNGÜLTIGE YAML-STRUKTUR',
        _SUBLINE,
        f'Datei   : {path}',
        'Erwartet: Top-Level Mapping / Dictionary',
        f'Gefunden: {type(raw).__name__}',
        _SUBLINE,
        'Die Konfigurationsdatei muss oben Schlüssel wie preprocessing, simulation und postprocessing enthalten.',
        _LINE,
    ])



def _format_plot_layout_error(path: Path, raw: dict[str, Any]) -> str:
    keys_preview = ', '.join(sorted(str(k) for k in raw.keys())[:8]) or '<leer>'
    return '\n'.join([
        _LINE,
        'FALSCHER DATEITYP FÜR DEN SIMULATIONS-LOADER',
        _SUBLINE,
        f'Datei   : {path}',
        'Erkannt : Plot-/Diagramm-Layout statt Simulations-Konfiguration',
        f'Schlüssel: {keys_preview}',
        _SUBLINE,
        'Die Datei enthält "figures" und sieht wie eine Plot-Konfiguration aus.',
        'Erwartet werden Top-Level-Felder wie preprocessing, simulation und postprocessing.',
        'Bitte diese Datei nicht als Simulations-Config laden und nicht im Varianten-Batch mitlaufen lassen.',
        _LINE,
    ])


def _format_config_normalization_error(path: Path, exc: ValueError) -> str:
    return '\n'.join([
        _LINE,
        'KONFIGURATIONS-NORMALISIERUNG FEHLGESCHLAGEN',
        _SUBLINE,
        f'Datei   : {path}',
        f'Fehler  : {exc}',
        _SUBLINE,
        'Bitte zentrale Submodel-Referenzen und geerbte Felder der YAML-Datei pruefen.',
        _LINE,
    ])



def _format_pydantic_validation_error(path: Path, exc: ValidationError) -> str:
    error_entries: list[dict[str, Any]] = exc.errors(include_url=False)
    yaml_lines = _build_yaml_line_lookup(path)
    lines = [
        _LINE,
        'KONFIGURATIONS-VALIDIERUNG FEHLGESCHLAGEN',
        _SUBLINE,
        f'Datei   : {path}',
        f'Fehler  : {len(error_entries)}',
        _SUBLINE,
    ]
    for index, err in enumerate(error_entries, start=1):
        loc = err.get('loc', ())
        location = _format_error_location(loc)
        line_no = _line_for_error_location(yaml_lines, loc)
        message = str(err.get('msg', 'Unbekannter Validierungsfehler'))
        err_type = str(err.get('type', 'unknown'))
        input_value = _format_input_value(err.get('input', '<nicht verfügbar>'))
        lines.append(f'[{index}] Feld    : {location}')
        lines.append(f'    Zeile   : {line_no if line_no is not None else "<nicht gefunden>"}')
        lines.append(f'    Meldung : {message}')
        lines.append(f'    Typ     : {err_type}')
        lines.append(f'    Eingabe : {input_value}')
        ctx = err.get('ctx')
        if ctx:
            lines.append(f'    Kontext : {_format_input_value(ctx)}')
        lines.append('')
    lines.extend([
        _SUBLINE,
        'Bitte Feldnamen, Pflichtfelder, Datentypen und Wertebereiche der YAML-Datei prüfen.',
        _LINE,
    ])
    return '\n'.join(lines)


def _build_yaml_line_lookup(path: Path) -> dict[tuple[Any, ...], int]:
    try:
        text = path.read_text(encoding='utf-8')
        root = yaml.compose(text)
    except Exception:
        return {}
    if root is None:
        return {}
    result: dict[tuple[Any, ...], int] = {}
    _collect_yaml_line_lookup(root, (), result)
    return result


def _collect_yaml_line_lookup(node: yaml.Node, path: tuple[Any, ...], result: dict[tuple[Any, ...], int]) -> None:
    result.setdefault(path, int(node.start_mark.line) + 1)
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            key = _yaml_key_value(key_node)
            child_path = (*path, key)
            result[child_path] = int(key_node.start_mark.line) + 1
            _collect_yaml_line_lookup(value_node, child_path, result)
        return
    if isinstance(node, yaml.SequenceNode):
        for index, item_node in enumerate(node.value):
            child_path = (*path, index)
            result[child_path] = int(item_node.start_mark.line) + 1
            _collect_yaml_line_lookup(item_node, child_path, result)


def _yaml_key_value(node: yaml.Node) -> Any:
    value = getattr(node, 'value', None)
    if not isinstance(value, str):
        return value
    try:
        return int(value)
    except ValueError:
        return value


def _line_for_error_location(lines: dict[tuple[Any, ...], int], loc: tuple[Any, ...] | list[Any]) -> int | None:
    if not lines:
        return None
    parts = tuple(_normalize_error_location_part(part) for part in loc)
    if parts in lines:
        return lines[parts]

    # Pydantic union/discriminator branches can inject labels that are not YAML keys.
    candidate_paths = [()]
    for part in parts:
        expanded: list[tuple[Any, ...]] = []
        for base in candidate_paths:
            direct = (*base, part)
            if direct in lines:
                expanded.append(direct)
            expanded.append(base)
        candidate_paths = expanded
    for path_candidate in sorted(set(candidate_paths), key=len, reverse=True):
        if path_candidate in lines:
            return lines[path_candidate]
    while parts:
        parts = parts[:-1]
        if parts in lines:
            return lines[parts]
    return lines.get(())


def _normalize_error_location_part(part: Any) -> Any:
    if isinstance(part, int):
        return part
    text = str(part)
    try:
        return int(text)
    except ValueError:
        return text



def _format_error_location(loc: tuple[Any, ...] | list[Any]) -> str:
    if not loc:
        return '<root>'
    parts: list[str] = []
    for item in loc:
        if isinstance(item, int):
            if parts:
                parts[-1] = f'{parts[-1]}[{item}]'
            else:
                parts.append(f'[{item}]')
            continue
        text = str(item)
        if not parts:
            parts.append(text)
        else:
            parts.append(f'.{text}')
    return ''.join(parts)



def _format_input_value(value: Any, max_len: int = 120) -> str:
    try:
        text = repr(value)
    except Exception:
        text = f'<{type(value).__name__}>'
    text = text.replace('\n', '\\n')
    if len(text) > max_len:
        return text[: max_len - 3] + '...'
    return text
