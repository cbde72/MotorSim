from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import yaml
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QApplication,
    QDockWidget,
    QFrame,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
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

from .dialogs import exec_dialog, get_open_file_name, get_save_file_name, show_foreground, show_warning
from .signal_alias_export import (
    DEFAULT_SIGNAL_EXPORT_NAME,
    allowed_target_units,
    export_signal_layout_csv,
    normalize_target_unit,
)
from .signal_catalog import DEFAULT_SIGNAL_ALIAS_NAME, generate_signal_alias_file

APP_ORG = "OpenAI"
APP_NAME = "Thermo0DSignalAliasEditor"


class SignalAliasEditor(QMainWindow):
    def __init__(self, project_dir: Path | str, *, auto_generate_missing: bool = True) -> None:
        super().__init__()
        self.settings = QSettings(APP_ORG, APP_NAME)
        self.project_dir = Path(project_dir).resolve()
        self.alias_path = self.project_dir / DEFAULT_SIGNAL_ALIAS_NAME
        self.export_path = self.project_dir / DEFAULT_SIGNAL_EXPORT_NAME
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
        last_export = self._last_export_path()
        if last_export is not None:
            self.export_path = last_export
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
        self.act_export = QAction("Export-Datei schreiben", self)
        self.act_export.triggered.connect(self.export_file)
        self.act_layout_save = QAction("Layout speichern", self)
        self.act_layout_save.triggered.connect(self.save_layout_to_settings)
        self.act_layout_reset = QAction("Layout zurücksetzen", self)
        self.act_layout_reset.triggered.connect(self.reset_layout)
        self.act_quit = QAction("Beenden", self)
        self.act_quit.triggered.connect(self.close)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("Datei")
        for action in [self.act_open, self.act_save, self.act_regen, self.act_export]:
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
        for action in [self.act_open, self.act_save, self.act_regen, self.act_export]:
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
        self.status_export = QLabel()
        for label in [self.status_project, self.status_alias, self.status_rows, self.status_export]:
            label.setFrameStyle(QFrame.Panel | QFrame.Sunken)
            label.setContentsMargins(6, 0, 6, 0)
            status.addPermanentWidget(label)

    def _build_docks(self) -> None:
        self.controls_panel = self._build_controls_panel()
        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels(["Export", "Signal", "Einheit", "Zieleinheit", "Kürzel", "Quelle", "Kategorie", "Familie", "Typ", "Vorschlag", "Benutzername"])
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)
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
        self.family_filter_combo = QComboBox()
        self.family_filter_combo.setMinimumWidth(160)
        self.family_filter_combo.currentTextChanged.connect(self.apply_filter)
        save_btn = QPushButton("Speichern")
        save_btn.clicked.connect(self.save_file)
        export_btn = QPushButton("Export-Datei")
        export_btn.clicked.connect(self.export_file)
        top.addWidget(QLabel("Datei:"))
        top.addWidget(self.path_label, 1)
        top.addWidget(QLabel("Filter:"))
        top.addWidget(self.filter_edit, 1)
        top.addWidget(QLabel("Familie:"))
        top.addWidget(self.family_filter_combo)
        top.addWidget(save_btn)
        top.addWidget(export_btn)
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
        selected_rows = sum(1 for row in range(self.table.rowCount()) if self._row_export_enabled(row))
        self.status_rows.setText(f"Zeilen: {visible_rows}/{self.table.rowCount()} | Export: {selected_rows}")
        self.status_export.setText(f"Export-Datei: {self.export_path}")

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
            export_box = QCheckBox()
            export_box.setChecked(bool(row.get("export_enabled", False)))
            export_box.stateChanged.connect(self._update_statusbar_fields)
            export_host = QWidget()
            export_layout = QHBoxLayout(export_host)
            export_layout.setContentsMargins(0, 0, 0, 0)
            export_layout.setAlignment(Qt.AlignCenter)
            export_layout.addWidget(export_box)
            self.table.setCellWidget(row_index, 0, export_host)

            source_unit = str(row.get("unit", ""))
            target_combo = QComboBox()
            target_combo.addItems(allowed_target_units(source_unit))
            target_combo.setEditable(False)
            target_combo.setCurrentText(normalize_target_unit(source_unit, str(row.get("target_unit", ""))))
            target_combo.currentTextChanged.connect(self._update_statusbar_fields)
            self.table.setCellWidget(row_index, 3, target_combo)

            values = [
                str(row.get("key", "")),
                source_unit,
                str(row.get("short_name", "")),
                str(row.get("source", "")),
                str(row.get("category", "")),
                str(row.get("signal_family", "")),
                str(row.get("signal_kind", "")),
                str(row.get("default_name", "")),
                str(row.get("display_name", row.get("default_name", ""))),
            ]
            table_cols = [1, 2, 4, 5, 6, 7, 8, 9, 10]
            for col, value in zip(table_cols, values):
                item = QTableWidgetItem(value)
                if col != 10:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_index, col, item)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)
        self._refresh_family_filter_options()
        self.apply_filter()

    def apply_filter(self) -> None:
        needle = self.filter_edit.text().strip().lower()
        family_filter = self.family_filter_combo.currentData() if hasattr(self, 'family_filter_combo') else None
        family_filter = str(family_filter or "").strip()
        searchable_columns = [1, 2, 4, 5, 6, 7, 8, 9, 10]
        for row in range(self.table.rowCount()):
            row_text = " | ".join(
                (self.table.item(row, col).text() if self.table.item(row, col) else "")
                for col in searchable_columns
            ).lower()
            row_family = self.table.item(row, 7).text().strip() if self.table.item(row, 7) else ""
            text_hidden = bool(needle) and needle not in row_text
            family_hidden = bool(family_filter) and row_family != family_filter
            self.table.setRowHidden(row, text_hidden or family_hidden)
        self._update_statusbar_fields()

    def _refresh_family_filter_options(self) -> None:
        if not hasattr(self, 'family_filter_combo'):
            return
        current = str(self.family_filter_combo.currentData() or "")
        families = sorted({
            self.table.item(row, 7).text().strip()
            for row in range(self.table.rowCount())
            if self.table.item(row, 7) and self.table.item(row, 7).text().strip()
        }, key=str.lower)
        self.family_filter_combo.blockSignals(True)
        self.family_filter_combo.clear()
        self.family_filter_combo.addItem("Alle Familien", "")
        for family in families:
            self.family_filter_combo.addItem(family, family)
        idx = self.family_filter_combo.findData(current)
        self.family_filter_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.family_filter_combo.blockSignals(False)

    def _row_export_widget(self, row: int) -> QCheckBox | None:
        host = self.table.cellWidget(row, 0)
        if host is None:
            return None
        return host.findChild(QCheckBox)

    def _row_target_unit_widget(self, row: int) -> QComboBox | None:
        widget = self.table.cellWidget(row, 3)
        return widget if isinstance(widget, QComboBox) else None

    def _row_export_enabled(self, row: int) -> bool:
        widget = self._row_export_widget(row)
        return bool(widget.isChecked()) if widget is not None else False

    def _set_row_export_enabled(self, row: int, enabled: bool = True) -> None:
        widget = self._row_export_widget(row)
        if widget is not None:
            widget.setChecked(bool(enabled))

    def _row_key(self, row: int) -> str:
        item = self.table.item(row, 1)
        return item.text().strip() if item is not None else ""

    @staticmethod
    def _component_parts_from_key(key: str) -> tuple[str, str, str] | None:
        match = re.match(r"^(.+)_(\d+)_(.+)$", str(key).strip())
        if not match:
            return None
        component_type = match.group(1)
        component = f"{component_type}_{match.group(2)}"
        suffix = match.group(3)
        return component_type, component, suffix

    def _selected_table_rows(self) -> list[int]:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if rows:
            return rows
        return sorted({item.row() for item in self.table.selectedItems()})

    def _transfer_index(self) -> dict[str, dict[str, dict[str, int]]]:
        index: dict[str, dict[str, dict[str, int]]] = {}
        for row in range(self.table.rowCount()):
            parts = self._component_parts_from_key(self._row_key(row))
            if parts is None:
                continue
            component_type, component, suffix = parts
            index.setdefault(component_type, {}).setdefault(component, {})[suffix] = row
        return index

    def _show_table_context_menu(self, pos) -> None:
        clicked_index = self.table.indexAt(pos)
        if clicked_index.isValid():
            clicked_row = clicked_index.row()
            if clicked_row not in self._selected_table_rows():
                self.table.selectRow(clicked_row)

        selected_rows = [row for row in self._selected_table_rows() if not self.table.isRowHidden(row)]
        menu = QMenu(self)

        export_selected = QAction("Ausgewählte Signale für Export markieren", self)
        export_selected.setEnabled(bool(selected_rows))
        export_selected.triggered.connect(lambda: self._mark_rows_for_export(selected_rows))
        menu.addAction(export_selected)

        clear_selected = QAction("Export-Markierung für Auswahl entfernen", self)
        clear_selected.setEnabled(bool(selected_rows))
        clear_selected.triggered.connect(lambda: self._mark_rows_for_export(selected_rows, enabled=False))
        menu.addAction(clear_selected)
        menu.addSeparator()

        self._add_component_transfer_actions(menu, selected_rows)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _mark_rows_for_export(self, rows: list[int], *, enabled: bool = True) -> None:
        for row in rows:
            self._set_row_export_enabled(row, enabled)
        self._update_statusbar_fields()

    def _add_component_transfer_actions(self, menu: QMenu, selected_rows: list[int]) -> None:
        transfer_rows: list[tuple[int, str, str, str]] = []
        for row in selected_rows:
            parts = self._component_parts_from_key(self._row_key(row))
            if parts is None:
                continue
            component_type, component, suffix = parts
            transfer_rows.append((row, component_type, component, suffix))

        if not transfer_rows:
            action = QAction("Auf anderes Bauteil übertragen: keine Bauteil-Signale ausgewählt", self)
            action.setEnabled(False)
            menu.addAction(action)
            return

        source_components = {(component_type, component) for _, component_type, component, _ in transfer_rows}
        if len(source_components) != 1:
            action = QAction("Auf anderes Bauteil übertragen: bitte nur ein Quellbauteil auswählen", self)
            action.setEnabled(False)
            menu.addAction(action)
            return

        component_type, source_component = next(iter(source_components))
        suffixes = [suffix for _, _, _, suffix in transfer_rows]
        transfer_index = self._transfer_index()
        candidates = []
        for target_component, suffix_index in transfer_index.get(component_type, {}).items():
            if target_component == source_component:
                continue
            target_rows = [suffix_index[suffix] for suffix in suffixes if suffix in suffix_index]
            if target_rows:
                candidates.append((target_component, target_rows, len(target_rows), len(suffixes)))

        if not candidates:
            action = QAction(f"Keine passenden {component_type}-Zielbauteile gefunden", self)
            action.setEnabled(False)
            menu.addAction(action)
            return

        transfer_menu = menu.addMenu(f"Export-Auswahl auf anderes {component_type}-Bauteil übertragen")
        for target_component, target_rows, matched, total in sorted(candidates, key=lambda item: item[0]):
            label = f"{target_component} markieren"
            if matched != total:
                label += f" ({matched}/{total} passende Signale)"
            else:
                label += f" ({matched} Signale)"
            action = QAction(label, self)
            rows_to_mark = list(dict.fromkeys(selected_rows + target_rows))
            action.triggered.connect(
                lambda checked=False, rows=rows_to_mark, target=list(target_rows), name=target_component: self._mark_component_transfer(rows, target, name)
            )
            transfer_menu.addAction(action)

    def _mark_component_transfer(self, rows: list[int], target_rows: list[int], target_component: str) -> None:
        self._mark_rows_for_export(rows, enabled=True)
        self.statusBar().showMessage(f"Export-Auswahl auf {target_component} übertragen: {len(target_rows)} Signale markiert", 3500)

    def _collect_table(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in range(self.table.rowCount()):
            source_unit = self.table.item(row, 2).text() if self.table.item(row, 2) else ""
            target_combo = self._row_target_unit_widget(row)
            target_unit = normalize_target_unit(source_unit, target_combo.currentText() if target_combo is not None else source_unit)
            rows.append({
                "export_enabled": self._row_export_enabled(row),
                "key": self.table.item(row, 1).text() if self.table.item(row, 1) else "",
                "unit": source_unit,
                "target_unit": target_unit,
                "short_name": self.table.item(row, 4).text() if self.table.item(row, 4) else "",
                "source": self.table.item(row, 5).text() if self.table.item(row, 5) else "",
                "category": self.table.item(row, 6).text() if self.table.item(row, 6) else "",
                "signal_family": self.table.item(row, 7).text() if self.table.item(row, 7) else "",
                "signal_kind": self.table.item(row, 8).text() if self.table.item(row, 8) else "",
                "default_name": self.table.item(row, 9).text() if self.table.item(row, 9) else "",
                "display_name": self.table.item(row, 10).text() if self.table.item(row, 10) else "",
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

    def export_file(self) -> None:
        rows = self._collect_table()
        selected = [row for row in rows if row.get("export_enabled")]
        if not selected:
            show_warning(self, "Signal-Export", "Es ist kein Signal zum Export ausgewählt.")
            return
        suggested_path = self._last_export_path() or self.export_path
        path, _ = get_save_file_name(self, "Signal-Export-Datei schreiben", str(suggested_path), "CSV (*.csv)")
        if not path:
            return
        export_path = Path(path)
        if export_path.suffix.lower() != ".csv":
            export_path = export_path.with_suffix('.csv')
        try:
            self.data["signals"] = rows
            self.alias_path.write_text(yaml.safe_dump(self.data, sort_keys=False, allow_unicode=True), encoding="utf-8")
            export_signal_layout_csv(rows, export_path)
        except Exception as exc:
            self._show_file_error(
                "Signal-Export",
                "Die Signal-Export-Datei konnte nicht geschrieben werden.",
                export_path,
                exc,
            )
            return
        self.export_path = export_path.resolve()
        self.settings.setValue('files/last_export_path', str(self.export_path))
        self._update_statusbar_fields()
        self.statusBar().showMessage(f"Signal-Export-Datei geschrieben: {self.export_path}", 3000)

    def _last_export_path(self) -> Path | None:
        text = str(self.settings.value('files/last_export_path', '') or '').strip()
        if not text:
            return None
        return Path(text).expanduser().resolve()

    def closeEvent(self, event) -> None:
        self.save_layout_to_settings()
        self.settings.setValue('files/last_alias_path', str(self.alias_path))
        self.settings.setValue('files/last_export_path', str(self.export_path))
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
