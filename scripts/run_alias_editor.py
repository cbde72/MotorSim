from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication, QMessageBox

from thermo0d.gui.dialogs import exec_dialog, show_foreground
from thermo0d.gui.signal_alias_editor import SignalAliasEditor
from thermo0d.gui.signal_catalog import (
    DEFAULT_SIGNAL_ALIAS_NAME,
    DEFAULT_SIGNAL_CATALOG_NAME,
    generate_signal_alias_file,
    generate_signal_catalog_file,
)


def parse_args(args_list: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open the thermo0d signal alias editor for a project directory.")
    parser.add_argument("--project", default=str((ROOT / "Projekte").resolve()), help="Project directory containing config.yaml and result CSV files.")
    return parser.parse_args(args_list)


def _ensure_qapplication() -> tuple[QApplication, bool]:
    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QApplication([])
    assert app is not None
    return app, owns_app


def _format_startup_generation_errors(errors: list[tuple[str, Path, Exception]]) -> str:
    lines = [
        "Die automatische Erzeugung der Projektdateien konnte nicht vollständig ausgeführt werden.",
        "",
        "Betroffene Datei(en):",
    ]
    for label, path, exc in errors:
        lines.extend([
            f"- {label}",
            f"  Pfad   : {path}",
            f"  Fehler : {exc}",
            "",
        ])
    lines.extend([
        "Der Alias-Editor kann trotzdem ohne Auto-Generierung gestartet werden.",
        "Bereits vorhandene Alias-Dateien werden dann weiterverwendet.",
        "",
        "Tipp: Prüfe Schreibrechte, OneDrive-/Virenscanner-Sperren oder geöffnete YAML-Dateien.",
    ])
    return "\n".join(lines).strip()


def _confirm_start_without_generation(errors: list[tuple[str, Path, Exception]]) -> bool:
    app, owns_app = _ensure_qapplication()
    box = QMessageBox()
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Alias-Editor: Schreibzugriff fehlgeschlagen")
    box.setText("Die automatische Erzeugung der Signal-Katalog-/Alias-Dateien ist fehlgeschlagen.")
    box.setInformativeText("Möchtest du den Alias-Editor trotzdem ohne Auto-Generierung starten?")
    box.setDetailedText(_format_startup_generation_errors(errors))
    continue_button = box.addButton("Ohne Auto-Generierung starten", QMessageBox.AcceptRole)
    box.addButton("Abbrechen", QMessageBox.RejectRole)
    box.setDefaultButton(continue_button)
    exec_dialog(box)
    _ = app
    _ = owns_app
    return box.clickedButton() is continue_button


def _show_startup_error(title: str, text: str, informative: str | None = None, details: str | None = None) -> None:
    app, owns_app = _ensure_qapplication()
    box = QMessageBox()
    box.setIcon(QMessageBox.Critical)
    box.setWindowTitle(title)
    box.setText(text)
    if informative:
        box.setInformativeText(informative)
    if details:
        box.setDetailedText(details)
    exec_dialog(box)
    _ = app
    _ = owns_app


def _try_generate_project_files(project_dir: Path) -> list[tuple[str, Path, Exception]]:
    errors: list[tuple[str, Path, Exception]] = []
    catalog_path = (project_dir / DEFAULT_SIGNAL_CATALOG_NAME).resolve()
    alias_path = (project_dir / DEFAULT_SIGNAL_ALIAS_NAME).resolve()
    operations = [
        ("Signal-Katalog", catalog_path, lambda: generate_signal_catalog_file(project_dir, catalog_path)),
        ("Signal-Alias-Datei", alias_path, lambda: generate_signal_alias_file(project_dir, alias_path)),
    ]
    for label, path, operation in operations:
        try:
            operation()
        except (PermissionError, OSError) as exc:
            errors.append((label, path, exc))
    return errors


def main(args_list: list[str] | None = None) -> int:
    args = parse_args(args_list)
    project_dir = Path(args.project).expanduser().resolve()

    generation_errors = _try_generate_project_files(project_dir)
    auto_generate_missing = True
    if generation_errors:
        auto_generate_missing = False
        if not _confirm_start_without_generation(generation_errors):
            return 1

    os.environ['THERMO0D_DEFAULT_PROJECT'] = str(project_dir)
    try:
        os.chdir(project_dir)
    except OSError as exc:
        _show_startup_error(
            "Alias-Editor: Projektordner nicht zugreifbar",
            "Der Projektordner konnte nicht als Arbeitsverzeichnis gesetzt werden.",
            informative=f"Pfad: {project_dir}",
            details=str(exc),
        )
        return 1

    app, owns_app = _ensure_qapplication()
    app.setOrganizationName('OpenAI')
    app.setApplicationName('Thermo0DSignalAliasEditor')
    win = SignalAliasEditor(project_dir, auto_generate_missing=auto_generate_missing)
    show_foreground(win)
    if owns_app:
        return int(app.exec())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
