from __future__ import annotations

from pathlib import Path
from tkinter import Tk, filedialog

from thermo0d.input.config_loader import (
    ConfigLoadError,
    is_plot_layout_mapping,
    is_simulation_config_mapping,
    parse_yaml_mapping,
)


class ConfigResolver:
    def __init__(self, project_dir: str | Path, variants_dir: str | Path):
        self.project_dir = Path(project_dir).resolve()
        self.variants_dir = Path(variants_dir).resolve()

    @staticmethod
    def _yaml_files(directory: Path) -> list[Path]:
        return sorted([*directory.glob('*.yaml'), *directory.glob('*.yml')])

    @staticmethod
    def _is_simulation_config_file(path: Path) -> bool:
        try:
            raw = parse_yaml_mapping(path)
        except ConfigLoadError:
            return False
        if is_plot_layout_mapping(raw):
            return False
        return is_simulation_config_mapping(raw)

    @classmethod
    def _simulation_yaml_files(cls, directory: Path) -> list[Path]:
        return [path for path in cls._yaml_files(directory) if cls._is_simulation_config_file(path)]

    @staticmethod
    def pick_project_dir(initial_dir: str | Path) -> Path | None:
        root = Tk()
        root.withdraw()
        selected = filedialog.askdirectory(initialdir=str(initial_dir), title='Projektordner auswählen')
        root.destroy()
        if not selected:
            return None
        return Path(selected).resolve()

    def resolve_project_dir(self, requested_project: str | Path, pick_project: bool, no_gui_pick: bool) -> Path:
        project_dir = Path(requested_project).resolve()
        if project_dir.exists():
            return project_dir
        if pick_project and not no_gui_pick:
            selected = self.pick_project_dir(self.project_dir)
            if selected is not None:
                return selected
        return project_dir

    def resolve_single_config(self, config_value: str | None, project_dir: Path) -> Path:
        if config_value is None:
            candidate = project_dir / 'config.yaml'
            if candidate.exists():
                return candidate.resolve()
            yaml_files = self._simulation_yaml_files(project_dir)
            if len(yaml_files) == 1:
                return yaml_files[0].resolve()
            raise FileNotFoundError(f'Keine eindeutige Konfiguration in {project_dir}')

        candidate = Path(config_value)
        if candidate.is_file():
            return candidate.resolve()
        if candidate.is_dir():
            yaml_files = self._simulation_yaml_files(candidate.resolve())
            if len(yaml_files) == 1:
                return yaml_files[0].resolve()
            candidate_file = candidate.resolve() / 'config.yaml'
            if candidate_file.exists():
                return candidate_file.resolve()
            raise FileNotFoundError(f'Kein eindeutiger YAML-Configpfad in {candidate}')
        if candidate.is_absolute() and candidate.is_file():
            return candidate.resolve()
        if candidate.is_absolute() and candidate.is_dir():
            yaml_files = self._simulation_yaml_files(candidate)
            if len(yaml_files) == 1:
                return yaml_files[0].resolve()
            candidate_file = candidate / 'config.yaml'
            if candidate_file.exists():
                return candidate_file.resolve()
            raise FileNotFoundError(f'Kein eindeutiger YAML-Configpfad in {candidate}')

        project_candidate = (project_dir / candidate).resolve()
        if project_candidate.is_file():
            return project_candidate
        if project_candidate.is_dir():
            yaml_files = self._simulation_yaml_files(project_candidate)
            if len(yaml_files) == 1:
                return yaml_files[0].resolve()
            candidate_file = project_candidate / 'config.yaml'
            if candidate_file.exists():
                return candidate_file.resolve()

        variants_candidate = (self.variants_dir / candidate).resolve()
        if variants_candidate.is_file():
            return variants_candidate

        raise FileNotFoundError(f'Konfiguration nicht gefunden: {config_value}')

    def resolve_batch_configs(self, variants_dir: str | Path) -> list[Path]:
        raw_directory = Path(variants_dir)
        directory = raw_directory.resolve() if raw_directory.exists() else (self.project_dir / raw_directory).resolve()
        yaml_files = self._simulation_yaml_files(directory)
        if not yaml_files:
            raise FileNotFoundError(f'Keine Varianten gefunden in {directory}')
        return yaml_files
