from __future__ import annotations

from .base import CollectionAdapter
from .clothtwin import ClothTwinAdapter
from .isaac_sim import IsaacSimAdapter


_ENGINES: dict[str, CollectionAdapter] = {
    "genesis": ClothTwinAdapter(),
    "isaac_sim": IsaacSimAdapter(),
}
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
    "canonical_engine_id",
    "engine_descriptors",
    "get_engine",
]
