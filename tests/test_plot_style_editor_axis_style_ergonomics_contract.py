from pathlib import Path


def test_axis_tab_contains_axis_style_clipboard_and_apply_actions() -> None:
    text = Path('src/thermo0d/gui/plot_style_editor.py').read_text(encoding='utf-8')
    assert 'self.axis_style_clipboard: dict[str, Any] | None = None' in text
    assert 'axis_copy_style_btn = QPushButton("Stil kopieren")' in text
    assert 'axis_paste_style_btn = QPushButton("Stil einfügen")' in text
    assert 'axis_apply_subplot_btn = QPushButton("Auf Subplot")' in text
    assert 'axis_apply_all_btn = QPushButton("Auf alle Subplots")' in text
    assert 'def copy_current_axis_style(self) -> None:' in text
    assert 'def paste_current_axis_style(self) -> None:' in text
    assert 'def apply_current_axis_style_to_subplot(self) -> None:' in text
    assert 'def apply_current_axis_style_to_all_subplots(self) -> None:' in text


def test_axis_tab_contains_nice_auto_limits_helpers() -> None:
    text = Path('src/thermo0d/gui/plot_style_editor.py').read_text(encoding='utf-8')
    assert 'axis_nice_btn = QPushButton("Auto-Limits")' in text
    assert 'axis_nice_btn.clicked.connect(self.fit_current_axis_to_data_nice)' in text
    assert 'def _nice_number(self, value: float, round_result: bool = True) -> float:' in text
    assert 'def _nice_axis_limits(self, values: list[float]) -> tuple[float, float, float, float] | None:' in text
    assert 'def _collect_axis_preview_values(self, subplot: SubplotModel, axis: AxisModel) -> list[float]:' in text
    assert 'def fit_current_axis_to_data_nice(self) -> None:' in text
    assert 'self.statusBar().showMessage(f"Auto-Limits gesetzt: {compact(y_min)} … {compact(y_max)}", 3000)' in text
