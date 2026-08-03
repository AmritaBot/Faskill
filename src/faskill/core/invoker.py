"""Skill invoker with LRU caching and async support.

This module provides SkillInvoker — responsible for loading skill content,
processing it with arguments, and caching results.  It is decoupled from
discovery and registry concerns.

The cache (ContentCache) uses ``aiologic.Lock`` so it works correctly in
**both** sync and async contexts without ``asyncio.run()`` bridges.
Sync code calls ``_cache.get_sync()`` / ``_cache.put_sync()`` directly;
async code uses the ``async with``-based accessors.
"""

import asyncio
import logging
from pathlib import Path

import aiofiles
import aiofiles.os

from faskill.core.models import ContentCache, Skill
from faskill.core.processors import normalize_arguments, process_skill_content

logger = logging.getLogger(__name__)


class SkillInvoker:
    """Load, process, and cache skill invocations.

    Owns the ContentCache and per-skill invocation locks (async only).

    Sync methods use the ContentCache's sync API backed by
    ``aiologic.Lock``, so caching works regardless of whether an event
    loop is already running — no ``asyncio.run()`` or loop-detection
    hacks needed.

    Attributes:
        _cache: LRU ContentCache for processed content.
        _skill_locks: Per-skill asyncio.Lock for async concurrency safety.
        _locks_lock: Mutex for _skill_locks dictionary.
    """

    def __init__(
        self,
        max_cache_size: int = 100,
    ) -> None:
        if max_cache_size <= 0:
            raise ValueError("max_cache_size must be positive")
        self._cache = ContentCache(max_size=max_cache_size)
        self._skill_locks: dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()

    #  Public API

    async def invoke(
        self,
        skill: Skill,
        arguments: str = "",
    ) -> str:
        """Async invocation with caching and per-skill locking.

        Args:
            skill: Full Skill instance (metadata already resolved).
            arguments: User arguments string.

        Returns:
            Processed skill content.

        Raises:
            ContentLoadError, ArgumentProcessingError, SizeLimitExceededError.
        """
        lock = await self._get_skill_lock(skill.metadata.name)

        async with lock:
            file_path = skill.metadata.skill_path
            normalized_args = normalize_arguments(arguments)
            current_mtime = await self._get_file_mtime(file_path)

            cached = await self._cache.get(skill.metadata.name, normalized_args, current_mtime)
            if cached is not None:
                return cached

            # Cache miss — load & process
            from faskill.core.exceptions import ContentLoadError

            try:
                async with aiofiles.open(file_path, encoding="utf-8-sig") as f:
                    raw_content = await f.read()
            except FileNotFoundError as e:
                raise ContentLoadError(
                    f"Skill file not found: {file_path}. "
                    f"File may have been deleted after discovery."
                ) from e
            except PermissionError as e:
                raise ContentLoadError(f"Permission denied reading skill: {file_path}") from e
            except UnicodeDecodeError as e:
                raise ContentLoadError(f"Skill file contains invalid UTF-8: {file_path}") from e

            processed = process_skill_content(raw_content, skill.base_directory, arguments)
            await self._cache.put(skill.metadata.name, normalized_args, processed, current_mtime)
            return processed

    def invoke_sync(
        self,
        skill: Skill,
        arguments: str = "",
    ) -> str:
        """Synchronous invocation with caching — safe in any context.

        Uses ``ContentCache.get_sync()`` / ``put_sync()`` backed by
        ``aiologic.Lock``, so caching works correctly even when called
        from within a running event loop (no ``asyncio.run()`` bridge
        or ``get_running_loop()`` detection required).

        Args:
            skill: Full Skill instance.
            arguments: User arguments string.

        Returns:
            Processed skill content.

        Raises:
            ContentLoadError, ArgumentProcessingError, SizeLimitExceededError.
        """
        metadata = skill.metadata
        file_path = metadata.skill_path
        normalized_args = normalize_arguments(arguments)
        current_mtime = file_path.stat().st_mtime

        # Cache access via aiologic.Lock — works sync or async
        cached = self._cache.get_sync(metadata.name, normalized_args, current_mtime)
        if cached is not None:
            return cached

        # Cache miss — load & process synchronously
        from faskill.core.exceptions import ContentLoadError

        try:
            raw_content = file_path.read_text(encoding="utf-8-sig")
        except FileNotFoundError as e:
            raise ContentLoadError(
                f"Skill file not found: {file_path}. File may have been deleted after discovery."
            ) from e
        except PermissionError as e:
            raise ContentLoadError(f"Permission denied reading skill: {file_path}") from e
        except UnicodeDecodeError as e:
            raise ContentLoadError(f"Skill file contains invalid UTF-8: {file_path}") from e

        processed = process_skill_content(raw_content, skill.base_directory, arguments)
        self._cache.put_sync(metadata.name, normalized_args, processed, current_mtime)
        return processed

    #  Cache management

    def get_stats(self):
        """Return a CacheStats snapshot."""
        return self._cache.get_stats()

    def clear_cache(self, skill_name: str | None = None) -> int:
        """Clear cache entries (synchronous — works in any context)."""
        return self._cache.clear_sync(skill_name)

    async def aclear_cache(self, skill_name: str | None = None) -> int:
        """Clear cache entries (async)."""
        return await self._cache.clear(skill_name)

    #  Internal

    async def _get_file_mtime(self, file_path: Path) -> float:
        stat_result = await aiofiles.os.stat(file_path)
        return stat_result.st_mtime

    async def _get_skill_lock(self, skill_name: str) -> asyncio.Lock:
        async with self._locks_lock:
            if skill_name not in self._skill_locks:
                self._skill_locks[skill_name] = asyncio.Lock()
            return self._skill_locks[skill_name]
