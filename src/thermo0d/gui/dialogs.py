from __future__ import annotations

from pathlib import Path
from typing import cast

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QDialog, QFileDialog, QInputDialog, QMessageBox, QWidget


def _unminimize_and_activate(widget: QWidget | None) -> None:
    if widget is None:
        return
    try:
        state = widget.windowState()
        if state & Qt.WindowMinimized:
            widget.setWindowState(state & ~Qt.WindowMinimized)
        widget.raise_()
        widget.activateWindow()
    except Exception:
        return


def bring_to_front(widget: QWidget | None) -> None:
    if widget is None:
        return
    _unminimize_and_activate(widget)
    QTimer.singleShot(0, lambda w=widget: _unminimize_and_activate(w))
    QTimer.singleShot(150, lambda w=widget: _unminimize_and_activate(w))


def prepare_dialog(dialog: QDialog, *, modal: bool = True, use_tool_flag: bool = True) -> QDialog:
    flags = dialog.windowFlags() | Qt.Dialog | Qt.WindowStaysOnTopHint
    if use_tool_flag:
        flags |= Qt.Tool
    dialog.setWindowFlags(flags)
    if modal:
        dialog.setModal(True)
        dialog.setWindowModality(Qt.ApplicationModal)
    bring_to_front(dialog)
    return dialog


def exec_dialog(dialog: QDialog, *, modal: bool = True, use_tool_flag: bool = True) -> int:
    prepare_dialog(dialog, modal=modal, use_tool_flag=use_tool_flag)
    dialog.show()
    bring_to_front(dialog)
    return int(dialog.exec())


def show_foreground(widget: QWidget | None) -> None:
    if widget is None:
        return
    widget.show()
    bring_to_front(widget)


def _set_message_details(box: QMessageBox, informative: str | None, details: str | None) -> None:
    if informative:
        box.setInformativeText(informative)
    if details:
        box.setDetailedText(details)


def show_information(parent: QWidget | None, title: str, text: str, *, informative: str | None = None, details: str | None = None) -> QMessageBox.StandardButton:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.Ok)
    _set_message_details(box, informative, details)
    exec_dialog(box)
    return cast(QMessageBox.StandardButton, box.standardButton(box.clickedButton()))


def show_warning(parent: QWidget | None, title: str, text: str, *, informative: str | None = None, details: str | None = None) -> QMessageBox.StandardButton:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.Ok)
    _set_message_details(box, informative, details)
    exec_dialog(box)
    return cast(QMessageBox.StandardButton, box.standardButton(box.clickedButton()))


def show_critical(parent: QWidget | None, title: str, text: str, *, informative: str | None = None, details: str | None = None) -> QMessageBox.StandardButton:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Critical)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.Ok)
    _set_message_details(box, informative, details)
    exec_dialog(box)
    return cast(QMessageBox.StandardButton, box.standardButton(box.clickedButton()))


def ask_question(parent: QWidget | None, title: str, text: str, *, buttons: QMessageBox.StandardButton = QMessageBox.Yes | QMessageBox.No, default_button: QMessageBox.StandardButton = QMessageBox.No, informative: str | None = None, details: str | None = None) -> QMessageBox.StandardButton:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(buttons)
    box.setDefaultButton(default_button)
    _set_message_details(box, informative, details)
    exec_dialog(box)
    clicked = box.clickedButton()
    if clicked is None:
        return QMessageBox.NoButton
    return cast(QMessageBox.StandardButton, box.standardButton(clicked))


def _split_dialog_path(start: str) -> tuple[str, str]:
    if not start:
        return "", ""
    candidate = Path(start).expanduser()
    text = str(candidate)
    if candidate.exists() and candidate.is_file():
        return str(candidate.parent), candidate.name
    if candidate.suffix:
        return str(candidate.parent), candidate.name
    return text, ""


def get_open_file_name(parent: QWidget | None, caption: str, directory: str = "", filter: str = "", selected_filter: str = "") -> tuple[str, str]:
    start_dir, initial_file = _split_dialog_path(directory)
    dialog = QFileDialog(parent, caption, start_dir, filter)
    dialog.setFileMode(QFileDialog.ExistingFile)
    dialog.setAcceptMode(QFileDialog.AcceptOpen)
    dialog.setOption(QFileDialog.DontUseNativeDialog, True)
    if selected_filter:
        dialog.selectNameFilter(selected_filter)
    if initial_file:
        dialog.selectFile(initial_file)
    if exec_dialog(dialog, use_tool_flag=False) != int(QDialog.Accepted):
        return "", ""
    files = dialog.selectedFiles()
    return (files[0] if files else "", dialog.selectedNameFilter())


def get_save_file_name(parent: QWidget | None, caption: str, directory: str = "", filter: str = "", selected_filter: str = "") -> tuple[str, str]:
    start_dir, initial_file = _split_dialog_path(directory)
    dialog = QFileDialog(parent, caption, start_dir, filter)
    dialog.setFileMode(QFileDialog.AnyFile)
    dialog.setAcceptMode(QFileDialog.AcceptSave)
    dialog.setOption(QFileDialog.DontUseNativeDialog, True)
    if selected_filter:
        dialog.selectNameFilter(selected_filter)
    if initial_file:
        dialog.selectFile(initial_file)
    if exec_dialog(dialog, use_tool_flag=False) != int(QDialog.Accepted):
        return "", ""
    files = dialog.selectedFiles()
    return (files[0] if files else "", dialog.selectedNameFilter())


def get_text(parent: QWidget | None, title: str, label: str, *, text: str = "") -> tuple[str, bool]:
    dialog = QInputDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    dialog.setTextValue(text)
    if exec_dialog(dialog) != int(QDialog.Accepted):
        return text, False
    return dialog.textValue(), True


def get_color(initial: QColor, parent: QWidget | None = None, title: str = "Farbe auswählen") -> QColor:
    dialog = QColorDialog(initial, parent)
    dialog.setWindowTitle(title)
    dialog.setOption(QColorDialog.DontUseNativeDialog, True)
    if exec_dialog(dialog, use_tool_flag=False) != int(QDialog.Accepted):
        return QColor()
    return dialog.currentColor()
