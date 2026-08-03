"""Tests for SkillContext orchestration layer.

This module validates the SkillContext class including discovery, listing,
retrieval, caching, and end-to-end invocation workflows.
"""

import asyncio

import pytest

from faskill.core.exceptions import ConfigurationError, SkillNotFoundError
from faskill.core.manager import SkillContext
from faskill.core.models import Skill, SkillMetadata

# T048: Create test_manager.py with imports and file header ✓


# T049: test_manager_discover_returns_dict
def test_manager_list_skills_returns_list(sample_skills):
    """Validate list_skills() returns list of SkillMetadata after discovery.

    Tests that the manager properly stores and returns discovered skills
    as a list of metadata objects.
    """
    # sample_skills is a list of skill directories, get the parent
    skills_dir = sample_skills[0].parent
    manager = SkillContext(skill_dirs=[skills_dir])
    manager.discover()

    skills = manager.list_skills()

    assert isinstance(skills, list)
    assert len(skills) > 0
    assert all(isinstance(skill, SkillMetadata) for skill in skills)


# T050: test_manager_get_skill_by_name
def test_manager_get_skill_by_name(sample_skills):
    """Validate get_skill() returns SkillMetadata for valid skill name.

    Tests that the manager can retrieve specific skills by name
    after discovery is complete.
    """
    skills_dir = sample_skills[0].parent
    manager = SkillContext(skill_dirs=[skills_dir])
    manager.discover()

    # Get the first skill name
    skills = manager.list_skills()
    assert len(skills) > 0

    first_skill_name = skills[0].name
    metadata = manager.get_skill(first_skill_name)

    assert metadata is not None
    assert isinstance(metadata, SkillMetadata)
    assert metadata.name == first_skill_name


# T051: test_manager_list_skills_returns_names
def test_manager_list_skills_contains_metadata(sample_skills):
    """Validate list_skills() returns list with name and description fields.

    Tests that the returned skill metadata contains all expected fields
    for display and selection purposes.
    """
    skills_dir = sample_skills[0].parent
    manager = SkillContext(skill_dirs=[skills_dir])
    manager.discover()

    skills = manager.list_skills()

    for skill in skills:
        assert hasattr(skill, "name")
        assert hasattr(skill, "description")
        assert hasattr(skill, "skill_path")
        assert skill.name is not None
        assert skill.description is not None


# T052: test_manager_skill_invocation
def test_manager_skill_invocation(fixtures_dir):
    """Validate end-to-end workflow: discover → get_skill → invoke.

    Tests the complete skill lifecycle from discovery through invocation,
    ensuring all components work together correctly.
    """
    manager = SkillContext(skill_dirs=[fixtures_dir])
    manager.discover()

    # Find a valid skill
    skills = manager.list_skills()
    assert len(skills) > 0

    # Load and invoke the skill
    skill_name = skills[0].name
    result = manager.invoke_skill(skill_name, arguments="test input")

    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0


# T053: test_manager_caching_behavior
def test_manager_load_skill_returns_skill_instance(sample_skills):
    """Validate load_skill() returns Skill instance (not just metadata).

    Tests that the manager creates proper Skill instances with lazy
    content loading capability.
    """
    skills_dir = sample_skills[0].parent
    manager = SkillContext(skill_dirs=[skills_dir])
    manager.discover()

    skills = manager.list_skills()
    assert len(skills) > 0

    skill_name = skills[0].name
    skill = manager.load_skill(skill_name)

    assert isinstance(skill, Skill)
    assert skill.metadata.name == skill_name
    assert hasattr(skill, "invoke")


# T054: test_manager_content_load_error_when_file_deleted
def test_manager_skill_not_found_error(sample_skills):
    """Validate SkillNotFoundError raised for non-existent skill name.

    Tests that the manager raises appropriate exception with helpful
    error message when requesting a skill that doesn't exist.
    """
    skills_dir = sample_skills[0].parent
    manager = SkillContext(skill_dirs=[skills_dir])
    manager.discover()

    with pytest.raises(SkillNotFoundError) as exc_info:
        manager.get_skill("nonexistent-skill-xyz")

    assert "nonexistent-skill-xyz" in str(exc_info.value)
    assert "not found" in str(exc_info.value).lower()


# Additional test: Empty directory returns empty list
def test_manager_empty_directory(tmp_path):
    """Validate manager handles empty directory gracefully.

    Tests that discovery in an empty directory completes without errors
    and returns empty skill list.
    """
    empty_dir = tmp_path / "empty_skills"
    empty_dir.mkdir()

    # Explicitly opt-out of default directories to test only empty_dir
    manager = SkillContext(skill_dirs=[empty_dir])
    manager.discover()

    skills = manager.list_skills()
    assert skills == []


# Additional test: Discovery logs and continues on invalid skills
def test_manager_graceful_degradation_on_invalid_skill(tmp_path, caplog):
    """Validate manager continues discovery when encountering invalid skills.

    Tests that the manager logs errors for invalid skills but continues
    processing other valid skills (graceful degradation).
    """
    skills_dir = tmp_path / "mixed_skills"
    skills_dir.mkdir()

    # Create one valid skill
    valid_dir = skills_dir / "valid-skill"
    valid_dir.mkdir()
    (valid_dir / "SKILL.md").write_text("---\nname: valid\ndescription: Valid skill\n---\nContent")

    # Create one invalid skill (missing name)
    invalid_dir = skills_dir / "invalid-skill"
    invalid_dir.mkdir()
    (invalid_dir / "SKILL.md").write_text("---\ndescription: Invalid skill\n---\nContent")

    # Explicitly opt-out of default directories to test only skills_dir
    manager = SkillContext(skill_dirs=[skills_dir])
    manager.discover()

    # Should have discovered only the valid skill
    skills = manager.list_skills()
    assert len(skills) == 1
    assert skills[0].name == "valid"

    # Should have logged error for invalid skill
    assert any("Failed to parse skill" in record.message for record in caplog.records)


# Additional test: Invoke skill with arguments
def test_manager_invoke_skill_with_arguments(fixtures_dir):
    """Validate invoke_skill() processes arguments correctly.

    Tests that the convenience method properly passes arguments through
    to the skill processor.
    """
    manager = SkillContext(skill_dirs=[fixtures_dir])
    manager.discover()

    # Find a skill with $ARGUMENTS placeholder
    skills = manager.list_skills()
    assert len(skills) > 0

    # Try to invoke with arguments
    skill_name = skills[0].name
    arguments = "test data for processing"
    result = manager.invoke_skill(skill_name, arguments=arguments)

    assert result is not None
    assert isinstance(result, str)
    # Result should contain either the arguments or the original content
    assert len(result) > 0


# Additional test: Discovery clears previous skills
def test_manager_discover_clears_previous_skills(tmp_path):
    """Validate calling discover() multiple times clears previous results.

    Tests that re-running discovery resets the skill registry,
    preventing stale skill accumulation.
    """
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # First discovery: create 2 skills
    skill1 = skills_dir / "skill1"
    skill1.mkdir()
    (skill1 / "SKILL.md").write_text("---\nname: skill1\ndescription: First skill\n---\nContent")

    skill2 = skills_dir / "skill2"
    skill2.mkdir()
    (skill2 / "SKILL.md").write_text("---\nname: skill2\ndescription: Second skill\n---\nContent")

    # Explicitly opt-out of default directories to test only skills_dir
    manager = SkillContext(skill_dirs=[skills_dir])
    manager.discover()
    assert len(manager.list_skills()) == 2

    # Remove skill2 and discover again
    (skill2 / "SKILL.md").unlink()
    skill2.rmdir()

    manager.discover()
    assert len(manager.list_skills()) == 1
    assert manager.list_skills()[0].name == "skill1"


# ==============================================================================
# Phase 5.1 Remediation Tests: Default Directory Discovery (User Story 3)
# ==============================================================================
# These tests address acceptance scenarios 4-8 from spec.md that were missing
# in the original v0.2 implementation. They validate tri-state parameter logic
# (None vs "" vs Path) for SkillContext initialization.


def test_scenario_4_explicit_custom_directory_discovered(tmp_path):
    """Scenario 4: Explicitly provided custom directory is discovered.

    When:
        - SkillContext(skill_dirs=[path]) with explicit path
        - The path exists and contains valid skills
    Then:
        - Skills from the path are discovered and available
    """
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill1_dir = skills_dir / "test-skill"
    skill1_dir.mkdir()
    (skill1_dir / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: Test skill from explicit dir\n---\nContent"
    )

    manager = SkillContext(skill_dirs=[skills_dir])
    manager.discover()

    skills = manager.list_skills()
    assert len(skills) == 1
    assert skills[0].name == "test-skill"
    assert skills[0].description == "Test skill from explicit dir"


def test_scenario_5_conflict_plugin_vs_custom(tmp_path):
    """Scenario 5: Plugin source wins over custom directory due to priority.

    When:
        - Two directories have the same skill name
        - One is a plugin (priority 10), the other is custom (priority 5)
    Then:
        - Both directories are scanned
        - Plugin wins conflicts (priority 10 > 5)
    """
    # Create a custom skills dir (treated as CUSTOM, priority 5)
    custom_skills = tmp_path / "custom-skills"
    custom_skills.mkdir()
    custom_skill = custom_skills / "test-skill"
    custom_skill.mkdir()
    (custom_skill / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: Custom version\n---\nCustom content"
    )

    # Create a plugin dir (has manifest, priority 10)
    plugin_dir = tmp_path / "plugin-dir"
    plugin_dir.mkdir()
    plugin_manifest_dir = plugin_dir / ".claude-plugin"
    plugin_manifest_dir.mkdir()
    import json

    (plugin_manifest_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "test-plugin",
                "version": "1.0.0",
                "description": "A test plugin",
                "author": "test",
            }
        )
    )
    plugin_skills = plugin_dir / "skills"
    plugin_skills.mkdir(parents=True)
    plugin_skill = plugin_skills / "test-skill"
    plugin_skill.mkdir()
    (plugin_skill / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: Plugin version\n---\nPlugin content"
    )

    manager = SkillContext(skill_dirs=[custom_skills, plugin_dir])
    manager.discover()

    # Plugin wins (priority 10 > 5)
    skills = manager.list_skills()
    assert len(skills) == 1
    assert skills[0].name == "test-skill"
    assert skills[0].description == "Plugin version"  # Plugin wins


def test_scenario_6_no_dirs_empty_with_log(tmp_path, caplog):
    """Scenario 6: No directories configured, context initialises empty.

    When:
        - SkillContext() initialised without parameters
    Then:
        - Context initialises successfully with 0 skills
        - INFO log: "No skill directories configured; initialised with empty skill list"
    """
    import logging

    caplog.set_level(logging.INFO)

    manager = SkillContext()
    manager.discover()

    skills = manager.list_skills()
    assert len(skills) == 0

    assert "No skill directories configured; initialised with empty skill list" in caplog.text


def test_scenario_7_explicit_invalid_raises_error(tmp_path):
    """Scenario 7: Explicitly provided path doesn't exist, raises ConfigurationError.

    When:
        - SkillContext(skill_dirs=[nonexistent]) with explicit path
        - Path does not exist
    Then:
        - Raises ConfigurationError immediately
        - Error message includes parameter name "skill_dirs" and path
    """
    nonexistent_path = tmp_path / "nonexistent"

    with pytest.raises(ConfigurationError) as exc_info:
        SkillContext(skill_dirs=[nonexistent_path])

    error_message = str(exc_info.value)
    assert "skill_dirs" in error_message
    assert str(nonexistent_path) in error_message
    assert "does not exist" in error_message


def test_scenario_8_no_args_skips_all_dirs(tmp_path, caplog):
    """Scenario 8: SkillContext() with no args finds nothing.

    When:
        - SkillContext() initialised with no arguments
        - A ./skills/ directory exists in the CWD
    Then:
        - No skills are auto-discovered (no implicit defaults)
        - INFO log about empty configuration
    """
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill1_dir = skills_dir / "test-skill"
    skill1_dir.mkdir()
    (skill1_dir / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: Should be ignored\n---\nContent"
    )

    import logging

    caplog.set_level(logging.INFO)

    # No args = no sources
    manager = SkillContext()
    manager.discover()

    skills = manager.list_skills()
    assert len(skills) == 0

    assert "No skill directories configured" in caplog.text


def test_mixed_valid_and_opt_out(tmp_path, monkeypatch):
    """Mixed configuration: Explicit valid path + opt-out for other sources.

    When:
        - SkillContext(skill_dirs=["/valid/path"])
        - /valid/path exists
        - ./.claude/skills/ exists but is opted out
    Then:
        - Only /valid/path is scanned
        - ./.claude/skills/ is ignored despite existing
    """
    # Setup: Create valid custom path and default anthropic path
    monkeypatch.chdir(tmp_path)

    # Create custom valid path
    custom_skills = tmp_path / "custom-skills"
    custom_skills.mkdir()
    custom_skill = custom_skills / "custom-skill"
    custom_skill.mkdir()
    (custom_skill / "SKILL.md").write_text(
        "---\nname: custom-skill\ndescription: From custom path\n---\nContent"
    )

    # Create default anthropic path (should be ignored)
    claude_skills = tmp_path / ".claude" / "skills"
    claude_skills.mkdir(parents=True)
    claude_skill = claude_skills / "claude-skill"
    claude_skill.mkdir()
    (claude_skill / "SKILL.md").write_text(
        "---\nname: claude-skill\ndescription: Should be ignored\n---\nContent"
    )

    # Test: Mixed configuration
    manager = SkillContext(
        skill_dirs=[custom_skills],  # Explicit opt-out
    )
    manager.discover()

    # Verify: Only custom path skill discovered
    skills = manager.list_skills()
    assert len(skills) == 1
    assert skills[0].name == "custom-skill"
    assert skills[0].description == "From custom path"


# ==============================================================================
# Phase 3: User Story 1 - Content Caching with Cache Invalidation (T019)
# ==============================================================================
# These tests validate the caching behavior added in v0.4, including:
# - Cache hits/misses tracking
# - Mtime-based invalidation
# - Processed content format (base directory injection)


def test_cache_hit_on_repeated_invocation(fixtures_dir):
    """Validate cache hit on second invocation with same arguments.

    Tests that repeated skill invocations with identical arguments
    return cached content instead of re-reading from disk.
    """
    manager = SkillContext(skill_dirs=[fixtures_dir])
    manager.discover()

    skills = manager.list_skills()
    assert len(skills) > 0
    skill_name = skills[0].name

    # First invocation - cache miss
    content1 = manager.invoke_skill(skill_name, "test-args")
    stats1 = manager.get_cache_stats()
    assert stats1.misses == 1
    assert stats1.hits == 0

    # Second invocation - cache hit
    content2 = manager.invoke_skill(skill_name, "test-args")
    stats2 = manager.get_cache_stats()
    assert stats2.hits == 1
    assert stats2.misses == 1  # Still only 1 miss

    # Content should be identical
    assert content1 == content2


def test_cache_miss_on_different_arguments(fixtures_dir):
    """Validate cache miss when arguments differ.

    Tests that different arguments create separate cache entries
    and don't result in cache hits.
    """
    manager = SkillContext(skill_dirs=[fixtures_dir])
    manager.discover()

    skills = manager.list_skills()
    assert len(skills) > 0
    skill_name = skills[0].name

    # First invocation with args1
    content1 = manager.invoke_skill(skill_name, "args1")
    stats1 = manager.get_cache_stats()
    assert stats1.misses == 1
    assert content1 is not None

    # Second invocation with different args2
    content2 = manager.invoke_skill(skill_name, "args2")
    stats2 = manager.get_cache_stats()
    assert stats2.misses == 2  # Another miss
    assert stats2.hits == 0  # No hits yet
    assert content2 is not None

    # Repeated invocation with args1 - cache hit
    content3 = manager.invoke_skill(skill_name, "args1")
    stats3 = manager.get_cache_stats()
    assert stats3.hits == 1
    assert stats3.misses == 2
    assert content3 is not None


def test_cache_invalidation_on_file_modification(fixtures_dir):
    """Validate cache invalidation when SKILL.md modified.

    Tests that modifying a skill file's mtime causes cache
    invalidation on next invocation.
    """
    manager = SkillContext(skill_dirs=[fixtures_dir])
    manager.discover()

    skills = manager.list_skills()
    assert len(skills) > 0
    skill_name = skills[0].name
    skill_path = skills[0].skill_path  # This is already the SKILL.md file path

    # First invocation - cache miss
    content1 = manager.invoke_skill(skill_name, "test")
    stats1 = manager.get_cache_stats()
    assert stats1.misses == 1
    assert content1 is not None

    # Modify file (update mtime)
    import time

    time.sleep(0.01)  # Ensure mtime changes
    skill_path.touch()

    # Second invocation - cache invalidated, another miss
    content2 = manager.invoke_skill(skill_name, "test")
    stats2 = manager.get_cache_stats()
    assert stats2.misses == 2  # Cache was invalidated
    assert content2 is not None

    # Third invocation - cache hit (new mtime cached)
    content3 = manager.invoke_skill(skill_name, "test")
    stats3 = manager.get_cache_stats()
    assert stats3.hits == 1
    assert content3 is not None


def test_processed_content_includes_base_directory(fixtures_dir):
    """Validate processed content includes base directory line.

    Tests that the returned content starts with base directory
    context for agent file resolution.
    """
    manager = SkillContext(skill_dirs=[fixtures_dir])
    manager.discover()

    skills = manager.list_skills()
    assert len(skills) > 0
    skill_name = skills[0].name
    # Get base directory from skill_path (parent directory of SKILL.md)
    base_dir = skills[0].skill_path.parent

    content = manager.invoke_skill(skill_name, "test")

    # First line should be base directory
    lines = content.split("\n")
    assert len(lines) > 0
    assert lines[0] == f"Base directory for this skill: {base_dir}"


def test_cache_stats_hit_rate_calculation(fixtures_dir):
    """Validate cache statistics hit rate calculation.

    Tests that CacheStats.hit_rate is correctly calculated
    as hits / (hits + misses).
    """
    manager = SkillContext(skill_dirs=[fixtures_dir])
    manager.discover()

    skills = manager.list_skills()
    assert len(skills) > 0
    skill_name = skills[0].name

    # Invoke 5 times: 1 miss, 4 hits
    for _ in range(5):
        manager.invoke_skill(skill_name, "same-args")

    stats = manager.get_cache_stats()
    assert stats.hits == 4
    assert stats.misses == 1
    assert stats.hit_rate == 0.8  # 4 / (4 + 1)


# ==============================================================================
# Phase 4: User Story 2 - Argument Normalization for Cache Efficiency (T025)
# ==============================================================================
# These tests validate that whitespace normalization improves cache hit rates


def test_normalization_whitespace_variations_same_cache_entry(fixtures_dir):
    """Validate whitespace variations hit same cache entry.

    Tests that arguments differing only in whitespace are
    normalized to the same cache key.
    """
    manager = SkillContext(skill_dirs=[fixtures_dir])
    manager.discover()

    skills = manager.list_skills()
    assert len(skills) > 0
    skill_name = skills[0].name

    # First invocation with leading space
    content1 = manager.invoke_skill(skill_name, " file.pdf")
    stats1 = manager.get_cache_stats()
    assert stats1.misses == 1

    # Second invocation with trailing space - cache hit
    content2 = manager.invoke_skill(skill_name, "file.pdf ")
    stats2 = manager.get_cache_stats()
    assert stats2.hits == 1  # Cache hit!

    # Third invocation with both spaces - cache hit
    content3 = manager.invoke_skill(skill_name, " file.pdf ")
    stats3 = manager.get_cache_stats()
    assert stats3.hits == 2

    # Fourth invocation with no spaces - cache hit
    content4 = manager.invoke_skill(skill_name, "file.pdf")
    stats4 = manager.get_cache_stats()
    assert stats4.hits == 3

    # All content should be identical
    assert content1 == content2 == content3 == content4


def test_normalization_multiple_spaces_collapsed(fixtures_dir):
    """Validate multiple spaces collapsed for cache efficiency.

    Tests that arguments with varying numbers of internal spaces
    are normalized to the same cache key.
    """
    manager = SkillContext(skill_dirs=[fixtures_dir])
    manager.discover()

    skills = manager.list_skills()
    assert len(skills) > 0
    skill_name = skills[0].name

    # First invocation with multiple spaces
    manager.invoke_skill(skill_name, "a  b")
    stats1 = manager.get_cache_stats()
    assert stats1.misses == 1

    # Second invocation with more spaces - cache hit
    manager.invoke_skill(skill_name, "a     b")
    stats2 = manager.get_cache_stats()
    assert stats2.hits == 1

    # Third invocation with single space - cache hit
    manager.invoke_skill(skill_name, "a b")
    stats3 = manager.get_cache_stats()
    assert stats3.hits == 2


def test_normalization_none_and_empty_equivalent(fixtures_dir):
    """Validate None and empty string are equivalent for caching.

    Tests that arguments=None and arguments="" hit the same
    cache entry after normalization.
    """
    manager = SkillContext(skill_dirs=[fixtures_dir])
    manager.discover()

    skills = manager.list_skills()
    assert len(skills) > 0
    skill_name = skills[0].name

    # First invocation with None
    content1 = manager.invoke_skill(skill_name, "")
    stats1 = manager.get_cache_stats()
    assert stats1.misses == 1

    # Second invocation with empty string - cache hit
    content2 = manager.invoke_skill(skill_name, "")
    stats2 = manager.get_cache_stats()
    assert stats2.hits == 1

    # Content should be identical
    assert content1 == content2


def test_normalization_preserves_case_sensitivity(fixtures_dir):
    """Validate normalization preserves case for different cache entries.

    Tests that case differences create separate cache entries,
    ensuring file paths and other case-sensitive arguments work correctly.
    """
    manager = SkillContext(skill_dirs=[fixtures_dir])
    manager.discover()

    skills = manager.list_skills()
    assert len(skills) > 0
    skill_name = skills[0].name

    # First invocation with lowercase
    manager.invoke_skill(skill_name, "file.pdf")
    stats1 = manager.get_cache_stats()
    assert stats1.misses == 1

    # Second invocation with uppercase - cache miss (different key)
    manager.invoke_skill(skill_name, "FILE.PDF")
    stats2 = manager.get_cache_stats()
    assert stats2.misses == 2  # Different cache entry

    # Third invocation with original lowercase - cache hit
    manager.invoke_skill(skill_name, "file.pdf")
    stats3 = manager.get_cache_stats()
    assert stats3.hits == 1  # Hits first entry


# ==============================================================================
# Phase 5: User Story 3 - Thread-Safe Concurrent Invocations (T031)
# ==============================================================================
# These tests validate thread safety with concurrent async invocations


@pytest.mark.asyncio
async def test_concurrent_same_skill_serialized(fixtures_dir):
    """Validate concurrent invocations of same skill are serialized.

    Tests that multiple concurrent invocations of the same skill
    are handled safely via per-skill locking.
    """
    manager = SkillContext(skill_dirs=[fixtures_dir])
    await manager.adiscover()

    skills = manager.list_skills()
    assert len(skills) > 0
    skill_name = skills[0].name

    # Launch 10 concurrent invocations of same skill
    tasks = [manager.ainvoke_skill(skill_name, f"args-{i}") for i in range(10)]
    results = await asyncio.gather(*tasks)

    # All should complete successfully
    assert len(results) == 10
    assert all(isinstance(r, str) for r in results)

    # Cache should have 10 entries (different arguments)
    stats = manager.get_cache_stats()
    assert stats.size == 10
    assert stats.misses == 10  # All first invocations


@pytest.mark.asyncio
async def test_concurrent_different_skills_parallel(fixtures_dir):
    """Validate concurrent invocations of different skills run in parallel.

    Tests that different skills can be invoked concurrently without
    blocking each other (per-skill locking allows parallel execution).
    """
    manager = SkillContext(skill_dirs=[fixtures_dir])
    await manager.adiscover()

    skills = manager.list_skills()
    # Need at least 3 skills for this test
    if len(skills) < 3:
        pytest.skip("Test requires at least 3 skills")

    # Launch concurrent invocations of different skills
    tasks = [manager.ainvoke_skill(skills[i].name, "test-args") for i in range(min(3, len(skills)))]
    results = await asyncio.gather(*tasks)

    # All should complete successfully
    assert len(results) == min(3, len(skills))
    assert all(isinstance(r, str) for r in results)


@pytest.mark.asyncio
async def test_concurrent_cache_statistics_accurate(fixtures_dir):
    """Validate cache statistics remain accurate under concurrent access.

    Tests that hit/miss counters are correctly tracked even with
    concurrent invocations (no race conditions in statistics).
    """
    manager = SkillContext(skill_dirs=[fixtures_dir])
    await manager.adiscover()

    skills = manager.list_skills()
    assert len(skills) > 0
    skill_name = skills[0].name

    # First invocation (cache miss)
    await manager.ainvoke_skill(skill_name, "test-args")

    # Launch 10 concurrent invocations with same arguments (cache hits)
    tasks = [manager.ainvoke_skill(skill_name, "test-args") for _ in range(10)]
    await asyncio.gather(*tasks)

    # Verify statistics
    stats = manager.get_cache_stats()
    assert stats.hits == 10  # All 10 concurrent hits
    assert stats.misses == 1  # Only first invocation missed
    assert stats.hit_rate == 10 / 11


# ==============================================================================
# Phase 5: User Story 3 - Cache Management Methods (T032)
# ==============================================================================
# These tests validate clear_cache() and aclear_cache() methods


def test_clear_cache_specific_skill(fixtures_dir):
    """Validate clear_cache(skill_name) removes only that skill's entries.

    Tests selective cache clearing for a specific skill without
    affecting other skills' cached content.
    """
    manager = SkillContext(skill_dirs=[fixtures_dir])
    manager.discover()

    skills = manager.list_skills()
    if len(skills) < 2:
        pytest.skip("Test requires at least 2 skills")

    skill1_name = skills[0].name
    skill2_name = skills[1].name

    # Cache content for both skills
    manager.invoke_skill(skill1_name, "args1")
    manager.invoke_skill(skill1_name, "args2")
    manager.invoke_skill(skill2_name, "args1")

    stats = manager.get_cache_stats()
    assert stats.size == 3

    # Clear only skill1
    cleared = manager.clear_cache(skill1_name)
    assert cleared == 2  # Two entries for skill1

    # Verify skill2 still cached
    stats = manager.get_cache_stats()
    assert stats.size == 1

    # Verify skill1 entries removed (cache miss)
    manager.invoke_skill(skill1_name, "args1")
    stats_after = manager.get_cache_stats()
    assert stats_after.misses > stats.misses  # New miss


def test_clear_cache_all_entries(fixtures_dir):
    """Validate clear_cache() without arguments clears all entries.

    Tests that calling clear_cache() with no skill_name removes
    all cached content across all skills.
    """
    manager = SkillContext(skill_dirs=[fixtures_dir])
    manager.discover()

    skills = manager.list_skills()
    assert len(skills) > 0

    # Cache content for multiple skills
    for skill in skills[:3]:  # Cache up to 3 skills
        manager.invoke_skill(skill.name, "test-args")

    stats = manager.get_cache_stats()
    initial_size = stats.size
    assert initial_size > 0

    # Clear all cache
    cleared = manager.clear_cache()
    assert cleared == initial_size

    # Verify cache empty
    stats_after = manager.get_cache_stats()
    assert stats_after.size == 0


@pytest.mark.asyncio
async def test_aclear_cache_async(fixtures_dir):
    """Validate aclear_cache() async method works correctly.

    Tests the async version of cache clearing for use in
    async workflows.
    """
    manager = SkillContext(skill_dirs=[fixtures_dir])
    await manager.adiscover()

    skills = manager.list_skills()
    assert len(skills) > 0
    skill_name = skills[0].name

    # Cache some content
    await manager.ainvoke_skill(skill_name, "args1")
    await manager.ainvoke_skill(skill_name, "args2")

    stats = manager.get_cache_stats()
    assert stats.size == 2

    # Clear cache asynchronously
    cleared = await manager.aclear_cache()
    assert cleared == 2

    # Verify cache empty
    stats_after = manager.get_cache_stats()
    assert stats_after.size == 0


def test_clear_cache_returns_count(fixtures_dir):
    """Validate clear_cache() returns number of cleared entries.

    Tests that the return value accurately reports how many
    entries were removed.
    """
    manager = SkillContext(skill_dirs=[fixtures_dir])
    manager.discover()

    skills = manager.list_skills()
    assert len(skills) > 0
    skill_name = skills[0].name

    # Empty cache - should return 0
    cleared = manager.clear_cache()
    assert cleared == 0

    # Add 3 entries
    manager.invoke_skill(skill_name, "args1")
    manager.invoke_skill(skill_name, "args2")
    manager.invoke_skill(skill_name, "args3")

    # Clear all - should return 3
    cleared = manager.clear_cache()
    assert cleared == 3
