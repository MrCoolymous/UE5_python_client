# net/guid/static_field_mapping.py
"""Static field mapping loaded from max_values.json.

Provides class max values for SerializeInt, per-class field index resolution, and detection.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_JSON_PATH = Path(__file__).parent / "data" / "max_values.json"


def _load_json() -> dict:
    try:
        return json.loads(_JSON_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _parse_max_values(raw: dict) -> dict[str, int]:
    values = raw.get("max_values", {})
    return {
        k: v for k, v in values.items()
        if isinstance(k, str) and isinstance(v, int) and v > 0
    }


def _parse_per_class(raw: dict) -> dict[str, dict[int, str]]:
    """Build class_name -> {field_index -> field_name} mapping."""
    result: dict[str, dict[int, str]] = {}
    for class_name, info in raw.get("per_class", {}).items():
        index_map: dict[int, str] = {}
        for idx_str, field_info in info.get("fields", {}).items():
            name = field_info.get("name")
            if name:
                index_map[int(idx_str)] = name
        if index_map:
            result[class_name] = index_map
    return result


_RAW = _load_json()
CLASS_MAX_VALUES: dict[str, int] = _parse_max_values(_RAW)
_PER_CLASS_FIELDS: dict[str, dict[int, str]] = _parse_per_class(_RAW)
del _RAW

def get_class_max(class_name: str) -> Optional[int]:
    return CLASS_MAX_VALUES.get(class_name)


def has_class_max(class_name: str) -> bool:
    return class_name in CLASS_MAX_VALUES


def get_field_name(class_name: str, field_index: int) -> Optional[str]:
    fields = _PER_CLASS_FIELDS.get(class_name)
    if fields:
        return fields.get(field_index)
    return None