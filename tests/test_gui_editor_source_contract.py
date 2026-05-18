from pathlib import Path


def test_valve_editor_uses_side_specific_file_fields() -> None:
    text = Path('src/thermo0d/gui/engine_gasexchange_editor.py').read_text(encoding='utf-8')
    assert 'FilePathField(editor, "Lift file", f"{self.base_path}.lift_file")' in text
    assert 'FilePathField(editor, "AlphaK file", f"{self.base_path}.alphak_file")' in text
    assert 'ValveAngleBasisField(editor, "Lift basis", f"{self.base_path}.profile_angle_domain")' in text
    assert "side_cfg.get('lift_file') or side_cfg.get('_lift_file')" in text
    assert "side_cfg.get('alphak_file') or side_cfg.get('_alpha_k_file')" in text


def test_preview_shows_ymax_metadata() -> None:
    text = Path('src/thermo0d/gui/engine_gasexchange_editor.py').read_text(encoding='utf-8')
    assert 'info_parts.append(f"y_max={compact_number(stats[\'y_max\'], digits=6)}")' in text
    assert 'Öffnungsdauer=' not in text
    assert 'preview_info = f"y_max={compact_number(left_axis_max, digits=6)} {self.editor.active_left_axis_unit()} | Basis {self.editor.valve_lift_basis_summary()}"' in text


def test_gui_valve_preview_uses_bore_area_relation_and_side_basis() -> None:
    text = Path('src/thermo0d/gui/engine_gasexchange_editor.py').read_text(encoding='utf-8')
    assert 'deep_get(self.config_data, f"gasexchange.valves.{side}.profile_angle_domain", "")' in text
    assert 'return max(alpha_k * bore_area, 0.0)' in text
    assert 'diameter_field' not in text
    assert 'return f"IN={intake_basis} | EX={exhaust_basis}"' in text


def test_timing_preview_right_axis_toggle_supports_piston_or_volume() -> None:
    text = Path('src/thermo0d/gui/engine_gasexchange_editor.py').read_text(encoding='utf-8')
    assert 'RIGHT_AXIS_PISTON_MODE = "piston_travel_ut"' in text
    assert 'RIGHT_AXIS_VOLUME_MODE = "cylinder_volume"' in text
    assert 'self.right_axis_toggle = QToolButton()' in text
    assert 'self.right_axis_toggle.setToolTip("Rechte Y-Achse: Kolbenweg ab UT oder Volumen")' in text
    assert 'self.right_axis_toggle.toggled.connect(self.toggle_right_axis_mode)' in text
    assert 'def preview_right_axis_value(' in text
    assert 'return self.plot_volume_from_m3(cylinder_volume_m3(' in text
    assert 'return self.plot_length_from_m(piston_distance_from_ut(' in text
    assert 'right_title = style.right_axis_title.strip() or f"{self.editor.active_right_axis_title()} [{self.editor.active_right_axis_unit()}]"' in text


def test_gui_loads_last_config_and_uses_visible_cam_crank_toggle() -> None:
    text = Path('src/thermo0d/gui/engine_gasexchange_editor.py').read_text(encoding='utf-8')
    assert 'self.settings.value("files/last_config_path", "")' in text
    assert "self.settings.setValue('files/last_config_path'" in text
    assert 'class ValveAngleBasisField(QWidget):' in text
    assert 'self.cam_button.setText("CAM")' in text
    assert 'self.crank_button.setText("CRANK")' in text


def test_valve_timing_editor_uses_selection_buttons_and_only_stores_opening() -> None:
    text = Path('src/thermo0d/gui/engine_gasexchange_editor.py').read_text(encoding='utf-8')
    assert 'class ValveTimingReferenceField(QWidget):' in text
    assert 'self.open_button.setText("Öffnen")' in text
    assert 'self.close_button.setText("Schließen")' in text
    assert 'self.center_button.setText("Center")' in text
    assert 'class ValveTimingValueField(QWidget):' in text
    assert 'self.editor.set_valve_open_from_display_value(self.side, mode, model_value)' in text
    assert 'deep_set(self.config_data, f"gasexchange.valves.{side}.open_deg", open_deg)' in text
    assert 'deep_set(self.config_data, f"gasexchange.valves.{side}.close_deg", close_deg)' not in text
    assert 'deep_set(self.config_data, f"gasexchange.valves.{side}.center_deg", center)' not in text


def test_valve_scaling_keeps_opening_and_updates_scaled_span_for_display() -> None:
    text = Path('src/thermo0d/gui/engine_gasexchange_editor.py').read_text(encoding='utf-8')
    assert 'def valve_scaled_span_deg(self, side: str) -> float:' in text
    assert 'def valve_timing_value(self, side: str, mode: str) -> float:' in text
    assert 'return self.valve_open_deg(side) + self.valve_scaled_span_deg(side)' in text
    assert 'return self.valve_open_deg(side) + 0.5 * self.valve_scaled_span_deg(side)' in text
    assert 'def apply_valve_scaling(self, side: str) -> None:' in text
    assert 'max_lift = max(base_max_lift * lift_scale, 0.0)' in text
    assert 'deep_set(self.config_data, f"gasexchange.valves.{side}.open_deg", open_deg)' in text
    assert 'open_deg = center - span_deg * 0.5' not in text
    assert 'close_deg = center + span_deg * 0.5' not in text
