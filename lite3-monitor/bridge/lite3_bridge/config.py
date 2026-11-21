"""Configuration loading.

The default config (config/default.yaml) is always loaded first; a user file
passed with --config is deep-merged on top. Lists are replaced, not merged.
"""
from __future__ import annotations

import copy
import ipaddress
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PACKAGE_DIR.parent / "config" / "default.yaml"


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    if path:
        with open(path, "r", encoding="utf-8") as fh:
            user = yaml.safe_load(fh) or {}
        cfg = _deep_merge(cfg, user)
    validate_config(cfg)
    return cfg


def validate_config(cfg: Dict[str, Any]) -> None:
    rates = cfg["rates"]
    for key in ("telemetry_hz", "health_hz", "paths_hz", "decode_hz"):
        if not (0 < float(rates[key]) <= 50):
            raise ValueError(f"rates.{key} must be in (0, 50]")
    if float(rates["map_min_interval_s"]) < 0.5:
        raise ValueError("rates.map_min_interval_s must be >= 0.5")
    for role, spec in cfg["topics"].items():
        if not isinstance(spec.get("candidates", []), list):
            raise ValueError(f"topics.{role}.candidates must be a list")
        if not spec.get("types"):
            raise ValueError(f"topics.{role}.types must be a non-empty list")
    dom = cfg["identity"].get("expected_ros_domain_id")
    if dom is not None and not (0 <= int(dom) <= 232):
        raise ValueError("identity.expected_ros_domain_id must be 0..232")


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def env_ros_domain_id() -> Optional[int]:
    raw = os.environ.get("ROS_DOMAIN_ID", "").strip()
    if raw == "":
        return None  # ROS 2 default is 0 when unset
    try:
        return int(raw)
    except ValueError:
        return None
