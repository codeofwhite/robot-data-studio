from __future__ import annotations

import os

from .base import CollectionAdapter
from .clothtwin import ClothTwinAdapter
from .isaac_sim import IsaacSimAdapter
from .roboverse import RoboVerseAdapter


_ENGINES: dict[str, CollectionAdapter] = {
    "genesis": ClothTwinAdapter(),
    "isaac_sim": IsaacSimAdapter(),
    "roboverse": RoboVerseAdapter(),
}
# An explicit deployment selection avoids probing plugins that are not installed.
# Without this setting, preserve the existing three-engine registry.
_requested_engines = os.environ.get("ROBOT_DATA_STUDIO_ENABLED_ENGINES")
if _requested_engines is not None:
    _enabled_ids = [item.strip() for item in _requested_engines.split(",")]
    if not all(_enabled_ids) or any(item not in _ENGINES for item in _enabled_ids):
        raise ValueError(
            "ROBOT_DATA_STUDIO_ENABLED_ENGINES must list known engine IDs: "
            + ", ".join(_ENGINES)
        )
    _ENGINES = {item: _ENGINES[item] for item in _enabled_ids}


_ALIASES = {"clothtwin": "genesis"}


def canonical_engine_id(engine_id: str) -> str:
    return _ALIASES.get(engine_id, engine_id)


def get_engine(engine_id: str) -> CollectionAdapter:
    canonical = canonical_engine_id(engine_id)
    try:
        return _ENGINES[canonical]
    except KeyError:
        raise ValueError(f"unsupported engine: {engine_id}") from None


def engine_descriptors() -> list[dict]:
    return [adapter.descriptor() for adapter in _ENGINES.values()]


__all__ = [
    "ClothTwinAdapter",
    "IsaacSimAdapter",
    "RoboVerseAdapter",
    "canonical_engine_id",
    "engine_descriptors",
    "get_engine",
]
