from pathlib import Path


def test_topology_property_panel_uses_schema_hints_and_required_markers() -> None:
    text = Path('src/thermo0d/gui/topology_config_editor.py').read_text(encoding='utf-8')
    assert 'from thermo0d.config.schema_meta import build_context_summary, get_schema_hint' in text
    assert 'self.schema_label = QLabel("")' in text
    assert 'schema_summary = build_context_summary(payload)' in text
    assert 'hint = get_schema_hint(self._payload, key)' in text
    assert 'label_text += " *"' in text
    assert 'widget.setPlaceholderText(hint.default_text)' in text
    assert 'hint.tooltip()' in text
