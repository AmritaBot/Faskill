"""Skill registry for name resolution, conflict detection, and listing.

This module provides SkillRegistry — the single source of truth for
discovered skills. It owns the internal dictionaries, handles
priority-based conflict resolution, and supports qualified name lookups.
"""

import logging
from typing import Dict

from faskill.core.models import (
    QualifiedSkillName,
    SkillMetadata,
    SkillSource,
    SourceType,
)

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Central skill name registry with multi-source conflict resolution.

    Owns the master skill dictionaries (_skills and _plugin_skills).
    Stateless aside from the registries — does not know about discovery
    or filesystem scanning.

    Attributes:
        _skills: Main registry (name → metadata), highest-priority wins
        _plugin_skills: Plugin-namespaced registry (plugin_name → name → metadata)
    """

    def __init__(self) -> None:
        self._skills: Dict[str, SkillMetadata] = {}
        self._plugin_skills: Dict[str, Dict[str, SkillMetadata]] = {}

    # Registration

    def register(
        self,
        metadata: SkillMetadata,
        source: SkillSource,
        all_sources: list[SkillSource],
    ) -> bool:
        """Register a skill, resolving conflicts by priority.

        Args:
            metadata: Parsed skill metadata.
            source: The source this skill was discovered in.
            all_sources: All configured sources (for conflict logging).

        Returns:
            True if the skill was registered (new or higher priority);
            False if it was ignored (lower-priority duplicate).

        Side Effects:
            Logs WARNING on conflicts, DEBUG on successful registration.
            Populates _plugin_skills for PLUGIN sources.
        """
        # Store in plugin namespace for PLUGIN sources
        if source.source_type == SourceType.PLUGIN and source.plugin_name:
            plugin_name = source.plugin_name
            if plugin_name not in self._plugin_skills:
                self._plugin_skills[plugin_name] = {}
            self._plugin_skills[plugin_name][metadata.name] = metadata
            logger.debug(
                "Registered plugin skill: %s:%s from %s",
                plugin_name,
                metadata.name,
                source.directory,
            )

        # Conflict detection
        if metadata.name in self._skills:
            existing = self._skills[metadata.name]
            existing_source = _find_source(existing.skill_path, all_sources)

            existing_type = existing_source.source_type.value if existing_source else "unknown"
            existing_priority = existing_source.priority if existing_source else "unknown"

            qualified_hint = ""
            if source.source_type == SourceType.PLUGIN and source.plugin_name:
                qualified_hint = (
                    f" Use qualified name '{source.plugin_name}:{metadata.name}' "
                    f"to access the ignored version."
                )

            logger.warning(
                f"Skill name conflict detected for '{metadata.name}':\n"
                f"  KEEPING: {existing.skill_path} "
                f"(source: {existing_type}, priority: {existing_priority})\n"
                f"  IGNORING: {metadata.skill_path} "
                f"(source: {source.source_type.value}, priority: {source.priority})\n"
                f"  RESOLUTION: Higher priority source wins.{qualified_hint}"
            )
            return False

        # Register
        self._skills[metadata.name] = metadata
        logger.debug("Registered skill: %s from %s", metadata.name, source.source_type.value)
        return True

    def clear(self) -> None:
        """Remove all registered skills."""
        self._skills.clear()
        self._plugin_skills.clear()

    # Lookup

    def get(self, name: str) -> SkillMetadata:
        """Get skill metadata by name (strict validation).

        Supports both simple names and fully qualified names (plugin:skill).

        Args:
            name: Skill name — "skill" or "plugin:skill".

        Returns:
            SkillMetadata instance.

        Raises:
            SkillNotFoundError: If the name is not in any registry.

        Performance:
            O(1) dictionary lookup (~1µs).
        """
        from faskill.core.exceptions import SkillNotFoundError

        try:
            parsed = QualifiedSkillName.parse(name)
        except ValueError as e:
            raise SkillNotFoundError(str(e)) from e

        if parsed.plugin is not None:
            return self._get_qualified(parsed.plugin, parsed.skill)

        if parsed.skill not in self._skills:
            available = ", ".join(self._skills.keys()) if self._skills else "none"
            raise SkillNotFoundError(
                f"Skill '{parsed.skill}' not found. Available skills: {available}"
            )
        return self._skills[parsed.skill]

    def _get_qualified(self, plugin: str, skill: str) -> SkillMetadata:
        """Resolve a plugin:skill qualified name."""
        from faskill.core.exceptions import SkillNotFoundError

        if plugin not in self._plugin_skills:
            available_plugins = (
                ", ".join(self._plugin_skills.keys()) if self._plugin_skills else "none"
            )
            raise SkillNotFoundError(
                f"Plugin '{plugin}' not found. Available plugins: {available_plugins}"
            )

        if skill not in self._plugin_skills[plugin]:
            available_skills = ", ".join(self._plugin_skills[plugin].keys())
            raise SkillNotFoundError(
                f"Skill '{skill}' not found in plugin '{plugin}'. "
                f"Available skills in this plugin: {available_skills}"
            )

        return self._plugin_skills[plugin][skill]

    # Listing

    def list_metadata(self) -> list[SkillMetadata]:
        """Return all registered skill metadata (lightweight).

        Performance:
            O(n) copy of internal list.
        """
        return list(self._skills.values())

    def list_names(self) -> list[str]:
        """Return skill names, including qualified names for shadowed plugins.

        Only qualified names are emitted for plugin skills that differ from
        the version that won the conflict in the main registry.
        """
        names: list[str] = list(self._skills.keys())

        for plugin_name, plugin_skills in self._plugin_skills.items():
            for skill_name, skill_meta in plugin_skills.items():
                if skill_name in self._skills:
                    main_skill = self._skills[skill_name]
                    if main_skill.skill_path != skill_meta.skill_path:
                        names.append(f"{plugin_name}:{skill_name}")

        return names

    # Introspection

    @property
    def count(self) -> int:
        """Number of skills in the main registry."""
        return len(self._skills)

    @property
    def plugin_count(self) -> int:
        """Number of plugin namespaces."""
        return len(self._plugin_skills)

    def __len__(self) -> int:
        return self.count

    def __contains__(self, name: str) -> bool:
        return name in self._skills


# Internal helper


def _find_source(
    skill_path: str | object,
    sources: list[SkillSource],
) -> SkillSource | None:
    """Find which SkillSource a skill_path belongs to (best-effort)."""
    path_str = str(skill_path)
    for s in sources:
        if str(s.directory) in path_str:
            return s
    return None
