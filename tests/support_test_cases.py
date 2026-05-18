from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_cases_root() -> Path:
    path = project_root() / "test_cases"
    path.mkdir(parents=True, exist_ok=True)
    return path


def case_dir(name: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name).strip("_") or "case"
    path = test_cases_root() / safe
    path.mkdir(parents=True, exist_ok=True)
    return path
