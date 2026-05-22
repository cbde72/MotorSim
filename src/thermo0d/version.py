from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

VERSION = (7, 1, 122)
__version__ = ".".join(str(x) for x in VERSION)
CURRENT_CONFIG_SCHEMA_VERSION = 8


@dataclass(frozen=True)
class VersionStamp:
    package_version: str
    config_schema_version: int
    loaded_config_schema_version: int
    migration_applied: bool


def version_string() -> str:
    return __version__


def normalized_versioning_dict(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    src = dict(raw or {})
    schema = src.get('config_schema_version', src.get('schema_version', 0))
    package_version = src.get('package_version', src.get('app_version', __version__))
    loaded_schema = src.get('loaded_config_schema_version', schema)
    migrated = bool(src.get('migration_applied', False))
    return {
        'package_version': str(package_version),
        'config_schema_version': int(schema),
        'loaded_config_schema_version': int(loaded_schema),
        'migration_applied': migrated,
    }


def stamp_for_loaded_config(raw_versioning: Mapping[str, Any] | None) -> VersionStamp:
    data = normalized_versioning_dict(raw_versioning)
    return VersionStamp(
        package_version=data['package_version'],
        config_schema_version=int(data['config_schema_version']),
        loaded_config_schema_version=int(data['loaded_config_schema_version']),
        migration_applied=bool(data['migration_applied']),
    )
