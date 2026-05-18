from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, QTimer, QFileSystemWatcher, QSettings, QSize
from PySide6.QtGui import QAction, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QToolBar,
    QWidget,
    QSizePolicy,
)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
APP_ORG = "OpenAI"
APP_NAME = "EngineSimImageViewer"

# Fallback-Startordner aus deinem bisherigen Script.
DEFAULT_INITIAL_PATH = (
    r"C:\Users\chris\Desktop\programming\EngineSim\0_MotorSim_V03_V07"
    r"\Projekte\results\sweeps\Vibe_dura_01\plots"
)


class ImageLabel(QLabel):
    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: black; color: white;")
        self.setText("Keine Bilder geladen")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._pixmap_original: QPixmap | None = None

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self._pixmap_original = pixmap
        self._refresh_scaled_pixmap()

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
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        super().setPixmap(scaled)


class ImageViewerWindow(QMainWindow):
    def __init__(self, initial_path: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("EngineSim Plot Viewer")
        self.setMinimumSize(QSize(900, 600))

        self.settings = QSettings(APP_ORG, APP_NAME)
        self.folder_path: Path | None = None
        self.image_files: List[Path] = []
        self.current_index = 0

        self.image_label = ImageLabel()
        self.setCentralWidget(self.image_label)

        self.status = QStatusBar()
        self.setStatusBar(self.status)

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

        self._build_actions()
        self._build_menu()
        self._build_toolbar()

        start_folder = self._resolve_start_folder(initial_path)
        if start_folder is not None:
            self.open_folder(start_folder)
        else:
            QTimer.singleShot(0, self.choose_folder)

        self.showMaximized()

    def _build_actions(self) -> None:
        self.action_choose_folder = QAction("Ordner wählen…", self)
        self.action_choose_folder.setShortcut(QKeySequence.Open)
        self.action_choose_folder.triggered.connect(self.choose_folder)

        self.action_reload = QAction("Neu laden", self)
        self.action_reload.setShortcut(QKeySequence.Refresh)
        self.action_reload.triggered.connect(self._refresh_current_folder)

        self.action_prev = QAction("Vorheriges Bild", self)
        self.action_prev.setShortcut(Qt.Key_Left)
        self.action_prev.triggered.connect(lambda: self.navigate(-1))

        self.action_next = QAction("Nächstes Bild", self)
        self.action_next.setShortcut(Qt.Key_Right)
        self.action_next.triggered.connect(lambda: self.navigate(1))

        self.action_exit = QAction("Beenden", self)
        self.action_exit.setShortcut(QKeySequence.Quit)
        self.action_exit.triggered.connect(self.close)

    def _build_menu(self) -> None:
        menu_file = self.menuBar().addMenu("Datei")
        menu_file.addAction(self.action_choose_folder)
        menu_file.addAction(self.action_reload)
        menu_file.addSeparator()
        menu_file.addAction(self.action_exit)

        menu_view = self.menuBar().addMenu("Ansicht")
        menu_view.addAction(self.action_prev)
        menu_view.addAction(self.action_next)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Hauptwerkzeugleiste", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        toolbar.addAction(self.action_choose_folder)
        toolbar.addAction(self.action_reload)
        toolbar.addSeparator()
        toolbar.addAction(self.action_prev)
        toolbar.addAction(self.action_next)

    def _resolve_start_folder(self, initial_path: str | None) -> Path | None:
        last_folder = self.settings.value("last_folder", "", str)
        candidates = [last_folder, initial_path or "", DEFAULT_INITIAL_PATH]
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            if path.exists() and path.is_dir():
                return path
        return None

    def choose_folder(self) -> None:
        start_dir = str(self.folder_path) if self.folder_path else str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "Bitte Bilderordner auswählen", start_dir)
        if not selected:
            if self.folder_path is None:
                self.status.showMessage("Kein Ordner ausgewählt.", 5000)
            return
        self.open_folder(Path(selected))

    def open_folder(self, folder: Path) -> None:
        if not folder.exists() or not folder.is_dir():
            QMessageBox.warning(self, "Ungültiger Ordner", f"Ordner nicht gefunden:\n{folder}")
            return

        self.folder_path = folder
        self.settings.setValue("last_folder", str(folder))
        self.current_index = 0
        self._refresh_file_list(reset_index=True)
        self._update_watcher_paths()
        self._load_current_image()
        self.status.showMessage(f"Ordner geladen: {folder}", 5000)

    def _get_images(self) -> List[Path]:
        if self.folder_path is None:
            return []
        files = [
            p for p in self.folder_path.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
        ]
        return sorted(files, key=lambda p: p.name.lower())

    def _refresh_file_list(self, reset_index: bool = False) -> None:
        old_current = self.image_files[self.current_index] if self.image_files and not reset_index else None
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

        current_file = self.image_files[self.current_index] if self.image_files else None
        before_names = [p.name for p in self.image_files]
        self._refresh_file_list(reset_index=False)
        after_names = [p.name for p in self.image_files]
        self._update_watcher_paths()

        if not self.image_files:
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("Keine Bilder gefunden")
            self.setWindowTitle("EngineSim Plot Viewer")
            self.status.showMessage(f"Keine Bilder in: {self.folder_path}", 5000)
            return

        should_reload = current_file is None or current_file not in self.image_files or before_names != after_names
        if should_reload:
            self._load_current_image()
        else:
            self._load_current_image(silent=True)

    def _load_current_image(self, silent: bool = False) -> None:
        if not self.image_files:
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("Keine Bilder gefunden")
            self.setWindowTitle("EngineSim Plot Viewer")
            return

        img_path = self.image_files[self.current_index]
        pixmap = QPixmap(str(img_path))
        if pixmap.isNull():
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(f"Bild konnte nicht geladen werden:\n{img_path.name}")
            self.status.showMessage(f"Fehler beim Laden: {img_path.name}", 5000)
            return

        self.image_label.setText("")
        self.image_label.set_pixmap(pixmap)
        self._update_watcher_paths()

        title = f"[{self.current_index + 1}/{len(self.image_files)}] {img_path.name}"
        self.setWindowTitle(title)
        if not silent:
            self.status.showMessage(f"Anzeige: {img_path}", 3000)

    def navigate(self, direction: int) -> None:
        if not self.image_files:
            return
        self.current_index = (self.current_index + direction) % len(self.image_files)
        self._load_current_image()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key_Right:
            self.navigate(1)
            return
        if event.key() == Qt.Key_Left:
            self.navigate(-1)
            return
        if event.key() == Qt.Key_O and event.modifiers() & Qt.ControlModifier:
            self.choose_folder()
            return
        super().keyPressEvent(event)

'''
def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName(APP_ORG)
    app.setApplicationName(APP_NAME)

    initial_path = sys.argv[1] if len(sys.argv) > 1 else None
    window = ImageViewerWindow(initial_path)
    window.show()
    return app.exec()
'''

def main() -> int:
    existing_app = QApplication.instance()
    owns_app = existing_app is None
    app = existing_app or QApplication(sys.argv)

    app.setOrganizationName(APP_ORG)
    app.setApplicationName(APP_NAME)

    initial_path = sys.argv[1] if len(sys.argv) > 1 else None
    window = ImageViewerWindow(initial_path)
    #_OPEN_WINDOWS.append(window)
    window.show()

    if owns_app:
        return app.exec()

    return 0



if __name__ == "__main__":
    sys.exit(main())
