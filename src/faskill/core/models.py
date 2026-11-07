"""Core data models for faskill library.

This module defines the SkillMetadata and Skill dataclasses that implement
the progressive disclosure pattern for memory-efficient skill management.
"""

from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

import aiologic

if TYPE_CHECKING:
    from faskill.core.processors import CompositeProcessor
    from faskill.core.scripts import ScriptMetadata


@dataclass(frozen=True, slots=True)
class CacheStats:
    """Cache statistics snapshot.

    Provides read-only metrics about cache performance and usage.
    All fields are immutable after creation.

    Attributes:
        size: Current number of cached entries
        max_size: Maximum cache capacity
        hits: Total cache hits since creation
        misses: Total cache misses since creation
        hit_rate: Calculated hit rate (hits / total requests, 0.0-1.0)

    Memory: ~80 bytes per instance
    """

    size: int
    max_size: int
    hits: int
    misses: int
    hit_rate: float


class ContentCache:
    """LRU cache for processed skill content with mtime-based invalidation.

    Thread-safe for mixed sync/async access via aiologic.Lock.  Implements
    Least Recently Used (LRU) eviction policy using OrderedDict.

    Provides both sync (``get_sync`` / ``put_sync`` / ``clear_sync``) and
    async (``get`` / ``put`` / ``clear``) accessors backed by the same lock,
    so the cache works correctly regardless of the calling context.

    Cache Key:   (skill_name: str, normalized_arguments: str)
    Cache Value: (processed_content: str, file_mtime: float)

    Performance:
        - get / get_sync:  O(1) with mtime validation
        - put / put_sync:  O(1) with LRU eviction
        - clear / clear_sync: O(n) for specific skill, O(1) for all

    Memory: ~2.1 KB per cached entry (typical), ~5 KB cache overhead

    Example:
        >>> cache = ContentCache(max_size=100)
        >>> cache.put_sync("skill-a", "args", "content", 1000.0)
        >>> cache.get_sync("skill-a", "args", 1000.0)   # Cache hit
        >>> cache.get_sync("skill-a", "args", 2000.0)   # Cache miss (stale)
    """

    def __init__(self, max_size: int = 100) -> None:
        """Initialize cache with maximum size.

        Args:
            max_size: Maximum number of entries (default 100)

        Raises:
            ValueError: If max_size <= 0
        """
        if max_size <= 0:
            raise ValueError(f"max_size must be positive, got: {max_size}")

        # Cache storage: (skill_name, normalized_args) -> (content, mtime)
        self._cache: OrderedDict[tuple[str, str], tuple[str, float]] = OrderedDict()
        self._max_size: int = max_size
        self._hits: int = 0
        self._misses: int = 0
        self._lock: aiologic.Lock = aiologic.Lock()  # Mixed sync/async safe

    #  Sync API

    def get_sync(
        self,
        skill_name: str,
        arguments: str,
        file_mtime: float,
    ) -> str | None:
        """Get cached content if valid (synchronous).

        Args:
            skill_name: Skill identifier.
            arguments: Normalized argument string.
            file_mtime: Current file modification time.

        Returns:
            Cached content if valid, ``None`` if miss or stale.
        """
        with self._lock:
            return self._get_locked(skill_name, arguments, file_mtime)

    def put_sync(
        self,
        skill_name: str,
        arguments: str,
        content: str,
        file_mtime: float,
    ) -> None:
        """Store processed content with mtime (synchronous).

        Implements LRU eviction when cache is full.
        """
        with self._lock:
            self._put_locked(skill_name, arguments, content, file_mtime)

    def clear_sync(self, skill_name: str | None = None) -> int:
        """Clear cache entries (synchronous).

        Args:
            skill_name: Clear only this skill (default: clear all).

        Returns:
            Number of entries cleared.
        """
        with self._lock:
            return self._clear_locked(skill_name)

    #  Async API

    async def get(
        self,
        skill_name: str,
        arguments: str,
        file_mtime: float,
    ) -> str | None:
        """Get cached content if valid (async)."""
        async with self._lock:
            return self._get_locked(skill_name, arguments, file_mtime)

    async def put(
        self,
        skill_name: str,
        arguments: str,
        content: str,
        file_mtime: float,
    ) -> None:
        """Store processed content with mtime (async)."""
        async with self._lock:
            self._put_locked(skill_name, arguments, content, file_mtime)

    async def clear(self, skill_name: str | None = None) -> int:
        """Clear cache entries (async)."""
        async with self._lock:
            return self._clear_locked(skill_name)

    #  Internal helpers (caller must hold self._lock)

    def _get_locked(
        self,
        skill_name: str,
        arguments: str,
        file_mtime: float,
    ) -> str | None:
        key = (skill_name, arguments)
        if key in self._cache:
            content, cached_mtime = self._cache[key]
            if cached_mtime >= file_mtime:
                # Valid cache entry — mark as recently used
                self._cache.move_to_end(key)
                self._hits += 1
                return content
            else:
                # Stale entry — invalidate
                del self._cache[key]

        self._misses += 1
        return None

    def _put_locked(
        self,
        skill_name: str,
        arguments: str,
        content: str,
        file_mtime: float,
    ) -> None:
        key = (skill_name, arguments)

        # Remove old entry if exists
        if key in self._cache:
            del self._cache[key]

        # Evict oldest entry if at capacity
        elif len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)

        # Add new entry (most recent)
        self._cache[key] = (content, file_mtime)

    def _clear_locked(self, skill_name: str | None = None) -> int:
        if skill_name is None:
            count = len(self._cache)
            self._cache.clear()
            return count

        keys_to_remove = [key for key in self._cache if key[0] == skill_name]
        for key in keys_to_remove:
            del self._cache[key]
        return len(keys_to_remove)

    #  Stats

    def get_stats(self) -> CacheStats:
        """Get cache statistics snapshot.

        Note:
            This method does **not** acquire the lock.
            Statistics may be approximate during concurrent operations.
        """
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0

        return CacheStats(
            size=len(self._cache),
            max_size=self._max_size,
            hits=self._hits,
            misses=self._misses,
            hit_rate=hit_rate,
        )


class SourceType(str, Enum):
    """Skill source type classification.

    Values define the priority order for conflict resolution:
    - PLUGIN: Plugin skills (manifest-bearing directories) - Priority 10
    - CUSTOM: All other user-configured directories - Priority 5
    """

    PLUGIN = "plugin"
    CUSTOM = "custom"


class InitMode(str, Enum):
    """Tracks SkillManager initialization state.

    Values track whether the manager was initialized synchronously or asynchronously
    to prevent mixing sync and async methods on the same instance.

    State Transitions:
        UNINITIALIZED → SYNC (via discover())
        UNINITIALIZED → ASYNC (via adiscover())
        SYNC → SYNC (no-op, already initialized)
        ASYNC → ASYNC (no-op, already initialized)
        SYNC ↛ ASYNC (ERROR: AsyncStateError)
        ASYNC ↛ SYNC (ERROR: AsyncStateError)
    """

    UNINITIALIZED = "uninitialized"
    SYNC = "sync"
    ASYNC = "async"


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    """Lightweight skill metadata loaded during discovery phase.

    Memory: ~400-800 bytes per instance (Python 3.10+)
    Immutability: frozen=True prevents accidental mutation
    Optimization: slots=True reduces memory by 60%

    Attributes:
        name: Unique skill identifier (from YAML frontmatter)
        description: Human-readable description of skill purpose
        skill_path: Absolute path to SKILL.md file
        allowed_tools: Tool names allowed for this skill (optional)
        version: Skill version string (optional, defaults to None if not specified in SKILL.md)
    """

    name: str
    description: str
    skill_path: Path
    allowed_tools: tuple[str, ...] | None = None
    version: str | None = None

    def __post_init__(self) -> None:
        """Validate skill path exists on construction.

        Raises:
            ValueError: If skill_path does not exist
        """
        if not self.skill_path.exists():
            raise ValueError(f"Skill path does not exist: {self.skill_path}")


# Note: slots=True cannot be combined with cached_property, so Skill uses only frozen=True (memory impact is minimal since content dwarfs object overhead).
@dataclass(frozen=True, slots=True)
class ResourceEntry:
    """A supporting file bundled with a skill.

    Attributes:
        relative_path: POSIX-style path relative to the skill directory.
        size: File size in bytes.
        is_script: True when the file is a detected executable script.
    """

    relative_path: str
    size: int
    is_script: bool = False


def _strip_frontmatter(content: str) -> str:
    """Return the markdown body of a SKILL.md file without its YAML frontmatter."""
    from faskill.core.parser import SkillParser

    match = SkillParser.FRONTMATTER_PATTERN.match(content)
    if match is None:
        return content.lstrip("\ufeff")
    return content[match.end() :].lstrip("\r\n")


@dataclass(frozen=True)
class Skill:
    """Full skill with lazy-loaded content (Python 3.10+).

    Memory: ~400-800 bytes wrapper + ~50-200KB content (when loaded)
    Content Loading: On-demand via @cached_property
    Processing: Via CompositeProcessor (base directory + arguments)

    Attributes:
        metadata: Lightweight metadata from discovery phase
        base_directory: Base directory context for skill execution
        _processor: Content processor chain (initialized in __post_init__)
        _scripts: Cached detected scripts (lazy-loaded)
    """

    metadata: SkillMetadata
    base_directory: Path
    _processor: "CompositeProcessor" = field(init=False, repr=False)
    _scripts: "list[ScriptMetadata] | None" = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize processor chain (avoids inline imports anti-pattern).

        Side Effects:
            Creates CompositeProcessor with BaseDirectoryProcessor + ArgumentSubstitutionProcessor
        """
        from faskill.core.processors import (
            ArgumentSubstitutionProcessor,
            BaseDirectoryProcessor,
            CompositeProcessor,
        )

        # Use object.__setattr__ because dataclass is frozen
        object.__setattr__(
            self,
            "_processor",
            CompositeProcessor(
                [
                    BaseDirectoryProcessor(),
                    ArgumentSubstitutionProcessor(),
                ]
            ),
        )

    @cached_property
    def body(self) -> str:
        """SKILL.md body with the YAML frontmatter removed.

        Frontmatter is discovery metadata and must not reach the model as
        instructions. ``content`` keeps exposing the raw file for callers
        that need it.
        """
        return _strip_frontmatter(self.content)

    @cached_property
    def content(self) -> str:
        """Lazy load content only when accessed.

        Returns:
            Full SKILL.md markdown content (UTF-8 encoded)

        Raises:
            ContentLoadError: If file cannot be read (deleted, permissions, encoding)

        Performance:
            - First access: ~10-20ms (file I/O)
            - Subsequent: <1μs (cached)
        """
        from faskill.core.exceptions import ContentLoadError

        try:
            return self.metadata.skill_path.read_text(encoding="utf-8-sig")
        except FileNotFoundError as e:
            raise ContentLoadError(
                f"Skill file not found: {self.metadata.skill_path}. "
                f"File may have been deleted after discovery."
            ) from e
        except PermissionError as e:
            raise ContentLoadError(
                f"Permission denied reading skill: {self.metadata.skill_path}"
            ) from e
        except UnicodeDecodeError as e:
            raise ContentLoadError(
                f"Skill file contains invalid UTF-8: {self.metadata.skill_path}"
            ) from e

    async def _load_content_async(self) -> str:
        """Async wrapper for content loading using asyncio.to_thread().

        Returns:
            Full SKILL.md markdown content (UTF-8 encoded)

        Raises:
            ContentLoadError: If file cannot be read

        Performance:
            - Overhead: <2ms vs sync version
            - Event loop remains responsive during I/O
        """
        import asyncio

        from faskill.core.exceptions import ContentLoadError

        def _sync_read() -> str:
            """Sync implementation for thread execution."""
            try:
                return self.metadata.skill_path.read_text(encoding="utf-8-sig")
            except FileNotFoundError as e:
                raise ContentLoadError(
                    f"Skill file not found: {self.metadata.skill_path}. "
                    f"File may have been deleted after discovery."
                ) from e
            except PermissionError as e:
                raise ContentLoadError(
                    f"Permission denied reading skill: {self.metadata.skill_path}"
                ) from e
            except UnicodeDecodeError as e:
                raise ContentLoadError(
                    f"Skill file contains invalid UTF-8: {self.metadata.skill_path}"
                ) from e

        return await asyncio.to_thread(_sync_read)

    def invoke(self, arguments: str = "") -> str:
        """Process skill content with arguments.

        Args:
            arguments: User-provided arguments for skill invocation

        Returns:
            Processed skill content with base directory + argument substitution

        Raises:
            ContentLoadError: If content cannot be loaded
            ArgumentProcessingError: If argument processing fails
            SizeLimitExceededError: If arguments exceed 1MB

        Processing Steps:
            1. Load content (lazy, cached)
            2. Inject base directory at beginning
            3. Replace $ARGUMENTS placeholders with actual arguments
            4. Return processed string

        Performance:
            - First invocation: ~10-25ms (includes content loading)
            - Subsequent: ~1-5ms (content cached, only processing)
        """
        context = {
            "arguments": arguments,
            "base_directory": str(self.base_directory),
            "skill_name": self.metadata.name,
        }
        return self._processor.process(self.body, context)

    async def ainvoke(self, arguments: str = "") -> str:
        """Async version of invoke() for non-blocking skill invocation.

        Args:
            arguments: User-provided arguments for skill invocation

        Returns:
            Processed skill content with base directory + argument substitution

        Raises:
            ContentLoadError: If content cannot be loaded
            ArgumentProcessingError: If argument processing fails
            SizeLimitExceededError: If arguments exceed 1MB

        Processing Steps:
            1. Load content asynchronously (non-blocking)
            2. Inject base directory at beginning
            3. Replace $ARGUMENTS placeholders with actual arguments
            4. Return processed string

        Performance:
            - Overhead: <2ms vs sync invoke()
            - Event loop remains responsive during file I/O
            - Suitable for concurrent invocations (10+)
        """
        # Check if content is already cached
        if "content" in self.__dict__:
            raw = self.content
        else:
            raw = await self._load_content_async()
        content = _strip_frontmatter(raw)

        context = {
            "arguments": arguments,
            "base_directory": str(self.base_directory),
            "skill_name": self.metadata.name,
        }
        return self._processor.process(content, context)

    def list_resources(self, max_depth: int = 2) -> list["ResourceEntry"]:
        """List supporting files bundled with this skill.

        Hidden entries, ``__pycache__`` and ``SKILL.md`` itself are skipped so
        the model only sees files it can actually read.

        Args:
            max_depth: Maximum path depth relative to the skill directory.

        Returns:
            Sorted list of :class:`ResourceEntry` objects.
        """
        base = self.base_directory
        if not base.is_dir():
            return []

        script_paths = {(base / script.path).resolve() for script in self.scripts}
        entries: list[ResourceEntry] = []
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(base)
            if len(relative.parts) > max_depth:
                continue
            if relative.as_posix() == "SKILL.md":
                continue
            if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            entries.append(
                ResourceEntry(
                    relative_path=relative.as_posix(),
                    size=size,
                    is_script=path.resolve() in script_paths,
                )
            )
        return sorted(entries, key=lambda entry: entry.relative_path)

    def read_resource(
        self,
        relative_path: str,
        start_line: int = 0,
        end_line: int = 0,
        *,
        max_bytes: int = 32768,
    ) -> str:
        """Read a supporting file inside the skill directory.

        Args:
            relative_path: Path relative to the skill directory.
            start_line: Zero-based first line to return.
            end_line: Exclusive last line; 0 means "until the end".
            max_bytes: Hard cap on the returned text size.

        Returns:
            The requested text, with a continuation hint when truncated.

        Raises:
            PathSecurityError: If the path escapes the skill directory.
            ContentLoadError: If the file is missing or binary.
        """
        from faskill.core.exceptions import ContentLoadError
        from faskill.core.path_resolver import FilePathResolver

        path = FilePathResolver.resolve_path(self.base_directory, relative_path)
        if not path.is_file():
            raise ContentLoadError(f"Resource not found: {relative_path}")

        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ContentLoadError(f"Cannot read resource: {relative_path}") from exc

        if b"\x00" in raw[:8192]:
            raise ContentLoadError(
                f"Resource is binary and cannot be read as text: {relative_path}"
            )

        lines = raw.decode("utf-8-sig", errors="replace").splitlines()
        total = len(lines)
        start = max(start_line, 0)
        if start >= total:
            return f"(no content at line {start}; file has {total} lines)"

        stop = total if end_line <= 0 else min(end_line, total)
        chunk = "\n".join(lines[start:stop])

        encoded = chunk.encode("utf-8")
        if len(encoded) > max_bytes:
            chunk = encoded[:max_bytes].decode("utf-8", errors="ignore")
            return (
                f"{chunk}\n\n[truncated at {max_bytes} bytes; "
                f"{total} lines total, continue with start_line={stop}]"
            )
        if stop < total:
            return f"{chunk}\n\n[lines {start}-{stop} of {total}; continue with start_line={stop}]"
        return chunk

    @property
    def scripts(self) -> "list[ScriptMetadata]":
        """Lazy load detected scripts.

        Scripts are detected once on first access and cached for the skill's lifetime.
        Detection scans the skill's scripts/ directory and root directory for executable
        scripts (.py, .sh, .js, .rb, .pl).

        Returns:
            List of ScriptMetadata instances (may be empty if no scripts found)

        Raises:
            ScriptDetectionError: If script detection fails critically

        Performance:
            - First access: ~5-10ms (directory scanning + description extraction)
            - Subsequent: <1μs (cached)

        Example:
            >>> skill.scripts
            [ScriptMetadata(name='extract', path=Path('scripts/extract.py'), ...)]
        """
        # Return cached scripts if already detected
        if self._scripts is not None:
            return self._scripts

        # Import ScriptDetector only when needed (circular dependency prevention)
        from faskill.core.scripts import ScriptDetector

        # Detect scripts and cache results
        detector = ScriptDetector()
        scripts = detector.detect_scripts(self.base_directory)

        # Use object.__setattr__ because dataclass is frozen
        object.__setattr__(self, "_scripts", scripts)

        return scripts


@dataclass(frozen=True, slots=True)
class PluginManifest:
    """Parsed metadata from .claude-plugin/plugin.json.

    Memory: ~400 bytes per instance
    Validation: Performed in __post_init__

    Attributes:
        name: Plugin identifier (must be valid Python identifier)
        version: Semantic version (e.g., "1.0.0")
        description: Plugin purpose
        author: Plugin author information
        skills: Skill directories relative to plugin root
        manifest_path: Path to plugin.json file (for error reporting)
        manifest_version: MCPB manifest version (e.g., "0.1", "0.3")
        display_name: Human-friendly plugin name (optional)
        homepage: Plugin homepage URL (optional)
        repository: Source control info (optional)
    """

    name: str
    version: str
    description: str
    author: dict[str, str]
    skills: list[str]
    manifest_path: Path
    manifest_version: str = "0.1"
    display_name: str | None = None
    homepage: str | None = None
    repository: dict[str, str] | None = None

    def __post_init__(self) -> None:
        """Validate manifest fields with security checks.

        Raises:
            ManifestValidationError: If validation fails
        """
        from faskill.core.exceptions import ManifestValidationError

        # Validate manifest version
        if self.manifest_version not in {"0.1", "0.3"}:
            raise ManifestValidationError(
                f"Unsupported manifest_version: {self.manifest_version}. "
                f"Supported versions: 0.1, 0.3",
                field_name="manifest_version",
                invalid_value=self.manifest_version,
            )

        # Validate name (must be valid identifier, no spaces)
        if not self.name or " " in self.name:
            raise ManifestValidationError(
                "Plugin name cannot be empty or contain spaces",
                field_name="name",
                invalid_value=self.name,
            )

        # Validate version (basic semver check)
        if not self.version or self.version.count(".") < 2:
            raise ManifestValidationError(
                "Version must be semver format (e.g., 1.0.0)",
                field_name="version",
                invalid_value=self.version,
            )

        # Validate description
        if not self.description or len(self.description) > 1000:
            raise ManifestValidationError(
                "Description required (max 1000 chars)",
                field_name="description",
                invalid_value=self.description if self.description else "",
            )

        # Validate author
        if not isinstance(self.author, dict) or "name" not in self.author:
            raise ManifestValidationError(
                "Author must be a dict with 'name' field",
                field_name="author",
                invalid_value=str(self.author),
            )

        # SECURITY: Validate skills paths
        for skill_path in self.skills:
            if not skill_path:
                raise ManifestValidationError(
                    "Skill path cannot be empty",
                    field_name="skills",
                    invalid_value=skill_path,
                )

            # Prevent path traversal
            if ".." in skill_path:
                raise ManifestValidationError(
                    f"Security violation: Path contains '..': {skill_path}",
                    field_name="skills",
                    invalid_value=skill_path,
                )

            # Prevent absolute paths
            if skill_path.startswith("/") or skill_path.startswith("\\"):
                raise ManifestValidationError(
                    f"Security violation: Path must be relative: {skill_path}",
                    field_name="skills",
                    invalid_value=skill_path,
                )

            # Windows: Prevent drive letters
            if len(skill_path) >= 2 and skill_path[1] == ":":
                raise ManifestValidationError(
                    f"Security violation: Drive letters not allowed: {skill_path}",
                    field_name="skills",
                    invalid_value=skill_path,
                )


@dataclass(frozen=True, slots=True)
class SkillSource:
    """Represents a skill source location with priority and metadata.

    Memory: ~200 bytes per instance
    Immutability: frozen=True prevents accidental mutation

    Attributes:
        source_type: Enum: PROJECT | ANTHROPIC | PLUGIN | CUSTOM
        directory: Absolute path to skill root directory
        priority: Priority for conflict resolution (higher = wins)
        plugin_name: Plugin namespace (only for PLUGIN type)
        plugin_manifest: Parsed manifest (only for PLUGIN type)
    """

    source_type: SourceType
    directory: Path
    priority: int
    plugin_name: str | None = None
    plugin_manifest: PluginManifest | None = None

    def __post_init__(self) -> None:
        """Validate source configuration.

        Raises:
            ValueError: If validation fails
        """
        # Validate directory exists
        if not self.directory.exists():
            raise ValueError(f"Source directory does not exist: {self.directory}")

        if not self.directory.is_dir():
            raise ValueError(f"Source path is not a directory: {self.directory}")

        # Validate priority is positive
        if self.priority <= 0:
            raise ValueError(f"Priority must be positive, got: {self.priority}")

        # Validate plugin-specific constraints
        if self.source_type == SourceType.PLUGIN and self.plugin_name is None:
            raise ValueError("plugin_name required when source_type == PLUGIN")


@dataclass(frozen=True, slots=True)
class QualifiedSkillName:
    """Skill identifier with optional plugin namespace.

    Format: "plugin:skill" (qualified) or "skill" (unqualified)

    Attributes:
        plugin: Plugin name (if qualified)
        skill: Skill name
    """

    plugin: str | None
    skill: str

    @staticmethod
    def parse(name: str) -> "QualifiedSkillName":
        """Parse qualified or unqualified skill name.

        Args:
            name: Skill name in format "plugin:skill" or "skill"

        Returns:
            QualifiedSkillName with plugin and skill parts

        Raises:
            ValueError: If name format is invalid

        Examples:
            >>> QualifiedSkillName.parse("csv-parser")
            QualifiedSkillName(plugin=None, skill="csv-parser")

            >>> QualifiedSkillName.parse("data-tools:csv-parser")
            QualifiedSkillName(plugin="data-tools", skill="csv-parser")
        """
        if not name:
            raise ValueError("Skill name cannot be empty")

        # Check for qualified name
        if ":" in name:
            parts = name.split(":", 1)
            if len(parts) != 2:
                raise ValueError(f"Invalid qualified name format: {name}")

            plugin, skill = parts

            if not plugin or not skill:
                raise ValueError(f"Invalid qualified name (empty plugin or skill): {name}")

            return QualifiedSkillName(plugin=plugin, skill=skill)

        # Unqualified name
        return QualifiedSkillName(plugin=None, skill=name)
