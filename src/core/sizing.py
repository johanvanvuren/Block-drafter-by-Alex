"""
Measurement & Sizing Manager for Garment Block Drafting.

Loads standard UK (8-16) metric size presets, merges required block measurements,
tracks custom bespoke overrides, and persists custom measurement profiles.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


@dataclass
class MeasurementField:
    """Metadata and value bounds for a single body measurement in centimeters."""

    key: str
    label: str
    default_cm: float
    min_cm: float = 1.0
    max_cm: float = 250.0
    description: str = ""


class SizingManager:
    """Manages standard sample sizes (UK 8-16) and custom bespoke measurements."""

    def __init__(self, sizes_json_path: Optional[str | Path] = None) -> None:
        self.system_id: str = "uk_metric_womenswear"
        self.system_name: str = "UK Standard Metric Sizing (Aldrich)"
        self.unit: str = "cm"
        self.definitions: Dict[str, MeasurementField] = {}
        self.presets: Dict[str, Dict[str, float]] = {}
        self.active_preset: str = "UK 10"
        self.custom_overrides: Dict[str, float] = {}

        if sizes_json_path is None:
            default_path = Path(__file__).resolve().parents[2] / "data" / "sizes" / "uk_metric.json"
            if default_path.exists():
                sizes_json_path = default_path

        if sizes_json_path and Path(sizes_json_path).exists():
            self.load_size_library(sizes_json_path)

    def load_size_library(self, path: str | Path) -> None:
        with Path(path).open("r", encoding="utf-8") as f:
            data = json.load(f)

        self.system_id = str(data.get("system_id", self.system_id))
        self.system_name = str(data.get("name", self.system_name))
        self.unit = str(data.get("unit", "cm"))

        self.definitions.clear()
        for key, meta in data.get("measurement_definitions", {}).items():
            self.definitions[key] = MeasurementField(
                key=key,
                label=str(meta.get("label", key)),
                default_cm=float(meta.get("default_cm", 50.0)),
                min_cm=float(meta.get("min_cm", 1.0)),
                max_cm=float(meta.get("max_cm", 250.0)),
                description=str(meta.get("description", "")),
            )

        self.presets.clear()
        for size_name, values in data.get("sizes", {}).items():
            self.presets[size_name] = {k: float(v) for k, v in values.items()}

        if self.presets and self.active_preset not in self.presets:
            self.active_preset = next(iter(self.presets.keys()))

    def list_size_names(self) -> List[str]:
        return list(self.presets.keys())

    def select_preset(self, size_name: str, clear_overrides: bool = True) -> Dict[str, float]:
        if size_name not in self.presets:
            raise KeyError(f"Unknown size preset '{size_name}'. Available: {self.list_size_names()}")
        self.active_preset = size_name
        if clear_overrides:
            self.custom_overrides.clear()
        return self.get_active_measurements()

    def set_custom_value(self, key: str, value_cm: float) -> None:
        self.custom_overrides[key] = float(value_cm)

    def reset_overrides(self) -> None:
        self.custom_overrides.clear()

    def get_active_measurements(
        self,
        block_spec: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, float]:
        """
        Return merged measurements:
        1. Block required measurement defaults
        2. Selected standard size preset (e.g., UK 10)
        3. User custom manual overrides
        """
        merged: Dict[str, float] = {}
        if block_spec:
            for req in block_spec.get("required_measurements", []):
                merged[str(req["key"])] = float(req.get("default_cm", 0.0))

        preset_vals = self.presets.get(self.active_preset, {})
        for k, v in preset_vals.items():
            merged[k] = float(v)

        for k, v in self.custom_overrides.items():
            merged[k] = float(v)

        return merged

    def save_custom_profile(self, path: str | Path, profile_name: str, measurements: Mapping[str, float]) -> None:
        payload = {
            "profile_name": profile_name,
            "base_size": self.active_preset,
            "unit": self.unit,
            "measurements": {k: float(v) for k, v in measurements.items()},
        }
        with Path(path).open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def load_custom_profile(self, path: str | Path) -> Dict[str, float]:
        with Path(path).open("r", encoding="utf-8") as f:
            payload = json.load(f)
        if "base_size" in payload and payload["base_size"] in self.presets:
            self.active_preset = str(payload["base_size"])
        self.custom_overrides = {
            str(k): float(v) for k, v in payload.get("measurements", {}).items()
        }
        return self.get_active_measurements()
