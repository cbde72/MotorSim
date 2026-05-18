from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import numpy as np


@dataclass(slots=True)
class NumericTableLoadResult:
    data: np.ndarray
    header_text: str
    converted_lift_axis_from_mm: bool = False


_FLOAT_SEP_RE = re.compile(r"[;,\t\s]+")
_M_TOKEN_RE = re.compile(r"(^|[^a-z])m([^a-z]|$)")


def _parse_numeric_rows(text: str, expected_cols: int) -> tuple[list[list[float]], list[str]]:
    rows: list[list[float]] = []
    header_candidates: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", ";", "//")):
            header_candidates.append(stripped.lstrip("#;/ "))
            continue
        parts = [part.strip() for part in _FLOAT_SEP_RE.split(stripped) if part.strip()]
        nums: list[float] = []
        for part in parts:
            try:
                nums.append(float(part.replace(",", ".")))
            except Exception:
                continue
        if len(nums) >= expected_cols:
            rows.append(nums[:expected_cols])
        elif re.search(r"[A-Za-zÄÖÜäöü]", stripped):
            header_candidates.append(stripped)
    return rows, header_candidates


def _has_lift_token(header_text: str) -> bool:
    return ("lift" in header_text) or ("hub" in header_text)


def _explicit_mm_hint(header_text: str) -> bool:
    return _has_lift_token(header_text) and ("mm" in header_text)


def _explicit_m_hint(header_text: str) -> bool:
    return _has_lift_token(header_text) and ("mm" not in header_text) and bool(_M_TOKEN_RE.search(header_text))


def _should_convert_lift_axis_from_mm(header_text: str, axis_max_abs: float) -> bool:
    explicit_mm = _explicit_mm_hint(header_text)
    explicit_m = _explicit_m_hint(header_text)
    inferred_mm = (not explicit_m) and axis_max_abs > 0.05
    return explicit_mm or inferred_mm


def load_numeric_table(path: Path, expected_cols: int, table_kind: str = "generic") -> NumericTableLoadResult:
    if not path.exists():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    rows, header_candidates = _parse_numeric_rows(text, expected_cols)
    if not rows:
        raise ValueError(f"{path} does not contain numeric rows with at least {expected_cols} columns")
    data = np.asarray(rows, dtype=np.float64)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    if data.shape[1] != expected_cols:
        raise ValueError(f"{path} must have exactly {expected_cols} numeric columns")
    data = data[np.argsort(data[:, 0])]
    header_text = " ".join(header_candidates).lower()

    converted = False
    if data.size and table_kind in {"valve_lift", "valve_alpha"}:
        axis_col = 1 if table_kind == "valve_lift" else 0
        axis_max_abs = float(np.max(np.abs(data[:, axis_col])))
        if _should_convert_lift_axis_from_mm(header_text, axis_max_abs):
            data[:, axis_col] *= 1.0e-3
            converted = True

    return NumericTableLoadResult(
        data=data,
        header_text=header_text,
        converted_lift_axis_from_mm=converted,
    )
