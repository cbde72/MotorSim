from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path


OUTPUT_DIR_NAME_MAX_LEN = 45
OUTPUT_DIR_HASH_LEN = 6
OUTPUT_DIR_HASH_SEPARATOR = '-'
INVALID_WINDOWS_PATH_CHARS_RE = re.compile(r'[<>:"/\|?*]')


@dataclass(frozen=True, slots=True)
class DirectorySettings:
    project_root: Path
    default_project: Path
    default_test_space: Path
    default_variants_dir: Path


class PathManager:
    _settings: DirectorySettings | None = None

    @classmethod
    def discover_project_root(cls) -> Path:
        return Path(__file__).resolve().parents[3]

    @classmethod
    def default_settings(cls) -> DirectorySettings:
        root = cls.discover_project_root().resolve()
        default_project = Path(os.environ.get('THERMO0D_DEFAULT_PROJECT', root / 'Projekte')).resolve()
        default_test_space = Path(os.environ.get('THERMO0D_DEFAULT_TEST_SPACE', root / 'test_space')).resolve()
        default_variants_dir = Path(os.environ.get('THERMO0D_DEFAULT_VARIANTS_DIR', default_project / 'variants')).resolve()
        return DirectorySettings(
            project_root=root,
            default_project=default_project,
            default_test_space=default_test_space,
            default_variants_dir=default_variants_dir,
        )

    @classmethod
    def settings(cls) -> DirectorySettings:
        if cls._settings is None:
            cls._settings = cls.default_settings()
        return cls._settings

    @classmethod
    def override(
        cls,
        *,
        project_root: str | Path | None = None,
        default_project: str | Path | None = None,
        default_test_space: str | Path | None = None,
        default_variants_dir: str | Path | None = None,
    ) -> DirectorySettings:
        current = cls.settings()
        updated = replace(
            current,
            project_root=Path(project_root).resolve() if project_root is not None else current.project_root,
            default_project=Path(default_project).resolve() if default_project is not None else current.default_project,
            default_test_space=Path(default_test_space).resolve() if default_test_space is not None else current.default_test_space,
            default_variants_dir=Path(default_variants_dir).resolve() if default_variants_dir is not None else current.default_variants_dir,
        )
        cls._settings = updated
        return updated

    @staticmethod
    def sanitize_output_dir_name(name: str, *, fallback: str = 'output') -> str:
        raw = str(name or '').strip()
        sanitized = INVALID_WINDOWS_PATH_CHARS_RE.sub('_', raw)
        sanitized = sanitized.strip().strip('.')
        return sanitized or fallback

    @classmethod
    def make_collision_safe_output_dir_name(cls, name: str, *, fallback: str = 'output') -> str:
        sanitized = cls.sanitize_output_dir_name(name, fallback=fallback)
        if len(sanitized) <= OUTPUT_DIR_NAME_MAX_LEN:
            return sanitized
        digest = hashlib.blake2s(sanitized.casefold().encode('utf-8'), digest_size=4).hexdigest()[:OUTPUT_DIR_HASH_LEN]
        prefix_len = max(1, OUTPUT_DIR_NAME_MAX_LEN - len(OUTPUT_DIR_HASH_SEPARATOR) - OUTPUT_DIR_HASH_LEN)
        prefix = sanitized[:prefix_len].rstrip(' ._-') or sanitized[:prefix_len] or fallback[:prefix_len] or 'o'
        return f"{prefix}{OUTPUT_DIR_HASH_SEPARATOR}{digest}"[:OUTPUT_DIR_NAME_MAX_LEN].strip().strip('.') or fallback

    @classmethod
    def default_output_dir_name(cls, config_path: str | Path) -> str:
        return cls.make_collision_safe_output_dir_name(Path(config_path).stem)

    @classmethod
    def central_log_dir(cls) -> Path:
        return Path(os.environ.get('THERMO0D_CENTRAL_LOG_DIR', cls.settings().project_root / 'test_cases')).resolve()

    @classmethod
    def resolve_output_dir(cls, config_path: str | Path, configured_outdir: str | None = None) -> Path:
        config_path = Path(config_path).resolve()
        raw = str(configured_outdir or '').strip()
        if raw:
            candidate = Path(raw)
            if candidate.is_absolute():
                return candidate.resolve()
            return (config_path.parent / 'results' / cls.make_collision_safe_output_dir_name(candidate.name)).resolve()
        return (config_path.parent / 'results' / cls.default_output_dir_name(config_path)).resolve()

    @classmethod
    def resolve_results_dir(cls, config_path: str | Path, configured_outdir: str | None = None) -> Path:
        return (cls.resolve_output_dir(config_path, configured_outdir) / 'results').resolve()

    @classmethod
    def resolve_plots_dir(cls, config_path: str | Path, configured_outdir: str | None = None) -> Path:
        return (cls.resolve_output_dir(config_path, configured_outdir) / 'plots').resolve()

    @classmethod
    def output_file_name(cls, configured_path: str | None, *, fallback_name: str) -> str:
        raw = str(configured_path or '').strip()
        if not raw:
            return Path(fallback_name).name
        file_name = Path(raw.replace('\\', '/')).name.strip()
        return file_name or Path(fallback_name).name

    @classmethod
    def resolve_output_file(
        cls,
        config_path: str | Path,
        *,
        configured_outdir: str | None = None,
        configured_path: str | None = None,
        fallback_name: str,
    ) -> Path:
        results_dir = cls.resolve_results_dir(config_path, configured_outdir)
        return (results_dir / cls.output_file_name(configured_path, fallback_name=fallback_name)).resolve()

    @classmethod
    def resolve_plot_output_dir(cls, config_path: str | Path, configured_outdir: str | None = None) -> Path:
        return cls.resolve_plots_dir(config_path, configured_outdir)

    @classmethod
    def resolve_layout_path(
        cls,
        config_path: str | Path,
        layout_path: str | Path,
        *,
        configured_outdir: str | None = None,
        prefer_output_dir_when_missing: bool = False,
    ) -> Path:
        config_path = Path(config_path).resolve()
        candidate = Path(layout_path)
        if candidate.is_absolute():
            return candidate.resolve()
        config_relative = (config_path.parent / candidate).resolve()
        if config_relative.exists() or not prefer_output_dir_when_missing:
            return config_relative
        output_dir = cls.resolve_output_dir(config_path, configured_outdir)
        return (output_dir / candidate.name).resolve()


def get_directory_settings() -> DirectorySettings:
    return PathManager.settings()


DEFAULT_PROJECT = str(PathManager.settings().default_project)
DEFAULT_TEST_SPACE = str(PathManager.settings().default_test_space)
DEFAULT_VARIANTS_DIR = str(PathManager.settings().default_variants_dir)
