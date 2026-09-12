"""Versioned, inert extension contracts for the DeepTwin web framework."""

from .contracts import (
    EXTENSION_KINDS,
    ExtensionBinding,
    ExtensionContractError,
    ExtensionInstallation,
    ExtensionManifest,
    ExtensionQualification,
    ExtensionScope,
    RuntimeBoundaryUnavailable,
)
from .registry import ExtensionRegistry
from .schema_exports import extension_schemas

__all__ = (
    "EXTENSION_KINDS",
    "ExtensionBinding",
    "ExtensionContractError",
    "ExtensionInstallation",
    "ExtensionManifest",
    "ExtensionQualification",
    "ExtensionRegistry",
    "ExtensionScope",
    "RuntimeBoundaryUnavailable",
    "extension_schemas",
)
