from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
from openpyxl import Workbook


class CsvExporter:
    @staticmethod
    def write(path: str | Path, separator: str, rows: list[dict[str, float | int]], *, header_rows: list[list[object]] | None = None) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not rows and not header_rows:
            return
        fieldnames = [str(v) for v in (header_rows[0] if header_rows else list(rows[0].keys()))]
        with path.open('w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f, delimiter=separator)
            if header_rows:
                for header in header_rows:
                    values = list(header[:len(fieldnames)])
                    if len(values) < len(fieldnames):
                        values.extend([''] * (len(fieldnames) - len(values)))
                    writer.writerow(values)
            else:
                writer.writerow(fieldnames)
            dict_writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=separator, extrasaction='ignore')
            dict_writer.writerows(rows)


class ExcelExporter:
    @staticmethod
    def _excel_value(value):
        if value is None:
            return None
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, (Path, bytes, bytearray, memoryview)):
            return str(value)
        if isinstance(value, bool):
            return bool(value)
        if isinstance(value, (np.bool_,)):
            return bool(value)
        if isinstance(value, (int, np.integer)):
            return int(value)
        if isinstance(value, (float, np.floating)):
            value = float(value)
            return value if math.isfinite(value) else None
        if isinstance(value, (list, tuple, set, dict)):
            try:
                return json.dumps(value, ensure_ascii=False)
            except Exception:
                return str(value)
        return value

    @classmethod
    def _normalized_headers(cls, rows: list[dict[str, object]], header_rows: list[list[object]] | None = None) -> list[str]:
        if header_rows:
            return [str(v) for v in header_rows[0]]
        if not rows:
            return []
        headers: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row.keys():
                key_text = str(key)
                if key_text in seen:
                    continue
                seen.add(key_text)
                headers.append(key_text)
        return headers

    @classmethod
    def _iter_excel_rows(cls, rows: list[dict[str, object]], headers: list[str], header_rows: list[list[object]] | None = None):
        if header_rows:
            for row in header_rows:
                values = list(row[:len(headers)])
                if len(values) < len(headers):
                    values.extend([''] * (len(headers) - len(values)))
                yield [cls._excel_value(v) for v in values]
        else:
            yield headers
        for row in rows:
            yield [cls._excel_value(row.get(key)) for key in headers]

    @classmethod
    def _write_with_workbook(cls, path: Path, rows: list[dict[str, object]], *, write_only: bool, header_rows: list[list[object]] | None = None) -> None:
        headers = cls._normalized_headers(rows, header_rows=header_rows)
        if not headers:
            return
        wb = Workbook(write_only=write_only)
        if write_only:
            ws = wb.create_sheet(title='results')
        else:
            ws = wb.active
            ws.title = 'results'
        for excel_row in cls._iter_excel_rows(rows, headers, header_rows=header_rows):
            ws.append(excel_row)
        with NamedTemporaryFile(prefix=path.stem + '_', suffix='.tmp', dir=path.parent, delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            wb.save(tmp_path)
            tmp_path.replace(path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise
        finally:
            try:
                wb.close()
            except Exception:
                pass

    @classmethod
    def write(cls, path: str | Path, rows: list[dict[str, float | int]], *, header_rows: list[list[object]] | None = None) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not rows and not header_rows:
            return
        try:
            cls._write_with_workbook(path, rows, write_only=True, header_rows=header_rows)
        except Exception:
            cls._write_with_workbook(path, rows, write_only=False, header_rows=header_rows)
