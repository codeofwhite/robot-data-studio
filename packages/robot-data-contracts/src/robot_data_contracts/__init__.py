"""Versioned, runtime-light contracts shared by Studio collection workers."""

from .scene import (
    SceneDescriptor,
    SceneParameter,
    ScenePlugin,
    ScenePluginDescriptor,
    SceneRuntime,
)

__all__ = [
    "SceneDescriptor",
    "SceneParameter",
    "ScenePlugin",
    "ScenePluginDescriptor",
    "SceneRuntime",
]
