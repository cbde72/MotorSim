from __future__ import annotations

import sys
from pathlib import Path
from typing import List

from PySide6.QtCore import QByteArray, QFileSystemWatcher, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QFrame,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
APP_ORG = "OpenAI"
APP_NAME = "EngineSimImageViewer"
LAYOUT_STATE_VERSION = 3

DEFAULT_INITIAL_PATH = (
    r"C:\Users\chris\Desktop\programming\EngineSim\0_MotorSim_V03_V07"
    r"\Projekte\results\sweeps\Vibe_dura_01\plots"
)


def _settings_bool(settings: QSettings, key: str, default: bool = False) -> bool:
    value = settings.value(key, default, bool)
    return bool(value)


def _settings_str(settings: QSettings, key: str, default: str = "") -> str:
    value = settings.value(key, default, str)
    return str(value) if value is not None else default


def _settings_int_or_none(settings: QSettings, key: str) -> int | None:
    value = settings.value(key, None)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class ImageLabel(QLabel):
    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: black; color: white;")
        self.setText("Keine Bilder geladen")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(240, 180)
        self._pixmap_original: QPixmap | None = None

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self._pixmap_original = pixmap
        self._refresh_scaled_pixmap()

    def clear_pixmap(self) -> None:
        self._pixmap_original = None
        super().setPixmap(QPixmap())

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._refresh_scaled_pixmap()

    def _refresh_scaled_pixmap(self) -> None:
        if self._pixmap_original is None or self._pixmap_original.isNull():
            return
        target = self.size()
        if target.width() < 10 or target.height() < 10:
            return
        scaled = self._pixmap_original.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        super().setPixmap(scaled)


class ImagePane(QFrame):
    activated = Signal(str)

    def __init__(self, side_key: str, settings: QSettings, initial_path: str | None = None) -> None:
        super().__init__()
        self.side_key = side_key
        self.side_name = "Links" if side_key == "left" else "Rechts"
        self.settings = settings
        self.folder_path: Path | None = None
        self.image_files: List[Path] = []
        self.current_index = 0

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setLineWidth(2)
        self.setObjectName(f"imagePane_{side_key}")
        self.setMinimumSize(280, 220)

        self.header_label = QLabel(f"{self.side_name}: Kein Ordner")
        self.header_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.header_label.setWordWrap(True)

        self.info_label = QLabel("0 / 0")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.image_label = ImageLabel()
        self.image_label.clicked.connect(self.activate)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addWidget(self.header_label)
        layout.addWidget(self.info_label)
        layout.addWidget(self.image_label, 1)

        self._dir_watcher = QFileSystemWatcher(self)
        self._dir_watcher.directoryChanged.connect(self._schedule_refresh)
        self._dir_watcher.fileChanged.connect(self._schedule_refresh)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(250)
        self._refresh_timer.timeout.connect(self._refresh_current_folder)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1200)
        self._poll_timer.timeout.connect(self._refresh_current_folder)
        self._poll_timer.start()

        start_folder = self._resolve_start_folder(initial_path)
        if start_folder is not None:
            self.open_folder(start_folder)
        else:
            self._show_no_images("Keine Bilder geladen")

        self.set_active(False)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.activate()
        super().mousePressEvent(event)

    def activate(self) -> None:
        self.activated.emit(self.side_key)

    def set_active(self, active: bool) -> None:
        border = "#2a82da" if active else "#666666"
        self.setStyleSheet(
            f"QFrame#{self.objectName()} {{ border: 2px solid {border}; border-radius: 4px; }}"
            "QLabel { border: none; color: palette(windowText); }"
        )

    def _resolve_start_folder(self, initial_path: str | None) -> Path | None:
        last_folder = _settings_str(self.settings, f"last_folder_{self.side_key}")
        candidates = [last_folder, initial_path or "", DEFAULT_INITIAL_PATH if self.side_key == "left" else ""]
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            if path.exists() and path.is_dir():
                return path
        return None

    def choose_folder(self, parent: QWidget | None = None) -> bool:
        start_dir = str(self.folder_path) if self.folder_path else str(Path.home())
        selected = QFileDialog.getExistingDirectory(parent, f"{self.side_name} Bilderordner auswählen", start_dir)
        if not selected:
            return False
        return self.open_folder(Path(selected), parent=parent)

    def open_folder(self, folder: Path, parent: QWidget | None = None) -> bool:
        if not folder.exists() or not folder.is_dir():
            QMessageBox.warning(parent or self, "Ungültiger Ordner", f"Ordner nicht gefunden:\n{folder}")
            return False

        self.folder_path = folder
        self.settings.setValue(f"last_folder_{self.side_key}", str(folder))
        self.current_index = 0
        self._refresh_file_list(reset_index=True)
        self._update_watcher_paths()
        self._load_current_image()
        return True

    def navigate(self, direction: int) -> None:
        if not self.image_files:
            return
        self.current_index = (self.current_index + direction) % len(self.image_files)
        self._load_current_image()

    def current_title(self) -> str:
        if not self.image_files:
            return f"{self.side_name}: Keine Bilder"
        img_path = self.image_files[self.current_index]
        return f"{self.side_name} [{self.current_index + 1}/{len(self.image_files)}] {img_path.name}"

    def current_status_text(self) -> str:
        if self.folder_path is None:
            return f"{self.side_name}: Kein Ordner"
        if not self.image_files:
            return f"{self.side_name}: Keine Bilder in {self.folder_path}"
        img_path = self.image_files[self.current_index]
        return f"{self.side_name}: {img_path}"

    def _show_no_images(self, message: str) -> None:
        self.image_label.clear_pixmap()
        self.image_label.setText(message)
        self.header_label.setText(f"{self.side_name}: {self.folder_path if self.folder_path else 'Kein Ordner'}")
        self.info_label.setText("0 / 0")

    def _get_images(self) -> List[Path]:
        if self.folder_path is None:
            return []
        files = [
            p for p in self.folder_path.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
        ]
        return sorted(files, key=lambda p: p.name.lower())

    def _refresh_file_list(self, reset_index: bool = False) -> None:
        if self.image_files and not reset_index:
            self.current_index = max(0, min(self.current_index, len(self.image_files) - 1))
            old_current = self.image_files[self.current_index]
        else:
            old_current = None
        self.image_files = self._get_images()

        if not self.image_files:
            self.current_index = 0
            return

        if reset_index or old_current is None:
            self.current_index = 0
            return

        try:
            self.current_index = self.image_files.index(old_current)
        except ValueError:
            self.current_index = min(self.current_index, len(self.image_files) - 1)

    def _update_watcher_paths(self) -> None:
        existing = self._dir_watcher.directories() + self._dir_watcher.files()
        if existing:
            self._dir_watcher.removePaths(existing)

        if self.folder_path is None:
            return

        self._dir_watcher.addPath(str(self.folder_path))
        if self.image_files:
            self._dir_watcher.addPath(str(self.image_files[self.current_index]))

    def _schedule_refresh(self, *_args) -> None:
        self._refresh_timer.start()

    def _refresh_current_folder(self) -> None:
        if self.folder_path is None:
            return

        if self.image_files:
            self.current_index = max(0, min(self.current_index, len(self.image_files) - 1))
            current_file = self.image_files[self.current_index]
        else:
            current_file = None
        before_names = [p.name for p in self.image_files]
        self._refresh_file_list(reset_index=False)
        after_names = [p.name for p in self.image_files]
        self._update_watcher_paths()

        if not self.image_files:
            self._show_no_images("Keine Bilder gefunden")
            return

        should_reload = current_file is None or current_file not in self.image_files or before_names != after_names
        self._load_current_image(silent=not should_reload)

    def _load_current_image(self, silent: bool = False) -> None:
        if not self.image_files:
            self._show_no_images("Keine Bilder gefunden")
            return

        img_path = self.image_files[self.current_index]
        pixmap = QPixmap(str(img_path))
        self.header_label.setText(f"{self.side_name}: {self.folder_path}")
        self.info_label.setText(f"{self.current_index + 1} / {len(self.image_files)}")

        if pixmap.isNull():
            self.image_label.clear_pixmap()
            self.image_label.setText(f"Bild konnte nicht geladen werden:\n{img_path.name}")
            return

        self.image_label.setText("")
        self.image_label.set_pixmap(pixmap)
        self._update_watcher_paths()
        if not silent:
            self.activate()


class ImageDockWidget(QDockWidget):
    activated = Signal(str)

    def __init__(self, title: str, side_key: str, pane: ImagePane, parent: QMainWindow) -> None:
        super().__init__(title, parent)
        self.side_key = side_key
        self.pane = pane
        self.setObjectName(f"dock_{side_key}")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.setMinimumSize(300, 220)
        self.setWidget(pane)
        self.pane.activated.connect(lambda _s: self.activated.emit(self.side_key))
        self.visibilityChanged.connect(self._handle_visibility_changed)

    def _handle_visibility_changed(self, visible: bool) -> None:
        if visible:
            self.activated.emit(self.side_key)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.side_key)
        super().mousePressEvent(event)


class ImageViewerWindow(QMainWindow):
    def __init__(self, initial_path: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("EngineSim Plot Viewer")
        self.setMinimumSize(QSize(1100, 700))

        self.settings = QSettings(APP_ORG, APP_NAME)
        self._restoring_layout = False
        self._applying_layout = False

        self.setDockOptions(
            QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.GroupedDragging
            | QMainWindow.DockOption.AnimatedDocks
        )

        self._central_placeholder = QWidget()
        self._central_placeholder.setObjectName("central_placeholder")
        self._central_placeholder.setMinimumSize(20, 20)
        self.setCentralWidget(self._central_placeholder)

        self.left_pane = ImagePane("left", self.settings, initial_path=initial_path)
        self.right_pane = ImagePane("right", self.settings)

        self.left_dock = ImageDockWidget("Bilder links", "left", self.left_pane, self)
        self.right_dock = ImageDockWidget("Bilder rechts", "right", self.right_pane, self)
        self.left_dock.activated.connect(self._set_active_pane)
        self.right_dock.activated.connect(self._set_active_pane)

        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.left_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.right_dock)

        self.status = QStatusBar()
        self.setStatusBar(self.status)

        self._layout_persist_timer = QTimer(self)
        self._layout_persist_timer.setSingleShot(True)
        self._layout_persist_timer.setInterval(300)
        self._layout_persist_timer.timeout.connect(self._persist_layout)

        self.active_side = "left"
        self._build_actions()
        self._build_menu()
        self._build_toolbar()
        self._connect_layout_change_signals()

        restored = self._restore_layout_from_settings()
        if not restored:
            split_enabled = _settings_bool(self.settings, "split_enabled")
            self._apply_default_layout(
                orientation=Qt.Orientation.Horizontal,
                show_right=split_enabled,
                save=False,
            )
        else:
            self._ensure_dock_widgets_bound()
            self._sync_actions_from_current_layout()
            QTimer.singleShot(0, self.make_docks_equal)

        self._set_active_pane(_settings_str(self.settings, "active_side", "left") or "left")

        if self.left_pane.folder_path is None and self.right_pane.folder_path is None:
            QTimer.singleShot(0, self.choose_active_folder)

        self._show_with_saved_geometry_or_default()
        QTimer.singleShot(0, self._update_window_title)

    def _build_actions(self) -> None:
        self.action_choose_folder = QAction("Ordner wählen…", self)
        self.action_choose_folder.setShortcut(QKeySequence.StandardKey.Open)
        self.action_choose_folder.triggered.connect(self.choose_active_folder)

        self.action_choose_left_folder = QAction("Ordner links wählen…", self)
        self.action_choose_left_folder.setShortcut("Ctrl+1")
        self.action_choose_left_folder.triggered.connect(self.choose_left_folder)

        self.action_choose_right_folder = QAction("Ordner rechts wählen…", self)
        self.action_choose_right_folder.setShortcut("Ctrl+2")
        self.action_choose_right_folder.triggered.connect(self.choose_right_folder)

        self.action_reload = QAction("Neu laden", self)
        self.action_reload.setShortcut(QKeySequence.StandardKey.Refresh)
        self.action_reload.triggered.connect(self.reload_active_pane)

        self.action_prev = QAction("Vorheriges Bild", self)
        self.action_prev.setShortcut(Qt.Key.Key_Left)
        self.action_prev.triggered.connect(lambda: self.navigate_active(-1))

        self.action_next = QAction("Nächstes Bild", self)
        self.action_next.setShortcut(Qt.Key.Key_Right)
        self.action_next.triggered.connect(lambda: self.navigate_active(1))

        self.action_split_view = QAction("Zweiten Bildbereich anzeigen", self)
        self.action_split_view.setCheckable(True)
        self.action_split_view.setShortcut("Ctrl+T")
        self.action_split_view.toggled.connect(self.toggle_split_view)

        self.action_sync_navigation = QAction("Synchron blättern", self)
        self.action_sync_navigation.setCheckable(True)
        self.action_sync_navigation.setShortcut("Ctrl+Shift+Y")
        self.action_sync_navigation.setChecked(_settings_bool(self.settings, "sync_navigation"))
        self.action_sync_navigation.toggled.connect(self._on_sync_navigation_toggled)

        self.action_switch_active = QAction("Aktive Seite wechseln", self)
        self.action_switch_active.setShortcut(Qt.Key.Key_Tab)
        self.action_switch_active.triggered.connect(self.switch_active_pane)

        self.action_layout_side_by_side = QAction("Docks nebeneinander", self)
        self.action_layout_side_by_side.triggered.connect(lambda: self._apply_default_layout(Qt.Orientation.Horizontal, True, True))

        self.action_layout_top_bottom = QAction("Docks untereinander", self)
        self.action_layout_top_bottom.triggered.connect(lambda: self._apply_default_layout(Qt.Orientation.Vertical, True, True))

        self.action_reset_equal_sizes = QAction("Docks gleich groß", self)
        self.action_reset_equal_sizes.triggered.connect(self.make_docks_equal)

        self.action_reset_layout = QAction("Layout zurücksetzen", self)
        self.action_reset_layout.triggered.connect(self.reset_layout)

        self.action_exit = QAction("Beenden", self)
        self.action_exit.setShortcut(QKeySequence.StandardKey.Quit)
        self.action_exit.triggered.connect(self.close)

    def _build_menu(self) -> None:
        menu_file = self.menuBar().addMenu("Datei")
        menu_file.addAction(self.action_choose_folder)
        menu_file.addAction(self.action_choose_left_folder)
        menu_file.addAction(self.action_choose_right_folder)
        menu_file.addAction(self.action_reload)
        menu_file.addSeparator()
        menu_file.addAction(self.action_exit)

        menu_view = self.menuBar().addMenu("Ansicht")
        menu_view.addAction(self.action_prev)
        menu_view.addAction(self.action_next)
        menu_view.addAction(self.action_switch_active)
        menu_view.addSeparator()
        menu_view.addAction(self.action_split_view)
        menu_view.addAction(self.action_sync_navigation)
        menu_view.addSeparator()
        menu_view.addAction(self.action_layout_side_by_side)
        menu_view.addAction(self.action_layout_top_bottom)
        menu_view.addAction(self.action_reset_equal_sizes)
        menu_view.addSeparator()
        menu_view.addAction(self.action_reset_layout)

        menu_window = self.menuBar().addMenu("Fenster")
        menu_window.addAction(self.left_dock.toggleViewAction())
        menu_window.addAction(self.right_dock.toggleViewAction())

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Hauptwerkzeugleiste", self)
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        toolbar.addAction(self.action_choose_folder)
        toolbar.addAction(self.action_choose_left_folder)
        toolbar.addAction(self.action_choose_right_folder)
        toolbar.addSeparator()
        toolbar.addAction(self.action_reload)
        toolbar.addSeparator()
        toolbar.addAction(self.action_prev)
        toolbar.addAction(self.action_next)
        toolbar.addAction(self.action_switch_active)
        toolbar.addSeparator()
        toolbar.addAction(self.action_split_view)
        toolbar.addAction(self.action_sync_navigation)
        toolbar.addAction(self.action_layout_side_by_side)
        toolbar.addAction(self.action_layout_top_bottom)
        toolbar.addAction(self.action_reset_equal_sizes)
        toolbar.addAction(self.action_reset_layout)

    def _connect_layout_change_signals(self) -> None:
        for dock in (self.left_dock, self.right_dock):
            dock.dockLocationChanged.connect(self._schedule_persist_layout)
            dock.topLevelChanged.connect(self._schedule_persist_layout)
            dock.visibilityChanged.connect(self._handle_dock_visibility_change)

    def _handle_dock_visibility_change(self, _visible: bool) -> None:
        if self._restoring_layout or self._applying_layout:
            return
        self._sync_actions_from_current_layout()
        if not self.right_dock.isVisible() and self.active_side == "right":
            self._set_active_pane("left")
        self._schedule_persist_layout()

    def _schedule_persist_layout(self, *_args) -> None:
        if self._restoring_layout or self._applying_layout:
            return
        self._layout_persist_timer.start()

    def _persist_layout(self) -> None:
        if self._restoring_layout or self._applying_layout:
            return
        self._ensure_dock_widgets_bound()
        self.settings.setValue("split_enabled", self.right_dock.isVisible())
        self.settings.setValue("active_side", self.active_side)
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.setValue("window_state_version", LAYOUT_STATE_VERSION)
        self.settings.setValue("window_state", self.saveState(LAYOUT_STATE_VERSION))
        self.settings.sync()

    def _read_byte_array(self, key: str) -> QByteArray | None:
        value = self.settings.value(key)
        if value is None:
            return None
        if isinstance(value, QByteArray):
            return value
        if isinstance(value, bytes):
            return QByteArray(value)
        return None

    def _restore_layout_from_settings(self) -> bool:
        self._ensure_dock_widgets_bound()

        stored_version = _settings_int_or_none(self.settings, "window_state_version")
        if stored_version is not None:
            if stored_version != LAYOUT_STATE_VERSION:
                return False

        geometry = self._read_byte_array("window_geometry")
        if geometry is not None and not geometry.isEmpty():
            self.restoreGeometry(geometry)

        state = self._read_byte_array("window_state")
        if state is None or state.isEmpty():
            return False

        self._restoring_layout = True
        try:
            restored = self.restoreState(state, LAYOUT_STATE_VERSION)
            self._ensure_dock_widgets_bound()
            self._sync_actions_from_current_layout()
            return restored
        finally:
            self._restoring_layout = False

    def _show_with_saved_geometry_or_default(self) -> None:
        geometry = self._read_byte_array("window_geometry")
        if geometry is None or geometry.isEmpty():
            self.showMaximized()
        else:
            self.show()

    def _ensure_dock_widgets_bound(self) -> None:
        if self.left_dock.widget() is not self.left_pane:
            self.left_dock.setWidget(self.left_pane)
        if self.right_dock.widget() is not self.right_pane:
            self.right_dock.setWidget(self.right_pane)

    def _sync_actions_from_current_layout(self) -> None:
        right_visible = self.right_dock.isVisible()
        self.action_split_view.blockSignals(True)
        self.action_split_view.setChecked(right_visible)
        self.action_split_view.blockSignals(False)
        self.action_choose_right_folder.setEnabled(right_visible)
        self.action_switch_active.setEnabled(right_visible)
        self.action_sync_navigation.setEnabled(right_visible)
        if not right_visible and self.action_sync_navigation.isChecked():
            self.action_sync_navigation.blockSignals(True)
            self.action_sync_navigation.setChecked(False)
            self.action_sync_navigation.blockSignals(False)
            self.settings.setValue("sync_navigation", False)

    def _on_sync_navigation_toggled(self, checked: bool) -> None:
        if checked and not self.right_dock.isVisible():
            self.action_sync_navigation.blockSignals(True)
            self.action_sync_navigation.setChecked(False)
            self.action_sync_navigation.blockSignals(False)
            checked = False
        self.settings.setValue("sync_navigation", checked)
        self.status.showMessage(
            "Synchrones Blättern aktiviert." if checked else "Synchrones Blättern deaktiviert.",
            2500,
        )

    def _sync_navigation_enabled(self) -> bool:
        return self.right_dock.isVisible() and self.action_sync_navigation.isChecked()

    def _clear_and_redock(self) -> None:
        self._ensure_dock_widgets_bound()
        for dock in (self.left_dock, self.right_dock):
            dock.setFloating(False)
            self.removeDockWidget(dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.left_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.right_dock)
        self._ensure_dock_widgets_bound()

    def _apply_default_layout(self, orientation: Qt.Orientation, show_right: bool, save: bool) -> None:
        self._applying_layout = True
        try:
            self._clear_and_redock()
            self.left_dock.show()
            if show_right:
                self.right_dock.show()
                self.splitDockWidget(self.left_dock, self.right_dock, orientation)
            else:
                self.right_dock.hide()
                if self.active_side == "right":
                    self.active_side = "left"
            self._sync_actions_from_current_layout()
            if not self.right_dock.isVisible() and self.active_side == "right":
                self.active_side = "left"
            QTimer.singleShot(0, self.make_docks_equal)
            QTimer.singleShot(0, self._update_window_title)
        finally:
            self._applying_layout = False
        if save:
            self._schedule_persist_layout()

    def _pane(self, side: str) -> ImagePane:
        return self.left_pane if side == "left" else self.right_pane

    def _dock(self, side: str) -> ImageDockWidget:
        return self.left_dock if side == "left" else self.right_dock

    def _active_pane(self) -> ImagePane:
        return self._pane(self.active_side)

    def _visible_docks(self) -> list[QDockWidget]:
        docks: list[QDockWidget] = [self.left_dock]
        if self.right_dock.isVisible():
            docks.append(self.right_dock)
        return docks

    def _set_active_pane(self, side: str) -> None:
        if side == "right" and not self.right_dock.isVisible():
            side = "left"
        self.active_side = side
        self.left_pane.set_active(side == "left")
        self.right_pane.set_active(side == "right" and self.right_dock.isVisible())
        self._update_window_title()
        self.status.showMessage(f"Aktive Seite: {'links' if self.active_side == 'left' else 'rechts'}", 2000)

    def switch_active_pane(self) -> None:
        if not self.right_dock.isVisible():
            self._set_active_pane("left")
            return
        self._set_active_pane("right" if self.active_side == "left" else "left")

    def toggle_split_view(self, checked: bool) -> None:
        if checked:
            self._apply_default_layout(Qt.Orientation.Horizontal, True, True)
        else:
            self._apply_default_layout(Qt.Orientation.Horizontal, False, True)

    def make_docks_equal(self) -> None:
        docks = self._visible_docks()
        if len(docks) < 2:
            return
        self.resizeDocks([self.left_dock, self.right_dock], [1, 1], Qt.Orientation.Horizontal)
        self.resizeDocks([self.left_dock, self.right_dock], [1, 1], Qt.Orientation.Vertical)

    def reset_layout(self) -> None:
        self.settings.remove("window_geometry")
        self.settings.remove("window_state")
        self.settings.remove("window_state_version")
        self._apply_default_layout(Qt.Orientation.Horizontal, self.action_split_view.isChecked(), True)
        self.status.showMessage("Dock-Layout zurückgesetzt.", 4000)

    def choose_active_folder(self) -> None:
        pane = self._active_pane()
        if pane.choose_folder(self):
            self._set_active_pane(pane.side_key)
            self._update_window_title()
            self.status.showMessage(f"Ordner geladen: {pane.current_status_text()}", 4000)

    def choose_left_folder(self) -> None:
        if self.left_pane.choose_folder(self):
            self._set_active_pane("left")
            self._update_window_title()
            self.status.showMessage(f"Ordner geladen: {self.left_pane.current_status_text()}", 4000)

    def choose_right_folder(self) -> None:
        if not self.right_dock.isVisible():
            self.action_split_view.setChecked(True)
        self.right_dock.show()
        self.right_dock.raise_()
        if self.right_pane.choose_folder(self):
            self._set_active_pane("right")
            self._update_window_title()
            self.status.showMessage(f"Ordner geladen: {self.right_pane.current_status_text()}", 4000)

    def reload_active_pane(self) -> None:
        pane = self._active_pane()
        pane._refresh_current_folder()
        self._update_window_title()
        self.status.showMessage(f"Neu geladen: {pane.current_status_text()}", 3000)

    def navigate_active(self, direction: int) -> None:
        if self._sync_navigation_enabled():
            moved = False
            for pane in (self.left_pane, self.right_pane):
                if pane.image_files:
                    pane.navigate(direction)
                    moved = True
            self._update_window_title()
            if moved:
                self.status.showMessage(
                    f"Synchrone Anzeige: {self.left_pane.current_status_text()}   |   {self.right_pane.current_status_text()}",
                    3000,
                )
            return

        pane = self._active_pane()
        pane.navigate(direction)
        self._update_window_title()
        self.status.showMessage(f"Anzeige: {pane.current_status_text()}", 3000)

    def _update_window_title(self) -> None:
        left_title = self.left_pane.current_title()
        if self.right_dock.isVisible():
            right_title = self.right_pane.current_title()
            self.setWindowTitle(f"{left_title}   |   {right_title}")
        else:
            self.setWindowTitle(left_title)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Right:
            self.navigate_active(1)
            return
        if event.key() == Qt.Key.Key_Left:
            self.navigate_active(-1)
            return
        if event.key() == Qt.Key.Key_Tab:
            self.switch_active_pane()
            return
        if event.key() == Qt.Key.Key_O and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.choose_active_folder()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._persist_layout()
        super().closeEvent(event)



def main() -> int:
    existing_app = QApplication.instance()
    owns_app = existing_app is None
    app = existing_app or QApplication(sys.argv)

    app.setOrganizationName(APP_ORG)
    app.setApplicationName(APP_NAME)

    initial_path = sys.argv[1] if len(sys.argv) > 1 else None
    window = ImageViewerWindow(initial_path)
    window.show()

    if owns_app:
        return app.exec()

    return 0


if __name__ == "__main__":
    sys.exit(main())
