"""Core module for faskill library.

This module contains the framework-agnostic core functionality with zero
framework dependencies (stdlib + PyYAML only).
"""

from faskill.core.discovery import SkillDiscovery
from faskill.core.exceptions import (
    ArgumentProcessingError,
    ContentLoadError,
    InvalidFrontmatterError,
    InvalidYAMLError,
    MissingRequiredFieldError,
    SizeLimitExceededError,
    SkillInvocationError,
    SkillNotFoundError,
    SkillParsingError,
    SkillSecurityError,
    SkillsUseError,
    SuspiciousInputError,
)
from faskill.core.manager import SkillContext
from faskill.core.models import CacheStats, ContentCache, Skill, SkillMetadata
from faskill.core.parser import SkillParser
from faskill.core.processors import (
    ArgumentSubstitutionProcessor,
    BaseDirectoryProcessor,
    CompositeProcessor,
    ContentProcessor,
    normalize_arguments,
    process_skill_content,
)
from faskill.core.runner import HostRunner, Runner

__all__ = [
    # Core classes
    "SkillContext",
    "SkillMetadata",
    "Skill",
    "SkillDiscovery",
    "SkillParser",
    # Cache
    "ContentCache",
    "CacheStats",
    # Processors
    "ContentProcessor",
    "BaseDirectoryProcessor",
    "ArgumentSubstitutionProcessor",
    "CompositeProcessor",
    "normalize_arguments",
    "process_skill_content",
    # Runner
    "Runner",
    "HostRunner",
    # Exceptions
    "SkillsUseError",
    "SkillParsingError",
    "InvalidYAMLError",
    "MissingRequiredFieldError",
    "InvalidFrontmatterError",
    "SkillNotFoundError",
    "SkillInvocationError",
    "ArgumentProcessingError",
    "ContentLoadError",
    "SkillSecurityError",
    "SuspiciousInputError",
    "SizeLimitExceededError",
]
