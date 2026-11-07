"""Skill context — thin orchestration facade.

This module provides SkillContext, the main entry point for skill
discovery, access, invocation, and script execution.  It delegates
heavy lifting to SkillRegistry, SkillInvoker, SkillDiscovery,
SkillParser, and ScriptExecutor.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Literal, overload

from faskill.core.discovery import SkillDiscovery, discover_plugin_manifest
from faskill.core.exceptions import (
    AsyncStateError,
    ConfigurationError,
    SkillsUseError,
)
from faskill.core.invoker import SkillInvoker
from faskill.core.models import (
    CacheStats,
    InitMode,
    Skill,
    SkillMetadata,
    SkillSource,
    SourceType,
)
from faskill.core.parser import SkillParser
from faskill.core.registry import SkillRegistry

logger = logging.getLogger(__name__)

PRIORITY_PLUGIN = 10
PRIORITY_CUSTOM = 5


class SkillContext:
    """Central skill context with discovery, invocation, and script execution.

    Discovery:  graceful degradation (log errors, continue processing).
    Invocation: strict validation (raise specific exceptions).

    All skill directories are treated as CUSTOM sources with equal priority,
    unless they contain a plugin manifest (then PLUGIN, priority 10).

    Priority order:  PLUGIN (10) > CUSTOM (5).
    For custom dirs the caller controls ordering — first wins on conflict.

    Example::

        ctx = SkillContext(skill_dirs=["./my-skills", "./plugins/pdf-tools"])
        ctx.discover()
        result = ctx.invoke_skill("code-reviewer", "review main.py")
    """

    def __init__(
        self,
        skill_dirs: List[Path | str] | None = None,
        *,
        default_script_timeout: int = 30,
        max_cache_size: int = 100,
        plugin_manifest_name: str = ".claude-plugin/plugin.json",
    ) -> None:
        """Initialise the skill context.

        Args:
            skill_dirs: List of skill directories (each treated as CUSTOM
                unless it contains a plugin manifest).  If None/omitted
                the context starts with zero sources — call ``add_source()``
                or pass explicit paths.
            default_script_timeout: Default timeout (seconds) for
                ``execute_skill_script()``.  Range 1-600.
            max_cache_size: Max cached invocation entries.
            plugin_manifest_name: Relative path inside a directory that
                marks it as a plugin (e.g. ``".claude-plugin/plugin.json"``).
        """
        if not (1 <= default_script_timeout <= 600):
            raise ValueError("default_script_timeout must be 1-600")

        self._sources: list[SkillSource] = []
        self._plugin_manifest_name = plugin_manifest_name

        if skill_dirs:
            self._sources = self._build_sources(skill_dirs)

        self._registry = SkillRegistry()
        self._invoker = SkillInvoker(max_cache_size=max_cache_size)
        self._discovery = SkillDiscovery()
        self._parser = SkillParser()

        self._init_mode = InitMode.UNINITIALIZED
        self._default_script_timeout = default_script_timeout

        if not self._sources:
            logger.info("No skill directories configured; initialised with empty skill list")

    # Source management

    def add_source(self, path: Path | str, *, priority: int = PRIORITY_CUSTOM) -> None:
        """Add a skill directory after construction.

        Automatically detected as PLUGIN if a manifest exists.
        """
        p = Path(path).resolve()
        if not p.is_dir():
            raise ConfigurationError(
                f"Directory does not exist: '{p}'",
                parameter_name="path",
                invalid_path=str(p),
            )

        detection = _detect_plugin(p, self._plugin_manifest_name)
        if detection is not None:
            src_type, plugin_name, plugin_manifest = detection
            source = SkillSource(
                source_type=src_type,
                directory=p,
                priority=PRIORITY_PLUGIN,
                plugin_name=plugin_name,
                plugin_manifest=plugin_manifest,
            )
        else:
            source = SkillSource(
                source_type=SourceType.CUSTOM,
                directory=p,
                priority=priority,
            )
        self._sources.append(source)
        self._sources.sort(key=lambda s: s.priority, reverse=True)

    # Initialisation

    @property
    def init_mode(self) -> InitMode:
        return self._init_mode

    def discover(self) -> None:
        """Discover skills from all configured sources (sync)."""
        if self._init_mode == InitMode.ASYNC:
            raise AsyncStateError(
                "Context was initialised with adiscover() (async mode). "
                "Cannot mix sync and async methods. Create a new context."
            )
        self._init_mode = InitMode.SYNC
        self._do_discover()

    async def adiscover(self) -> None:
        """Discover skills from all configured sources (async)."""
        if self._init_mode == InitMode.SYNC:
            raise AsyncStateError(
                "Context was initialised with discover() (sync mode). "
                "Cannot mix sync and async methods. Create a new context."
            )
        self._init_mode = InitMode.ASYNC
        await self._ado_discover()

    # Listing & lookup

    @overload
    def list_skills(self, /) -> list[SkillMetadata]:  # Default behavior
        """Return discovered skill metadata."""

    @overload
    def list_skills(self, include_qualified: Literal[False]) -> list[SkillMetadata]:  # Not included
        """Return discovered skill metadata or qualified names."""

    @overload
    def list_skills(self, include_qualified: Literal[True]) -> list[str]:  # Included
        """Return discovered skill metadata or qualified names."""

    def list_skills(self, include_qualified: bool = False) -> list[SkillMetadata] | list[str]:
        """Return discovered skill metadata or qualified names.

        Args:
            include_qualified: If True, return a list of name strings
                (including ``plugin:skill`` for shadowed plugins).

        Returns:
            List of SkillMetadata (default) or list of str.
        """
        if include_qualified:
            return self._registry.list_names()
        return self._registry.list_metadata()

    def get_skill(self, name: str) -> SkillMetadata:
        """Get skill metadata by name.

        Supports ``"skill"`` and ``"plugin:skill"`` qualified names.

        Raises:
            SkillNotFoundError: If not registered.
        """
        return self._registry.get(name)

    def load_skill(self, name: str) -> Skill:
        """Load full Skill instance (content loaded lazily)."""
        metadata = self.get_skill(name)
        return Skill(metadata=metadata, base_directory=metadata.skill_path.parent)

    # Progressive disclosure

    def open_skill(
        self,
        name: str,
        arguments: str = "",
        section: str = "",
        *,
        max_chars: int = 12000,
    ) -> str:
        """Load a skill's instructions for progressive disclosure (L2).

        Returns the body without frontmatter, applies ``$ARGUMENTS`` when
        present, slices a heading when requested, and lists the supporting
        files the model can read next. Absolute paths are never exposed.

        Args:
            name: Skill name.
            arguments: Optional user request inserted into ``$ARGUMENTS``.
            section: Optional heading to slice; empty means the whole body.
            max_chars: Character budget before truncation.

        Returns:
            A model-facing text block.
        """
        skill = self.load_skill(name)
        body = skill.body
        has_placeholder = "$ARGUMENTS" in body
        if arguments and has_placeholder:
            body = body.replace("$ARGUMENTS", arguments)

        text = body
        if section:
            sliced = _slice_section(body, section)
            if sliced is None:
                headings = _list_headings(body)
                available = "\n".join(headings) if headings else "(no headings)"
                return (
                    f"[skill: {name}]\n"
                    f"Section not found: {section}. Available sections:\n{available}"
                )
            text = sliced

        headings = _list_headings(text)
        truncated = len(text) > max_chars
        keep = 0
        if truncated:
            cut = text.rfind("\n", 0, max_chars)
            keep = cut if cut > 0 else max_chars
            text = text[:keep]

        parts = [f"[skill: {name}]", text.strip()]
        if truncated:
            parts.append(f"[truncated at {keep} characters]")
            if headings:
                parts.append("Sections:\n" + "\n".join(headings))

        if arguments and not has_placeholder:
            parts.append(f"[user request]\n{arguments}")

        resources = skill.list_resources()
        if resources:
            lines = ["[files in this skill; read with skill_read]"]
            for entry in resources:
                marker = " (script)" if entry.is_script else ""
                lines.append(f"- {entry.relative_path} ({_human_size(entry.size)}){marker}")
            parts.append("\n".join(lines))

        return "\n\n".join(part for part in parts if part)

    def read_skill_resource(
        self,
        name: str,
        relative_path: str,
        start_line: int = 0,
        end_line: int = 0,
    ) -> str:
        """Read a supporting file of a skill (progressive disclosure L3)."""
        skill = self.load_skill(name)
        return skill.read_resource(relative_path, start_line, end_line)

    # Invocation

    def invoke_skill(self, name: str, arguments: str = "") -> str:
        """Invoke a skill (sync) with LRU caching."""
        skill = self.load_skill(name)
        return self._invoker.invoke_sync(skill, arguments)

    async def ainvoke_skill(self, name: str, arguments: str = "") -> str:
        """Invoke a skill (async) with LRU caching.

        Raises:
            AsyncStateError: If initialised via ``discover()`` (sync).
        """
        if self._init_mode == InitMode.SYNC:
            raise AsyncStateError(
                "Context was initialised with discover() (sync mode). "
                "Use invoke_skill() or create a new context and call adiscover()."
            )
        if self._init_mode == InitMode.UNINITIALIZED:
            raise SkillsUseError(
                "Context not initialised. Call adiscover() before invoking skills."
            )
        skill = self.load_skill(name)
        return await self._invoker.invoke(skill, arguments)

    # Cache

    def get_cache_stats(self) -> CacheStats:
        return self._invoker.get_stats()

    def clear_cache(self, skill_name: str | None = None) -> int:
        return self._invoker.clear_cache(skill_name)

    async def aclear_cache(self, skill_name: str | None = None) -> int:
        return await self._invoker.aclear_cache(skill_name)

    # Script execution

    def execute_skill_script(
        self,
        skill_name: str,
        script_name: str,
        arguments: Dict[str, Any],
        timeout: int | None = None,
    ):
        """Execute a specific script from a skill.

        Args:
            skill_name: Skill name.
            script_name: Script name (without extension).
            arguments: JSON-serialisable dict → stdin.
            timeout: Override default timeout (seconds).

        Returns:
            ScriptExecutionResult.
        """
        from faskill.core.exceptions import ScriptNotFoundError
        from faskill.core.scripts import ScriptExecutor

        if self._init_mode == InitMode.UNINITIALIZED:
            raise SkillsUseError("Context not initialised. Call discover() or adiscover() first.")

        skill = self.load_skill(skill_name)

        script_meta = None
        for s in skill.scripts:
            if s.name == script_name:
                script_meta = s
                break

        if script_meta is None:
            available = ", ".join(s.name for s in skill.scripts) or "none"
            raise ScriptNotFoundError(
                f"Script '{script_name}' not found in skill '{skill_name}'. Available: {available}"
            )

        effective_timeout = timeout if timeout is not None else self._default_script_timeout
        normalised_args = {k.lower(): v for k, v in arguments.items()}

        executor = ScriptExecutor(timeout=effective_timeout)
        return executor.execute(
            script_path=script_meta.path,
            arguments=normalised_args,
            skill_base_dir=skill.base_directory,
            skill_metadata=skill.metadata,
        )

    # Internal

    def _build_sources(self, skill_dirs: List[Path | str]) -> list[SkillSource]:
        sources: list[SkillSource] = []

        for d in skill_dirs:
            p = Path(d).resolve()
            if not p.is_dir():
                raise ConfigurationError(
                    f"Explicitly configured directory does not exist: '{p}'",
                    parameter_name="skill_dirs",
                    invalid_path=str(p),
                )
            detection = _detect_plugin(p, self._plugin_manifest_name)
            if detection is not None:
                src_type, plugin_name, plugin_manifest = detection
                source = SkillSource(
                    source_type=src_type,
                    directory=p,
                    priority=PRIORITY_PLUGIN,
                    plugin_name=plugin_name,
                    plugin_manifest=plugin_manifest,
                )
            else:
                source = SkillSource(
                    source_type=SourceType.CUSTOM,
                    directory=p,
                    priority=PRIORITY_CUSTOM,
                )
            sources.append(source)

        sources.sort(key=lambda s: s.priority, reverse=True)
        return sources

    def _do_discover(self) -> None:
        logger.info("Starting skill discovery (sync)")
        self._registry.clear()
        total = 0

        for src in self._sources:
            skill_files = self._discovery.discover_skills(src)
            if not skill_files:
                logger.debug("No skills found in %s", src.directory)
                continue

            for sf in skill_files:
                try:
                    metadata = self._parser.parse_skill_file(sf)
                    if self._registry.register(metadata, src, self._sources):
                        total += 1
                except SkillsUseError as e:
                    logger.error("Failed to parse skill at %s: %s", sf, e, exc_info=True)
                except Exception as e:
                    logger.error("Unexpected error parsing %s: %s", sf, e, exc_info=True)

        logger.info(
            "Discovery complete: %d skill(s) from %d source(s)",
            total,
            len(self._sources),
        )

    async def _ado_discover(self) -> None:
        logger.info("Starting skill discovery (async)")
        self._registry.clear()
        total = 0

        for src in self._sources:
            skill_files = await self._discovery.adiscover_skills(src)
            if not skill_files:
                logger.debug("No skills found in %s", src.directory)
                continue

            for sf in skill_files:
                try:
                    metadata = self._parser.parse_skill_file(sf)
                    if self._registry.register(metadata, src, self._sources):
                        total += 1
                except SkillsUseError as e:
                    logger.error("Failed to parse skill at %s: %s", sf, e, exc_info=True)
                except Exception as e:
                    logger.error("Unexpected error parsing %s: %s", sf, e, exc_info=True)

        logger.info(
            "Async discovery complete: %d skill(s) from %d source(s)",
            total,
            len(self._sources),
        )


# Module-private helper


def _detect_plugin(
    directory: Path,
    manifest_name: str,
) -> tuple[SourceType, str, Any] | None:
    """Try to discover a plugin manifest.

    Returns (SourceType.PLUGIN, plugin_name, PluginManifest) or None.
    """
    manifest = discover_plugin_manifest(directory, manifest_name)
    if manifest:
        return (SourceType.PLUGIN, manifest.name, manifest)
    return None


_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)


def _list_headings(text: str) -> list[str]:
    """Return at most 40 markdown headings from ``text``."""
    return [f"{match.group(1)} {match.group(2)}" for match in _HEADING_RE.finditer(text)][:40]


def _slice_section(text: str, section: str) -> str | None:
    """Return the section under ``section`` (case-insensitive, partial match)."""
    target = section.strip().lstrip("#").strip().lower()
    matches = list(_HEADING_RE.finditer(text))
    for index, match in enumerate(matches):
        title = match.group(2).strip().lower()
        if title != target and target not in title:
            continue
        level = len(match.group(1))
        end = len(text)
        for later in matches[index + 1 :]:
            if len(later.group(1)) <= level:
                end = later.start()
                break
        return text[match.start() : end].strip()
    return None


def _human_size(size: int) -> str:
    """Format a byte count for model-facing file listings."""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"
