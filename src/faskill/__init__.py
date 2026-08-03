"""faskill: Python library for Anthropic's Agent Skills functionality.

This library implements multi-source skill discovery, YAML frontmatter parsing,
progressive disclosure pattern, and framework integrations for LLM-powered agents.
"""

import importlib.metadata
import logging
from pathlib import Path
from typing import List

# Add NullHandler to prevent "No handlers found" warnings (Python library standard)
logging.getLogger(__name__).addHandler(logging.NullHandler())

# Public API exports
from faskill.core.exceptions import (
    ArgumentProcessingError,
    ArgumentSerializationError,
    ArgumentSizeError,
    ContentLoadError,
    InterpreterNotFoundError,
    InvalidFrontmatterError,
    InvalidSkillNameError,
    InvalidYAMLError,
    MissingRequiredFieldError,
    PathSecurityError,
    ScriptNotFoundError,
    ScriptPermissionError,
    SizeLimitExceededError,
    SkillInvocationError,
    SkillNotFoundError,
    SkillParsingError,
    SkillSecurityError,
    SkillsUseError,
    SuspiciousInputError,
    ToolIDValidationError,
)
from faskill.core.manager import SkillContext
from faskill.core.models import Skill, SkillMetadata
from faskill.core.path_resolver import FilePathResolver
from faskill.core.scripts import ScriptExecutionResult, ScriptMetadata

__version__ = importlib.metadata.version("faskill")


def create_context(
    skill_dirs: List[Path | str] | None = None,
    *,
    default_script_timeout: int = 30,
    max_cache_size: int = 100,
    plugin_manifest_name: str = ".claude-plugin/plugin.json",
) -> SkillContext:
    """Create a new SkillContext (recommended entry point).

    Args:
        skill_dirs: List of skill directories.  Each is treated as CUSTOM
            unless it contains a plugin manifest.  If None/omitted the
            context starts with zero sources.
        default_script_timeout: Default timeout for script execution (seconds).
        max_cache_size: Max LRU cache entries for invocation results.
        plugin_manifest_name: Relative path marking a directory as a plugin.

    Returns:
        A ready-to-use SkillContext instance (call ``discover()`` or
        ``adiscover()`` before querying skills).
    """
    return SkillContext(
        skill_dirs=skill_dirs,
        default_script_timeout=default_script_timeout,
        max_cache_size=max_cache_size,
        plugin_manifest_name=plugin_manifest_name,
    )


__all__ = [
    # Factory
    "create_context",
    # Core classes
    "SkillContext",
    "SkillMetadata",
    "Skill",
    "FilePathResolver",
    # Script classes (v0.3+)
    "ScriptMetadata",
    "ScriptExecutionResult",
    # Base exceptions
    "SkillsUseError",
    "SkillParsingError",
    "SkillInvocationError",
    "SkillSecurityError",
    # Parsing exceptions
    "InvalidYAMLError",
    "MissingRequiredFieldError",
    "InvalidFrontmatterError",
    "InvalidSkillNameError",
    # Runtime exceptions
    "SkillNotFoundError",
    "ArgumentProcessingError",
    "ContentLoadError",
    # Security exceptions
    "SuspiciousInputError",
    "SizeLimitExceededError",
    "PathSecurityError",
    # Script exceptions (v0.3+)
    "InterpreterNotFoundError",
    "ScriptNotFoundError",
    "ScriptPermissionError",
    "ArgumentSerializationError",
    "ArgumentSizeError",
    "ToolIDValidationError",
]
