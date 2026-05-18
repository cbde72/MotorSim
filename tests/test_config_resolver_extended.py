from __future__ import annotations

from pathlib import Path

import pytest

from thermo0d.input.config_resolver import ConfigResolver


def test_pick_project_dir_returns_selected(monkeypatch, tmp_path: Path):
    selected = tmp_path / 'picked'
    selected.mkdir()

    class DummyTk:
        def withdraw(self):
            pass
        def destroy(self):
            pass

    monkeypatch.setattr('thermo0d.input.config_resolver.Tk', lambda: DummyTk())
    monkeypatch.setattr('thermo0d.input.config_resolver.filedialog.askdirectory', lambda **kwargs: str(selected))
    assert ConfigResolver.pick_project_dir(tmp_path) == selected.resolve()


def test_pick_project_dir_cancel(monkeypatch, tmp_path: Path):
    class DummyTk:
        def withdraw(self):
            pass
        def destroy(self):
            pass

    monkeypatch.setattr('thermo0d.input.config_resolver.Tk', lambda: DummyTk())
    monkeypatch.setattr('thermo0d.input.config_resolver.filedialog.askdirectory', lambda **kwargs: '')
    assert ConfigResolver.pick_project_dir(tmp_path) is None


def test_resolve_project_dir_pick(monkeypatch, tmp_path: Path):
    resolver = ConfigResolver(tmp_path / 'base', tmp_path / 'variants')
    chosen = tmp_path / 'chosen'
    chosen.mkdir()
    monkeypatch.setattr(resolver, 'pick_project_dir', lambda initial: chosen)
    assert resolver.resolve_project_dir(tmp_path / 'missing', True, False) == chosen


def test_resolve_single_config_default_single_yaml(tmp_path: Path):
    project = tmp_path / 'project'
    project.mkdir()
    only = project / 'only.yaml'
    only.write_text('a: 1', encoding='utf-8')
    resolver = ConfigResolver(project, tmp_path / 'variants')
    assert resolver.resolve_single_config(None, project) == only.resolve()


def test_resolve_single_config_dir_with_config_yaml(tmp_path: Path):
    project = tmp_path / 'project'
    target = project / 'sub'
    target.mkdir(parents=True)
    cfg = target / 'config.yaml'
    cfg.write_text('a: 1', encoding='utf-8')
    resolver = ConfigResolver(project, tmp_path / 'variants')
    assert resolver.resolve_single_config(str(target), project) == cfg.resolve()


def test_resolve_single_config_from_variants(tmp_path: Path):
    project = tmp_path / 'project'
    variants = tmp_path / 'variants'
    project.mkdir()
    variants.mkdir()
    cfg = variants / 'case.yaml'
    cfg.write_text('a: 1', encoding='utf-8')
    resolver = ConfigResolver(project, variants)
    assert resolver.resolve_single_config('case.yaml', project) == cfg.resolve()


def test_resolve_batch_configs_missing_raises(tmp_path: Path):
    resolver = ConfigResolver(tmp_path / 'project', tmp_path / 'variants')
    with pytest.raises(FileNotFoundError):
        resolver.resolve_batch_configs(tmp_path / 'does_not_exist')
