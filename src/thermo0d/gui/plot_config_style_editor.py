from __future__ import annotations

import argparse
import copy
import fnmatch
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml
from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QStyleFactory,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

APP_ORG = "Meta GmbH"
APP_NAME = "Thermo0D PlotConfigStyleEditor"
TEMPLATE_FORMAT = "thermo0d-line-style-templates-v1"
LINE_STYLES = {
    "Solid": "-",
    "Dashed": "--",
    "Dotted": ":",
    "Dash-dot": "-.",
    "None": "none",
}
LINE_WIDTHS = (0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.4, 3.0)
COLORS = {
    "Blue 100 · very light": "#DBEAFE",
    "Blue 300 · light": "#93C5FD",
    "Blue 500": "#3B82F6",
    "Blue 700 · dark": "#1D4ED8",
    "Blue 900 · very dark": "#1E3A8A",
    "Red 100 · very light": "#FEE2E2",
    "Red 300 · light": "#FCA5A5",
    "Red 500": "#EF4444",
    "Red 700 · dark": "#B91C1C",
    "Red 900 · very dark": "#7F1D1D",
    "Green 300 · light": "#86EFAC",
    "Green 700 · dark": "#15803D",
    "Orange": "#F97316",
    "Purple": "#7E22CE",
    "Teal": "#0F766E",
    "Gray 400": "#9CA3AF",
    "Gray 700": "#374151",
    "Black": "#111111",
}


def default_template_document() -> dict[str, Any]:
    return {
        "format": TEMPLATE_FORMAT,
        "templates": [
            {
                "name": "Engineering component hierarchy",
                "description": "Pressure blue, temperature red; component shades become progressively darker.",
                "rules": [
                    {"name": "All pressures", "pattern": r"(^|[_\s])p($|[_\s])|pressure|druck", "color": "#3B82F6", "priority": 10},
                    {"name": "Cylinder 1 pressure", "pattern": r"(cylinder|cyl)[_\s-]*1.*(pressure|p_)|p_.*(cylinder|cyl)[_\s-]*1", "color": "#93C5FD", "priority": 30},
                    {"name": "Compressor 1 pressure", "pattern": r"(compressor|comp)[_\s-]*1.*(pressure|p_)|p_.*(compressor|comp)[_\s-]*1", "color": "#DBEAFE", "priority": 40},
                    {"name": "Cylinder 2 pressure", "pattern": r"(cylinder|cyl)[_\s-]*2.*(pressure|p_)|p_.*(cylinder|cyl)[_\s-]*2", "color": "#1D4ED8", "priority": 30},
                    {"name": "Compressor 2 pressure", "pattern": r"(compressor|comp)[_\s-]*2.*(pressure|p_)|p_.*(compressor|comp)[_\s-]*2", "color": "#1E3A8A", "priority": 40},
                    {"name": "Transfer pressure", "pattern": r"transfer.*(pressure|p_)|p_.*transfer", "color": "#172554", "priority": 50},
                    {"name": "All temperatures", "pattern": r"temperature|temperatur|(^|_)t(_|$)", "color": "#EF4444", "priority": 10},
                    {"name": "Cylinder 1 temperature", "pattern": r"(cylinder|cyl)[_\s-]*1.*(temperature|t_)|t_.*(cylinder|cyl)[_\s-]*1", "color": "#FCA5A5", "priority": 30},
                    {"name": "Compressor 1 temperature", "pattern": r"(compressor|comp)[_\s-]*1.*(temperature|t_)|t_.*(compressor|comp)[_\s-]*1", "color": "#FEE2E2", "priority": 40},
                    {"name": "Cylinder 2 temperature", "pattern": r"(cylinder|cyl)[_\s-]*2.*(temperature|t_)|t_.*(cylinder|cyl)[_\s-]*2", "color": "#B91C1C", "priority": 30},
                    {"name": "Compressor 2 temperature", "pattern": r"(compressor|comp)[_\s-]*2.*(temperature|t_)|t_.*(compressor|comp)[_\s-]*2", "color": "#7F1D1D", "priority": 40},
                    {"name": "Mass flows", "pattern": r"mass.?flow|m_dot|mdot|massenstrom", "line_style": "-.", "priority": 20},
                    {"name": "Piston motion", "pattern": r"piston|kolben|stroke|hub|velocity|acceleration", "color": "#111111", "line_style": "--", "priority": 20},
                    {"name": "Geometry", "pattern": r"area|geometry|opening|slot|port|querschnitt|fläche|flaeche", "line_style": "--", "line_width": 1.0, "priority": 20},
                ],
            }
        ],
    }


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"{path}: YAML root must be a mapping.")
    return value


def save_yaml_mapping(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )


@dataclass
class SeriesRef:
    path: Path
    figure_index: int
    subplot_index: int
    series_index: int
    figure_title: str
    subplot_title: str
    series: dict[str, Any]

    @property
    def searchable_text(self) -> str:
        values = (
            self.series.get("signal_key", ""),
            self.series.get("label", ""),
            self.series.get("axis_id", ""),
            self.figure_title,
            self.subplot_title,
            self.path.stem,
        )
        return " ".join(str(value) for value in values).lower()


def iter_series(path: Path, document: dict[str, Any]) -> Iterable[SeriesRef]:
    figures = document.get("figures", [])
    if not isinstance(figures, list):
        return
    for figure_index, figure in enumerate(figures):
        if not isinstance(figure, dict):
            continue
        figure_title = str(figure.get("title", ""))
        subplots = figure.get("subplots", [])
        if not isinstance(subplots, list):
            continue
        for subplot_index, subplot in enumerate(subplots):
            if not isinstance(subplot, dict):
                continue
            subplot_title = str(subplot.get("title", ""))
            series_items = subplot.get("series", [])
            if not isinstance(series_items, list):
                continue
            for series_index, series in enumerate(series_items):
                if isinstance(series, dict):
                    yield SeriesRef(
                        path=path,
                        figure_index=figure_index,
                        subplot_index=subplot_index,
                        series_index=series_index,
                        figure_title=figure_title,
                        subplot_title=subplot_title,
                        series=series,
                    )


def validate_rule(rule: dict[str, Any]) -> None:
    pattern = str(rule.get("pattern", "")).strip()
    if not pattern:
        raise ValueError("A template rule needs a search pattern.")
    match_mode = str(rule.get("match_mode", "regex")).strip().lower()
    if match_mode not in {"contains", "wildcard", "regex"}:
        raise ValueError(f"Invalid match mode: {match_mode}")
    if match_mode == "regex":
        re.compile(pattern, re.IGNORECASE)
    color = str(rule.get("color", "")).strip()
    if color and not QColor(color).isValid():
        raise ValueError(f"Invalid color: {color}")
    style = str(rule.get("line_style", "")).strip()
    if style and style not in LINE_STYLES.values():
        raise ValueError(f"Invalid line style: {style}")
    if "line_width" in rule and rule["line_width"] not in ("", None):
        width = float(rule["line_width"])
        if not 0.0 < width <= 20.0:
            raise ValueError("Line width must be between 0 and 20.")


def rule_matches(rule: dict[str, Any], text: str) -> bool:
    pattern = str(rule.get("pattern", "")).strip()
    mode = str(rule.get("match_mode", "regex")).strip().lower()
    if mode == "contains":
        return pattern.lower() in text.lower()
    if mode == "wildcard":
        return fnmatch.fnmatch(text.lower(), pattern.lower())
    return re.search(pattern, text, re.IGNORECASE) is not None


def apply_rules(series_ref: SeriesRef, rules: list[dict[str, Any]]) -> list[str]:
    matches: list[tuple[int, int, dict[str, Any]]] = []
    for index, rule in enumerate(rules):
        validate_rule(rule)
        if rule_matches(rule, series_ref.searchable_text):
            matches.append((int(rule.get("priority", 0)), index, rule))
    changed: list[str] = []
    for _, _, rule in sorted(matches):
        for key in ("color", "line_style", "line_width"):
            value = rule.get(key)
            if value in ("", None):
                continue
            if key == "line_width":
                value = float(value)
            if series_ref.series.get(key) != value:
                series_ref.series[key] = value
                if key not in changed:
                    changed.append(key)
    return changed


class ColorComboBox(QComboBox):
    colorChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        for name, color in COLORS.items():
            pixmap = QPixmap(22, 14)
            pixmap.fill(QColor(color))
            self.addItem(pixmap, f"{name}  {color}", color)
        self.currentIndexChanged.connect(self._emit_color)
        self.lineEdit().editingFinished.connect(self._emit_color)

    def color(self) -> str:
        data = self.currentData()
        if data and self.currentText().endswith(str(data)):
            return str(data)
        match = re.search(r"#[0-9a-fA-F]{6}", self.currentText())
        return match.group(0).upper() if match else self.currentText().strip()

    def set_color(self, color: str) -> None:
        color = str(color or "#3B82F6").upper()
        for index in range(self.count()):
            if str(self.itemData(index)).upper() == color:
                self.setCurrentIndex(index)
                return
        self.setEditText(color)

    def _emit_color(self) -> None:
        color = self.color()
        if QColor(color).isValid():
            self.colorChanged.emit(color)


class RuleDialog(QDialog):
    def __init__(self, rule: dict[str, Any] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Line template rule")
        self.setMinimumWidth(520)
        rule = rule or {}
        form = QFormLayout(self)
        self.name_edit = QLineEdit(str(rule.get("name", "")))
        self.pattern_edit = QLineEdit(str(rule.get("pattern", "")))
        self.pattern_edit.setPlaceholderText("e.g. pressure, cylinder_1 or *mass_flow*")
        self.match_mode_combo = QComboBox()
        self.match_mode_combo.addItem("Contains text (recommended)", "contains")
        self.match_mode_combo.addItem("Wildcard (* and ?)", "wildcard")
        self.match_mode_combo.addItem("Regular expression (advanced)", "regex")
        mode = str(rule.get("match_mode", "regex" if rule else "contains"))
        self.match_mode_combo.setCurrentIndex(max(0, self.match_mode_combo.findData(mode)))
        self.color_combo = ColorComboBox()
        self.color_combo.set_color(str(rule.get("color", "#3B82F6")))
        self.use_color = QComboBox()
        self.use_color.addItems(["Set color", "Keep color"])
        self.use_color.setCurrentIndex(0 if rule.get("color") else 1)
        color_row = QWidget()
        color_layout = QHBoxLayout(color_row)
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.addWidget(self.use_color)
        color_layout.addWidget(self.color_combo, 1)
        self.style_combo = QComboBox()
        self.style_combo.addItem("Keep line style", "")
        for name, value in LINE_STYLES.items():
            self.style_combo.addItem(name, value)
        style_index = self.style_combo.findData(str(rule.get("line_style", "")))
        self.style_combo.setCurrentIndex(max(0, style_index))
        self.width_combo = QComboBox()
        self.width_combo.setEditable(True)
        self.width_combo.addItem("Keep line width", "")
        for width in LINE_WIDTHS:
            self.width_combo.addItem(f"{width:.1f} pt", width)
        if rule.get("line_width") not in ("", None):
            self.width_combo.setEditText(str(rule["line_width"]))
        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(-1000, 1000)
        self.priority_spin.setValue(int(rule.get("priority", 10)))
        form.addRow("Rule name", self.name_edit)
        form.addRow("Match method", self.match_mode_combo)
        form.addRow("Signal/label search", self.pattern_edit)
        form.addRow("Color", color_row)
        form.addRow("Line style", self.style_combo)
        form.addRow("Line width", self.width_combo)
        form.addRow("Priority", self.priority_spin)
        note = QLabel("All matching rules are applied. Higher priority values override lower values.")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def value(self) -> dict[str, Any]:
        rule: dict[str, Any] = {
            "name": self.name_edit.text().strip() or self.pattern_edit.text().strip(),
            "pattern": self.pattern_edit.text().strip(),
            "match_mode": self.match_mode_combo.currentData(),
            "priority": self.priority_spin.value(),
        }
        if self.use_color.currentIndex() == 0:
            rule["color"] = self.color_combo.color()
        style = self.style_combo.currentData()
        if style:
            rule["line_style"] = style
        width_text = self.width_combo.currentText().replace("pt", "").strip()
        if width_text and not width_text.lower().startswith("keep"):
            rule["line_width"] = float(width_text.replace(",", "."))
        validate_rule(rule)
        return rule

    def accept(self) -> None:
        try:
            self.value()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid rule", str(exc))
            return
        super().accept()


class PlotConfigStyleEditor(QMainWindow):
    COL_FILE = 0
    COL_FIGURE = 1
    COL_SUBPLOT = 2
    COL_SIGNAL = 3
    COL_LABEL = 4
    COL_COLOR = 5
    COL_STYLE = 6
    COL_WIDTH = 7

    def __init__(self, root: Path | str) -> None:
        super().__init__()
        self.root = Path(root).resolve()
        self.settings = QSettings(APP_ORG, APP_NAME)
        self.documents: dict[Path, dict[str, Any]] = {}
        self.refs: list[SeriesRef] = []
        self.dirty_paths: set[Path] = set()
        self.template_path = self.root / "plot_line_templates.yaml"
        self.template_document = self._load_templates()
        self.style_actions = QActionGroup(self)
        self.style_actions.setExclusive(True)
        self.setWindowTitle("Thermo0D Plot Config Style Editor")
        self.resize(1580, 900)
        self._build_actions()
        self._build_ui()
        self._populate_styles()
        self._apply_saved_style()
        self._restore_layout()
        self._update_template_combo()
        self.statusBar().showMessage("Open a plot configuration or a folder.", 4000)

    def _build_actions(self) -> None:
        self.open_files_action = QAction("Open files…", self)
        self.open_files_action.triggered.connect(self.open_files)
        self.open_folder_action = QAction("Open folder…", self)
        self.open_folder_action.triggered.connect(self.open_folder)
        self.save_action = QAction("Save changed", self)
        self.save_action.setShortcut("Ctrl+S")
        self.save_action.triggered.connect(self.save_changed)
        self.reload_action = QAction("Reload", self)
        self.reload_action.triggered.connect(self.reload)
        self.layout_save_action = QAction("Save layout", self)
        self.layout_save_action.triggered.connect(self._save_layout)
        self.layout_reset_action = QAction("Reset layout", self)
        self.layout_reset_action.triggered.connect(self._default_layout)
        self.advanced_action = QAction("Advanced templates", self)
        self.advanced_action.setCheckable(True)
        self.advanced_action.toggled.connect(self._toggle_advanced)

    def _build_ui(self) -> None:
        central = QWidget()
        central.hide()
        central.setMaximumSize(0, 0)
        self.setCentralWidget(central)
        file_menu = self.menuBar().addMenu("File")
        file_menu.addActions([self.open_files_action, self.open_folder_action, self.save_action, self.reload_action])
        view_menu = self.menuBar().addMenu("View")
        view_menu.addAction(self.advanced_action)
        layout_menu = self.menuBar().addMenu("Layout")
        layout_menu.addActions([self.layout_save_action, self.layout_reset_action])
        self.style_menu = self.menuBar().addMenu("Style")
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        toolbar.addActions([self.open_files_action, self.open_folder_action, self.save_action, self.reload_action])
        toolbar.addSeparator()
        toolbar.addAction(self.advanced_action)
        self.addToolBar(toolbar)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["File", "Figure", "Subplot", "Signal", "Label", "Color", "Line style", "Line width"])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_SIGNAL, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._table_item_changed)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table_dock = self._dock("Plot series", self.table)

        filter_widget = QWidget()
        filter_layout = QVBoxLayout(filter_widget)
        workflow = QGroupBox("Quick workflow")
        workflow_layout = QVBoxLayout(workflow)
        open_hint = QLabel("1. Open one or more plot YAML files.\n2. Select lines in the table.\n3. Choose a style below and apply it.")
        open_hint.setWordWrap(True)
        workflow_layout.addWidget(open_hint)
        open_buttons = QHBoxLayout()
        open_file_button = QPushButton("Open files")
        open_file_button.clicked.connect(self.open_files)
        open_folder_button = QPushButton("Open folder")
        open_folder_button.clicked.connect(self.open_folder)
        open_buttons.addWidget(open_file_button)
        open_buttons.addWidget(open_folder_button)
        workflow_layout.addLayout(open_buttons)
        filter_layout.addWidget(workflow)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by file, signal, label, figure or subplot…")
        self.filter_edit.textChanged.connect(self.populate_table)
        filter_layout.addWidget(QLabel("Series filter"))
        filter_layout.addWidget(self.filter_edit)
        selection_buttons = QHBoxLayout()
        select_visible_button = QPushButton("Select all visible")
        select_visible_button.clicked.connect(self.table_select_all_visible)
        clear_selection_button = QPushButton("Clear selection")
        clear_selection_button.clicked.connect(self.table.clearSelection)
        selection_buttons.addWidget(select_visible_button)
        selection_buttons.addWidget(clear_selection_button)
        filter_layout.addLayout(selection_buttons)

        automatic_group = QGroupBox("Automatic styling")
        automatic_layout = QVBoxLayout(automatic_group)
        automatic_layout.addWidget(QLabel("Choose a ready-made template:"))
        self.simple_template_combo = QComboBox()
        self.simple_template_combo.currentIndexChanged.connect(self._simple_template_changed)
        automatic_layout.addWidget(self.simple_template_combo)
        auto_selected_button = QPushButton("Apply to selected lines")
        auto_selected_button.clicked.connect(lambda: self.apply_template(selected_only=True))
        auto_all_button = QPushButton("Apply to all loaded lines")
        auto_all_button.clicked.connect(lambda: self.apply_template(selected_only=False))
        automatic_layout.addWidget(auto_selected_button)
        automatic_layout.addWidget(auto_all_button)
        advanced_hint = QLabel("Need your own matching rules? Enable “Advanced templates” in the toolbar.")
        advanced_hint.setWordWrap(True)
        automatic_layout.addWidget(advanced_hint)
        filter_layout.addWidget(automatic_group)

        selection_group = QGroupBox("Style selected lines")
        selection_form = QFormLayout(selection_group)
        self.selection_label = QLabel("No lines selected")
        self.batch_color_combo = ColorComboBox()
        self.batch_style_combo = QComboBox()
        self.batch_style_combo.addItem("Keep existing", "")
        for name, value in LINE_STYLES.items():
            self.batch_style_combo.addItem(name, value)
        self.batch_width_combo = QComboBox()
        self.batch_width_combo.setEditable(True)
        self.batch_width_combo.addItem("Keep existing", "")
        for width in LINE_WIDTHS:
            self.batch_width_combo.addItem(f"{width:.1f}", width)
        self.batch_use_color = QComboBox()
        self.batch_use_color.addItems(["Set selected color", "Keep existing color"])
        apply_batch_button = QPushButton("Apply style to selected lines")
        apply_batch_button.setToolTip("Changes only the rows currently selected in the series table.")
        apply_batch_button.clicked.connect(self.apply_batch_style)
        selection_form.addRow(self.selection_label)
        selection_form.addRow("Color action", self.batch_use_color)
        selection_form.addRow("Color", self.batch_color_combo)
        selection_form.addRow("Line style", self.batch_style_combo)
        selection_form.addRow("Line width", self.batch_width_combo)
        selection_form.addRow(apply_batch_button)
        filter_layout.addWidget(selection_group)
        filter_layout.addStretch(1)
        self.filter_dock = self._dock("Filter", filter_widget)

        template_widget = QWidget()
        template_layout = QVBoxLayout(template_widget)
        self.template_combo = QComboBox()
        self.rule_table = QTableWidget(0, 5)
        self.rule_table.setHorizontalHeaderLabels(["Rule", "Pattern", "Color", "Style", "Priority"])
        self.rule_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rule_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.rule_table.horizontalHeader().setStretchLastSection(True)
        self.rule_table.doubleClicked.connect(self.edit_rule)
        self.template_combo.currentIndexChanged.connect(self._populate_rule_table)
        self.template_combo.currentIndexChanged.connect(self._advanced_template_changed)
        template_layout.addWidget(QLabel("Template"))
        template_layout.addWidget(self.template_combo)
        template_layout.addWidget(self.rule_table, 1)
        buttons = QHBoxLayout()
        for text, callback in (
            ("New template", self.new_template),
            ("Add rule", self.add_rule),
            ("Edit", self.edit_rule),
            ("Delete", self.delete_rule),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        template_layout.addLayout(buttons)
        template_help = QLabel(
            "Templates assign styles automatically from signal names and labels. "
            "Use “Contains text” for simple rules; priorities resolve overlaps."
        )
        template_help.setWordWrap(True)
        template_layout.insertWidget(0, template_help)
        apply_selected = QPushButton("Preview/apply to selected lines")
        apply_selected.clicked.connect(lambda: self.apply_template(selected_only=True))
        apply_all = QPushButton("Preview/apply to all loaded lines")
        apply_all.clicked.connect(lambda: self.apply_template(selected_only=False))
        save_templates = QPushButton("Save templates")
        save_templates.clicked.connect(self.save_templates)
        template_layout.addWidget(apply_selected)
        template_layout.addWidget(apply_all)
        template_layout.addWidget(save_templates)
        self.template_dock = self._dock("Line templates", template_widget)

        self.addDockWidget(Qt.LeftDockWidgetArea, self.filter_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.template_dock)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.table_dock)
        self.resizeDocks([self.filter_dock, self.template_dock], [280, 520], Qt.Horizontal)
        self.resizeDocks([self.table_dock], [650], Qt.Vertical)
        for dock in (self.filter_dock, self.template_dock, self.table_dock):
            view_menu.addAction(dock.toggleViewAction())
        self.template_dock.visibilityChanged.connect(self.advanced_action.setChecked)
        self.template_dock.hide()
        status = QStatusBar(self)
        self.status_files = QLabel("0 files")
        self.status_series = QLabel("0 series")
        self.status_dirty = QLabel("0 changed")
        for label in (self.status_files, self.status_series, self.status_dirty):
            status.addPermanentWidget(label)
        self.setStatusBar(status)

    def _dock(self, title: str, widget: QWidget) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(title.replace(" ", "_"))
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        return dock

    def _load_templates(self) -> dict[str, Any]:
        if self.template_path.exists():
            try:
                data = load_yaml_mapping(self.template_path)
                if isinstance(data.get("templates"), list):
                    return data
            except Exception:
                pass
        return default_template_document()

    def save_templates(self) -> None:
        save_yaml_mapping(self.template_path, self.template_document)
        self.statusBar().showMessage(f"Templates saved: {self.template_path}", 3500)

    def _update_template_combo(self) -> None:
        current = self.template_combo.currentText() if hasattr(self, "template_combo") else ""
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        for template in self.template_document.get("templates", []):
            self.template_combo.addItem(str(template.get("name", "Unnamed")))
        index = self.template_combo.findText(current)
        self.template_combo.setCurrentIndex(max(0, index))
        self.template_combo.blockSignals(False)
        if hasattr(self, "simple_template_combo"):
            self.simple_template_combo.blockSignals(True)
            self.simple_template_combo.clear()
            for template in self.template_document.get("templates", []):
                self.simple_template_combo.addItem(str(template.get("name", "Unnamed")))
            self.simple_template_combo.setCurrentIndex(self.template_combo.currentIndex())
            self.simple_template_combo.blockSignals(False)
        self._populate_rule_table()

    def _simple_template_changed(self, index: int) -> None:
        if self.template_combo.currentIndex() != index:
            self.template_combo.setCurrentIndex(index)

    def _advanced_template_changed(self, index: int) -> None:
        if hasattr(self, "simple_template_combo") and self.simple_template_combo.currentIndex() != index:
            self.simple_template_combo.setCurrentIndex(index)

    def _current_template(self) -> dict[str, Any] | None:
        templates = self.template_document.get("templates", [])
        index = self.template_combo.currentIndex()
        return templates[index] if isinstance(templates, list) and 0 <= index < len(templates) else None

    def _populate_rule_table(self) -> None:
        template = self._current_template() or {}
        rules = template.get("rules", [])
        self.rule_table.setRowCount(0)
        for rule in rules:
            row = self.rule_table.rowCount()
            self.rule_table.insertRow(row)
            values = (
                rule.get("name", ""),
                rule.get("pattern", ""),
                rule.get("color", "keep"),
                rule.get("line_style", "keep"),
                rule.get("priority", 0),
            )
            for column, value in enumerate(values):
                self.rule_table.setItem(row, column, QTableWidgetItem(str(value)))

    def new_template(self) -> None:
        name, ok = self._text_dialog("New template", "Template name")
        if not ok or not name.strip():
            return
        self.template_document.setdefault("templates", []).append({"name": name.strip(), "rules": []})
        self._update_template_combo()
        self.template_combo.setCurrentIndex(self.template_combo.count() - 1)

    def _text_dialog(self, title: str, label: str) -> tuple[str, bool]:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QFormLayout(dialog)
        edit = QLineEdit()
        layout.addRow(label, edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        accepted = dialog.exec() == QDialog.Accepted
        return edit.text(), accepted

    def add_rule(self) -> None:
        template = self._current_template()
        if template is None:
            return
        dialog = RuleDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            template.setdefault("rules", []).append(dialog.value())
            self._populate_rule_table()

    def edit_rule(self) -> None:
        template = self._current_template()
        row = self.rule_table.currentRow()
        if template is None or row < 0:
            return
        rules = template.setdefault("rules", [])
        dialog = RuleDialog(copy.deepcopy(rules[row]), self)
        if dialog.exec() == QDialog.Accepted:
            rules[row] = dialog.value()
            self._populate_rule_table()

    def delete_rule(self) -> None:
        template = self._current_template()
        row = self.rule_table.currentRow()
        if template is not None and row >= 0:
            del template.setdefault("rules", [])[row]
            self._populate_rule_table()

    def open_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Open plot configs", str(self.root), "YAML (*.yaml *.yml)")
        self.load_paths(Path(path) for path in paths)

    def open_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open plot config folder", str(self.root))
        if folder:
            self.load_paths(sorted([*Path(folder).rglob("*.yaml"), *Path(folder).rglob("*.yml")]))

    def load_paths(self, paths: Iterable[Path]) -> None:
        failures: list[str] = []
        for path in paths:
            path = path.resolve()
            try:
                document = load_yaml_mapping(path)
                if document.get("figures") is not None:
                    self.documents[path] = document
            except Exception as exc:
                failures.append(f"{path.name}: {exc}")
        self._rebuild_refs()
        if failures:
            QMessageBox.warning(self, "Some files were skipped", "\n".join(failures[:15]))

    def _rebuild_refs(self) -> None:
        self.refs = [ref for path, document in sorted(self.documents.items()) for ref in iter_series(path, document)]
        self.populate_table()
        self._update_status()

    def populate_table(self) -> None:
        if not hasattr(self, "table"):
            return
        needle = self.filter_edit.text().strip().lower()
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for ref_index, ref in enumerate(self.refs):
            if needle and needle not in ref.searchable_text:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = (
                str(ref.path.relative_to(self.root) if ref.path.is_relative_to(self.root) else ref.path),
                ref.figure_title,
                ref.subplot_title,
                ref.series.get("signal_key", ""),
                ref.series.get("label", ""),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, ref_index)
                if column < self.COL_LABEL:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, column, item)
            color_combo = ColorComboBox()
            color_combo.set_color(str(ref.series.get("color", "#3B82F6")))
            color_combo.colorChanged.connect(lambda value, idx=ref_index: self._set_series_value(idx, "color", value))
            self.table.setCellWidget(row, self.COL_COLOR, color_combo)
            style_combo = QComboBox()
            for name, value in LINE_STYLES.items():
                style_combo.addItem(name, value)
            style_combo.setCurrentIndex(max(0, style_combo.findData(str(ref.series.get("line_style", "-")))))
            style_combo.currentIndexChanged.connect(
                lambda _value, combo=style_combo, idx=ref_index: self._set_series_value(idx, "line_style", combo.currentData())
            )
            self.table.setCellWidget(row, self.COL_STYLE, style_combo)
            width_combo = QComboBox()
            width_combo.setEditable(True)
            for width in LINE_WIDTHS:
                width_combo.addItem(f"{width:.1f}", width)
            width_combo.setEditText(str(ref.series.get("line_width", 1.6)))
            width_combo.currentTextChanged.connect(lambda value, idx=ref_index: self._set_width(idx, value))
            self.table.setCellWidget(row, self.COL_WIDTH, width_combo)
        self.table.blockSignals(False)
        self.status_series.setText(f"{self.table.rowCount()} / {len(self.refs)} series")

    def _set_width(self, ref_index: int, value: str) -> None:
        try:
            width = float(value.replace(",", "."))
        except ValueError:
            return
        if 0.0 < width <= 20.0:
            self._set_series_value(ref_index, "line_width", width)

    def _set_series_value(self, ref_index: int, key: str, value: Any) -> None:
        ref = self.refs[ref_index]
        if ref.series.get(key) != value:
            ref.series[key] = value
            self.dirty_paths.add(ref.path)
            self._update_status()

    def _table_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != self.COL_LABEL:
            return
        ref_index = int(item.data(Qt.UserRole))
        self._set_series_value(ref_index, "label", item.text())

    def apply_template(self, *, selected_only: bool) -> None:
        template = self._current_template()
        if template is None:
            return
        rules = template.get("rules", [])
        selected_indices: set[int] | None = None
        if selected_only:
            selected_indices = {
                int(self.table.item(index.row(), self.COL_FILE).data(Qt.UserRole))
                for index in self.table.selectionModel().selectedRows()
            }
            if not selected_indices:
                QMessageBox.information(self, "Apply template", "Select one or more series rows first.")
                return
        candidates = [
            (index, ref)
            for index, ref in enumerate(self.refs)
            if selected_indices is None or index in selected_indices
        ]
        matching = [
            (index, ref)
            for index, ref in candidates
            if any(rule_matches(rule, ref.searchable_text) for rule in rules)
        ]
        answer = QMessageBox.question(
            self,
            "Apply line template",
            f'Template “{template.get("name", "Unnamed")}” matches '
            f"{len(matching)} of {len(candidates)} lines.\n\nApply these style changes?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        changed_series = 0
        for index, ref in matching:
            if apply_rules(ref, rules):
                self.dirty_paths.add(ref.path)
                changed_series += 1
        self.populate_table()
        self._update_status()
        self.statusBar().showMessage(f"Template changed {changed_series} series.", 4000)

    def _selected_ref_indices(self) -> set[int]:
        return {
            int(self.table.item(index.row(), self.COL_FILE).data(Qt.UserRole))
            for index in self.table.selectionModel().selectedRows()
        }

    def _selection_changed(self) -> None:
        count = len(self._selected_ref_indices())
        self.selection_label.setText(f"{count} line{'s' if count != 1 else ''} selected")

    def table_select_all_visible(self) -> None:
        self.table.selectAll()
        self._selection_changed()

    def apply_batch_style(self) -> None:
        indices = self._selected_ref_indices()
        if not indices:
            QMessageBox.information(self, "Style selected lines", "Select one or more rows in the series table first.")
            return
        style = self.batch_style_combo.currentData()
        width_text = self.batch_width_combo.currentText().strip()
        width: float | None = None
        if width_text and not width_text.lower().startswith("keep"):
            try:
                width = float(width_text.replace(",", "."))
            except ValueError:
                QMessageBox.warning(self, "Invalid line width", "Enter a numeric line width, for example 1.6.")
                return
        for index in indices:
            if self.batch_use_color.currentIndex() == 0:
                self._set_series_value(index, "color", self.batch_color_combo.color())
            if style:
                self._set_series_value(index, "line_style", style)
            if width is not None:
                self._set_series_value(index, "line_width", width)
        self.populate_table()
        self.statusBar().showMessage(f"Style applied to {len(indices)} selected lines.", 3500)

    def save_changed(self) -> None:
        for path in sorted(self.dirty_paths):
            save_yaml_mapping(path, self.documents[path])
        count = len(self.dirty_paths)
        self.dirty_paths.clear()
        self._update_status()
        self.statusBar().showMessage(f"Saved {count} plot configuration files.", 4000)

    def reload(self) -> None:
        paths = list(self.documents)
        if self.dirty_paths:
            answer = QMessageBox.question(self, "Discard changes?", "Reloading discards unsaved style changes.")
            if answer != QMessageBox.Yes:
                return
        self.documents.clear()
        self.dirty_paths.clear()
        self.load_paths(paths)

    def _update_status(self) -> None:
        self.status_files.setText(f"{len(self.documents)} files")
        self.status_series.setText(f"{self.table.rowCount()} / {len(self.refs)} series")
        self.status_dirty.setText(f"{len(self.dirty_paths)} changed")

    def _populate_styles(self) -> None:
        for name in QStyleFactory.keys():
            action = QAction(name, self, checkable=True)
            action.setData(name)
            action.triggered.connect(lambda _checked=False, style=name: self._apply_style(style))
            self.style_actions.addAction(action)
            self.style_menu.addAction(action)

    def _apply_saved_style(self) -> None:
        self._apply_style(str(self.settings.value("style", "Fusion")))

    def _apply_style(self, name: str) -> None:
        style = QStyleFactory.create(name)
        if style is not None:
            QApplication.setStyle(style)
            self.settings.setValue("style", name)
            for action in self.style_actions.actions():
                action.setChecked(action.data() == name)

    def _save_layout(self) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("window_state", self.saveState())

    def _restore_layout(self) -> None:
        geometry = self.settings.value("geometry")
        state = self.settings.value("window_state")
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state)

    def _default_layout(self) -> None:
        self.removeDockWidget(self.filter_dock)
        self.removeDockWidget(self.template_dock)
        self.removeDockWidget(self.table_dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.filter_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.template_dock)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.table_dock)
        for dock in (self.filter_dock, self.template_dock, self.table_dock):
            dock.show()
        self.template_dock.hide()
        self.advanced_action.setChecked(False)

    def _toggle_advanced(self, visible: bool) -> None:
        self.template_dock.setVisible(visible)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.dirty_paths:
            answer = QMessageBox.question(self, "Unsaved changes", "Save changed plot configurations before closing?", QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if answer == QMessageBox.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.Yes:
                self.save_changed()
        self._save_layout()
        event.accept()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Edit line styles in thermo0d plot YAML configurations.")
    parser.add_argument("--root", default="Projekte", help="Project root used for templates and relative paths.")
    parser.add_argument("paths", nargs="*", help="Plot YAML files or folders to open.")
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv)
    editor = PlotConfigStyleEditor(Path(args.root))
    paths: list[Path] = []
    for raw_path in args.paths:
        path = Path(raw_path)
        if path.is_dir():
            paths.extend(sorted([*path.rglob("*.yaml"), *path.rglob("*.yml")]))
        elif path.exists():
            paths.append(path)
    if paths:
        editor.load_paths(paths)
    else:
        preferred_folders = (
            Path(args.root) / "variants" / "plot_v40",
            Path(args.root) / "variants" / "plot_cycle",
            Path(args.root) / "plot_configs",
        )
        default_folder = next((folder for folder in preferred_folders if folder.exists()), None)
        if default_folder is not None:
            editor.load_paths(sorted([*default_folder.rglob("*.yaml"), *default_folder.rglob("*.yml")]))
            editor.statusBar().showMessage(
                f"Automatically opened {default_folder}. Choose another folder with “Open folder”.",
                6000,
            )
    editor.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
