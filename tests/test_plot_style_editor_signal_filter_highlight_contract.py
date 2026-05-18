from pathlib import Path


def test_signal_filter_has_real_match_highlighting_and_focus() -> None:
    text = Path('src/thermo0d/gui/plot_style_editor.py').read_text(encoding='utf-8')
    assert 'def _signal_filter_tokens(self) -> list[str]:' in text
    assert 'def _signal_matches_filter(self, signal: str, resolved: str, tokens: list[str]) -> bool:' in text
    assert 'def _apply_filter_match_highlight(self, item: QTreeWidgetItem, *, is_direct_hit: bool, token_text: str) -> None:' in text
    assert 'highlight_brush = QBrush(QColor("#fff3b0"))' in text
    assert 'font.setBold(True)' in text
    assert 'item.setBackground(0, highlight_brush)' in text
    assert 'item.setToolTip(1, f"Filter-Treffer: {token_text}")' in text
    assert 'cat_item.setText(1, f"{cat_match_count} Treffer")' in text
    assert 'top_item.setText(1, f"{top_match_count} Treffer")' in text
    assert 'self.signal_tree.setCurrentItem(first_hit_item)' in text
    assert 'self.signal_tree.scrollToItem(first_hit_item)' in text
    assert 'self.statusBar().showMessage(f"Signalfilter: {total_hits} Treffer", 2500)' in text
