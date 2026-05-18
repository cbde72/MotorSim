from __future__ import annotations

from pathlib import Path

from thermo0d.output.exporters import CsvExporter, ExcelExporter
from thermo0d.output.rows import ResultRowBuilder
import thermo0d.main as main_module


def test_exporters_skip_empty_rows(tmp_path: Path):
    csv_path = tmp_path / 'empty.csv'
    xlsx_path = tmp_path / 'empty.xlsx'
    CsvExporter.write(csv_path, ';', [])
    ExcelExporter.write(xlsx_path, [])
    assert not csv_path.exists()
    assert not xlsx_path.exists()


def test_row_builder_importable():
    assert ResultRowBuilder is not None


def test_package_main_calls_run(monkeypatch):
    called = {'n': 0}
    monkeypatch.setattr(main_module, 'run', lambda: called.__setitem__('n', called['n'] + 1))
    main_module.main()
    assert called['n'] == 1
