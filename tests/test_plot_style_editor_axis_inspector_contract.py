from pathlib import Path


def test_axis_inspector_contains_y_limit_fields_and_quick_actions() -> None:
    text = Path('src/thermo0d/gui/plot_style_editor.py').read_text(encoding='utf-8')
    assert 'form.addRow("Y limits", self.axis_limit_mode_combo)' in text
    assert 'form.addRow("Y min", self.axis_y_min_spin)' in text
    assert 'form.addRow("Y max", self.axis_y_max_spin)' in text
    assert 'form.addRow("Y major step", self.axis_tick_step_spin)' in text
    assert 'form.addRow("Y minor step", self.axis_minor_tick_step_spin)' in text
    assert 'form.addRow("Y major grid", self.axis_major_grid_check)' in text
    assert 'form.addRow("Y minor grid", self.axis_minor_grid_check)' in text
    assert 'def reset_current_axis_to_auto(self) -> None:' in text
    assert 'def swap_current_axis_side(self) -> None:' in text
    assert 'def enable_current_axis_full_grid(self) -> None:' in text


def test_axis_rendering_applies_manual_limits_steps_and_grids() -> None:
    text = Path('src/thermo0d/gui/plot_style_editor.py').read_text(encoding='utf-8')
    assert 'def _apply_axis_view_config(self, mpl_axis, axis_model: AxisModel) -> None:' in text
    assert 'mpl_axis.set_ylim(y_min, y_max)' in text
    assert 'mpl_axis.yaxis.set_major_locator(MultipleLocator(tick_step))' in text
    assert 'mpl_axis.yaxis.set_minor_locator(MultipleLocator(minor_tick_step))' in text
    assert 'mpl_axis.grid(True, which="major", axis="y"' in text
    assert 'mpl_axis.grid(True, which="minor", axis="y"' in text


def test_refresh_lists_restore_selection_by_id_instead_of_jumping_to_first_row() -> None:
    text = Path('src/thermo0d/gui/plot_style_editor.py').read_text(encoding='utf-8')
    assert 'def _selected_list_row_by_id(self, list_widget: QListWidget) -> tuple[int, str]:' in text
    assert 'def _restore_list_row_by_id(self, list_widget: QListWidget, preferred_row: int, preferred_id: str) -> None:' in text
    assert 'previous_row, previous_id = self._selected_list_row_by_id(self.axis_list)' in text
    assert 'self._restore_list_row_by_id(self.axis_list, previous_row, previous_id)' in text
    assert 'previous_row, previous_id = self._selected_list_row_by_id(self.series_list)' in text
    assert 'self._restore_list_row_by_id(self.series_list, previous_row, previous_id)' in text
    assert 'previous_row, previous_id = self._selected_list_row_by_id(self.event_list)' in text
    assert 'self._restore_list_row_by_id(self.event_list, previous_row, previous_id)' in text
