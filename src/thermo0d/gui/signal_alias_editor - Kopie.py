from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFrame,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QStyleFactory,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
)

from .dialogs import exec_dialog, get_open_file_name, show_foreground
from .signal_catalog import DEFAULT_SIGNAL_ALIAS_NAME, generate_signal_alias_file

APP_ORG = "OpenAI"
APP_NAME = "Thermo0DSignalAliasEditor"


class SignalAliasEditor(QMainWindow):
    def __init__(self, project_dir: Path | str, *, auto_generate_missing: bool = True) -> None:
        super().__init__()
        self.settings = QSettings(APP_ORG, APP_NAME)
        self.project_dir = Path(project_dir).resolve()
        self.alias_path = self.project_dir / DEFAULT_SIGNAL_ALIAS_NAME
        self.auto_generate_missing = bool(auto_generate_missing)
        self.data: dict[str, Any] = {}
        self.style_action_group = QActionGroup(self)
        self.style_action_group.setExclusive(True)

        self.setWindowTitle("Thermo0D Signal Alias Editor")
        self.resize(1480, 860)
        self._build_window()
        self._build_actions()
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()
        self._build_docks()
        self._populate_style_menu()
        self._apply_saved_style()
        self._restore_layout()

        last_alias = self._last_alias_path()
        if last_alias is not None:
            self.alias_path = last_alias
        self.path_label.setText(str(self.alias_path))

        if not self.alias_path.exists():
            if self.auto_generate_missing:
                try:
                    generate_signal_alias_file(self.project_dir, self.alias_path)
                except Exception as exc:
                    self._show_file_error(
                        "Alias-Datei erzeugen",
                        "Die Alias-Datei konnte beim Start nicht automatisch erzeugt werden.",
                        self.alias_path,
                        exc,
                    )
                    self.data = {"format": "thermo0d-signal-aliases-v1", "signals": []}
                    self.populate_table()
                    self.showMaximized()
                    self.statusBar().showMessage("Bereit", 2500)
                    return
            else:
                self.data = {"format": "thermo0d-signal-aliases-v1", "signals": []}
                self.populate_table()
                self.showMaximized()
                self.statusBar().showMessage("Alias-Datei fehlt. Editor wurde ohne Auto-Generierung gestartet.", 6000)
                return
        self.load_alias_file(self.alias_path)
        self.showMaximized()
        self.statusBar().showMessage("Bereit", 2500)

    def _build_window(self) -> None:
        self.setDockOptions(
            QMainWindow.AllowNestedDocks
            | QMainWindow.AllowTabbedDocks
            | QMainWindow.GroupedDragging
            | QMainWindow.AnimatedDocks
        )
        central = QWidget()
        central.setMinimumSize(0, 0)
        central.setMaximumSize(0, 0)
        central.hide()
        self.setCentralWidget(central)

    def _build_actions(self) -> None:
        self.act_open = QAction("Öffnen", self)
        self.act_open.triggered.connect(self.open_file)
        self.act_save = QAction("Speichern", self)
        self.act_save.triggered.connect(self.save_file)
        self.act_regen = QAction("Neu erzeugen", self)
        self.act_regen.triggered.connect(self.regenerate_file)
        self.act_layout_save = QAction("Layout speichern", self)
        self.act_layout_save.triggered.connect(self.save_layout_to_settings)
        self.act_layout_reset = QAction("Layout zurücksetzen", self)
        self.act_layout_reset.triggered.connect(self.reset_layout)
        self.act_quit = QAction("Beenden", self)
        self.act_quit.triggered.connect(self.close)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("Datei")
        for action in [self.act_open, self.act_save, self.act_regen]:
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        self.view_menu = self.menuBar().addMenu("Ansicht")
        layout_menu = self.menuBar().addMenu("Layout")
        layout_menu.addAction(self.act_layout_save)
        layout_menu.addAction(self.act_layout_reset)
        self.style_menu = self.menuBar().addMenu("Style")

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        for action in [self.act_open, self.act_save, self.act_regen]:
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addAction(self.act_layout_save)
        toolbar.addAction(self.act_layout_reset)

    def _build_statusbar(self) -> None:
        status = QStatusBar(self)
        self.setStatusBar(status)
        self.status_project = QLabel()
        self.status_alias = QLabel()
        self.status_rows = QLabel()
        for label in [self.status_project, self.status_alias, self.status_rows]:
            label.setFrameStyle(QFrame.Panel | QFrame.Sunken)
            label.setContentsMargins(6, 0, 6, 0)
            status.addPermanentWidget(label)

    def _build_docks(self) -> None:
        self.controls_panel = self._build_controls_panel()
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["Signal", "Einheit", "Kürzel", "Quelle", "Kategorie", "Familie", "Typ", "Vorschlag", "Benutzername"])
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.controls_dock = self._create_dock("Projekt", self.controls_panel)
        self.table_dock = self._create_dock("Signal Aliases", self.table)
        self.all_docks = [self.controls_dock, self.table_dock]
        self._apply_default_layout()
        for dock in self.all_docks:
            self.view_menu.addAction(dock.toggleViewAction())

    def _build_controls_panel(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self.path_label = QLabel()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter nach Signal, Quelle, Einheit oder Name …")
        self.filter_edit.textChanged.connect(self.apply_filter)
        save_btn = QPushButton("Speichern")
        save_btn.clicked.connect(self.save_file)
        top.addWidget(QLabel("Datei:"))
        top.addWidget(self.path_label, 1)
        top.addWidget(QLabel("Filter:"))
        top.addWidget(self.filter_edit, 1)
        top.addWidget(save_btn)
        layout.addLayout(top)
        return root

    def _create_dock(self, title: str, widget: QWidget) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(f"dock_{title.lower().replace(' ', '_')}")
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        dock.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        return dock

    def _apply_default_layout(self) -> None:
        for dock in getattr(self, 'all_docks', []):
            self.removeDockWidget(dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.controls_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.table_dock)

    def _restore_layout(self) -> None:
        geometry = self.settings.value('window/geometry')
        state = self.settings.value('window/state')
        restored = False
        if geometry:
            restored = bool(self.restoreGeometry(geometry))
        if state:
            restored = bool(self.restoreState(state)) or restored
        if not restored:
            self._apply_default_layout()

    def save_layout_to_settings(self) -> None:
        self.settings.setValue('window/geometry', self.saveGeometry())
        self.settings.setValue('window/state', self.saveState())
        self.settings.sync()
        self.statusBar().showMessage('Layout gespeichert', 2500)

    def reset_layout(self) -> None:
        self.settings.remove('window/geometry')
        self.settings.remove('window/state')
        self._apply_default_layout()
        self.statusBar().showMessage('Layout zurückgesetzt', 2500)

    def _populate_style_menu(self) -> None:
        self.style_menu.clear()
        for style_name in sorted(QStyleFactory.keys()):
            action = QAction(style_name, self)
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, name=style_name: self.apply_style(name))
            self.style_action_group.addAction(action)
            self.style_menu.addAction(action)

    def _apply_saved_style(self) -> None:
        style_name = str(self.settings.value('ui/style_name', QApplication.style().objectName()))
        available = {name.lower(): name for name in QStyleFactory.keys()}
        key = style_name.lower()
        if key not in available and available:
            style_name = sorted(available.values())[0]
        elif key in available:
            style_name = available[key]
        self.apply_style(style_name, announce=False)

    def apply_style(self, style_name: str, announce: bool = True) -> None:
        if style_name and style_name in QStyleFactory.keys():
            QApplication.setStyle(QStyleFactory.create(style_name))
            self.settings.setValue('ui/style_name', style_name)
            for action in self.style_action_group.actions():
                action.blockSignals(True)
                action.setChecked(action.text() == style_name)
                action.blockSignals(False)
            self._update_statusbar_fields()
            if announce:
                self.statusBar().showMessage(f'Style gewechselt: {style_name}', 2500)

    def _last_alias_path(self) -> Path | None:
        text = str(self.settings.value('files/last_alias_path', '') or '').strip()
        if not text:
            return None
        candidate = Path(text).expanduser()
        return candidate if candidate.exists() else None

    def _show_file_error(self, title: str, text: str, path: Path, exc: Exception) -> None:
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setInformativeText(f"Datei: {path}")
        msg.setDetailedText(str(exc))
        exec_dialog(msg)

    def _update_statusbar_fields(self) -> None:
        visible_rows = sum(1 for row in range(self.table.rowCount()) if not self.table.isRowHidden(row))
        self.status_project.setText(f"Projekt: {self.project_dir}")
        self.status_alias.setText(f"Alias-Datei: {self.alias_path}")
        self.status_rows.setText(f"Zeilen: {visible_rows}/{self.table.rowCount()}")

    def open_file(self) -> None:
        path, _ = get_open_file_name(self, "Alias-Datei öffnen", str(self.project_dir), "YAML (*.yaml *.yml)")
        if path:
            self.load_alias_file(Path(path))

    def regenerate_file(self) -> None:
        try:
            generate_signal_alias_file(self.project_dir, self.alias_path)
        except Exception as exc:
            self._show_file_error(
                "Alias-Datei neu erzeugen",
                "Die Alias-Datei konnte nicht neu erzeugt werden.",
                self.alias_path,
                exc,
            )
            return
        self.load_alias_file(self.alias_path)
        self.statusBar().showMessage(f"Alias-Datei neu erzeugt: {self.alias_path}", 3000)

    def load_alias_file(self, path: Path) -> None:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            self._show_file_error(
                "Alias-Datei laden",
                "Die Alias-Datei konnte nicht geladen werden.",
                path,
                exc,
            )
            return
        self.alias_path = path.resolve()
        self.settings.setValue('files/last_alias_path', str(self.alias_path))
        self.data = raw if isinstance(raw, dict) else {"signals": []}
        self.path_label.setText(str(self.alias_path))
        self.populate_table()
        self._update_statusbar_fields()
        self.statusBar().showMessage(f"Alias-Datei geladen: {self.alias_path}", 2500)

    def populate_table(self) -> None:
        rows = self.data.get("signals") if isinstance(self.data.get("signals"), list) else []
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                str(row.get("key", "")),
                str(row.get("unit", "")),
                str(row.get("short_name", "")),
                str(row.get("source", "")),
                str(row.get("category", "")),
                str(row.get("signal_family", "")),
                str(row.get("signal_kind", "")),
                str(row.get("default_name", "")),
                str(row.get("display_name", row.get("default_name", ""))),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col != 8:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_index, col, item)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)
        self.apply_filter()

    def apply_filter(self) -> None:
        needle = self.filter_edit.text().strip().lower()
        for row in range(self.table.rowCount()):
            text = " | ".join(
                (self.table.item(row, col).text() if self.table.item(row, col) else "")
                for col in range(self.table.columnCount())
            ).lower()
            self.table.setRowHidden(row, bool(needle) and needle not in text)
        self._update_statusbar_fields()

    def _collect_table(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for row in range(self.table.rowCount()):
            rows.append({
                "key": self.table.item(row, 0).text() if self.table.item(row, 0) else "",
                "unit": self.table.item(row, 1).text() if self.table.item(row, 1) else "",
                "short_name": self.table.item(row, 2).text() if self.table.item(row, 2) else "",
                "source": self.table.item(row, 3).text() if self.table.item(row, 3) else "",
                "category": self.table.item(row, 4).text() if self.table.item(row, 4) else "",
                "signal_family": self.table.item(row, 5).text() if self.table.item(row, 5) else "",
                "signal_kind": self.table.item(row, 6).text() if self.table.item(row, 6) else "",
                "default_name": self.table.item(row, 7).text() if self.table.item(row, 7) else "",
                "display_name": self.table.item(row, 8).text() if self.table.item(row, 8) else "",
            })
        return rows

    def save_file(self) -> None:
        self.data["signals"] = self._collect_table()
        try:
            self.alias_path.write_text(yaml.safe_dump(self.data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        except Exception as exc:
            self._show_file_error(
                "Alias-Datei speichern",
                "Die Alias-Datei konnte nicht gespeichert werden.",
                self.alias_path,
                exc,
            )
            return
        self._update_statusbar_fields()
        self.statusBar().showMessage(f"Alias-Datei gespeichert: {self.alias_path}", 3000)

    def closeEvent(self, event) -> None:
        self.save_layout_to_settings()
        self.settings.setValue('files/last_alias_path', str(self.alias_path))
        super().closeEvent(event)


def main(project_dir: str | Path, *, auto_generate_missing: bool = True) -> int:
    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QApplication([])
    assert app is not None
    app.setOrganizationName(APP_ORG)
    app.setApplicationName(APP_NAME)
    win = SignalAliasEditor(project_dir, auto_generate_missing=auto_generate_missing)
    show_foreground(win)
    if owns_app:
        return app.exec()
    return 0
