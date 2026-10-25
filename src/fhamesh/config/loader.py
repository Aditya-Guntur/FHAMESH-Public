"""Configuration loader for the Federated Hierarchical Agent Mesh."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from .defaults import DEFAULT_CONFIG
from .schemas import SystemConfig

logger = logging.getLogger(__name__)


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, preferring override values."""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class ConfigLoader:
    """Load and validate YAML configuration files.

    Merges multiple config files (default, policies, privacy, domains)
    with built-in defaults to produce a validated SystemConfig.
    """

    def __init__(self, config_dir: str | Path = "config"):
        self._dir = Path(config_dir)

    def load(self) -> SystemConfig:
        """Load all config files, merge with defaults, and validate."""
        merged = dict(DEFAULT_CONFIG)

        file_map = {
            "default.yaml": None,        # top-level merge
            "policies.yaml": "policies",  # nested under "policies" key
            "privacy.yaml": "privacy",
            "domains.yaml": "domains",
        }

        for filename, nest_key in file_map.items():
            data = self._load_yaml(filename)
            if data is None:
                continue
            if nest_key is None:
                merged = _deep_merge(merged, data)
            else:
                merged[nest_key] = _deep_merge(merged.get(nest_key, {}), data)

        return SystemConfig(**merged)

    def _load_yaml(self, filename: str) -> dict[str, Any] | None:
        """Load a single YAML file. Returns None if file doesn't exist."""
        path = self._dir / filename
        if not path.exists():
            logger.debug("Config file not found, skipping: %s", path)
            return None
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            logger.warning("Config file %s did not contain a mapping, skipping", path)
            return None
        return data
