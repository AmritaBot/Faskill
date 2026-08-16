"""AmritaCore integration tests for faskill library.

Tests validate that create_amrita_tools() and register_amrita_script_tools()
correctly register discovered skills as AmritaCore tools (OpenAI-paradigm
JSON Schema modeled with Pydantic), consumable through MultiToolsManager.

Test Coverage:
    - Tool registration and structure validation
    - Tool name/description/schema correctness
    - Tool invocation with various argument patterns
    - Script tool registration and invocation (success + failure)
    - Error propagation from skills to AmritaCore handlers

Markers:
    - integration: AmritaCore framework integration tests
    - requires_amrita: Requires amrita-core package
"""

import asyncio
import json

import pytest

# Skip all tests in this file if amrita-core is not installed
pytest.importorskip("amrita_core")

from amrita_core.config import AmritaConfig, set_config
from amrita_core.tools.manager import MultiToolsManager, ToolsManager

from faskill.core.exceptions import SkillNotFoundError
from faskill.core.manager import SkillContext
from faskill.integrations.amcore import (
    build_script_usage_prompt,
    build_skill_usage_prompt,
    clone_tools_manager,
    create_amrita_tools,
    register_amrita_script_tools,
)


@pytest.fixture(autouse=True)
def _clean_global_tools_manager():
    """Reset the global ``ToolsManager`` singleton before/after each test.

    Since the integration now mixes tools into the global ``ToolsManager()``
    by default, tests must not leak registrations into each other.

    Built-in tools' ``enable_if`` callbacks read the global AmritaCore config,
    so we initialize it once (``set_config``) to make ``get_tools()`` safe.
    """
    _remove_all_tools()
    yield
    _remove_all_tools()


def _remove_all_tools() -> None:
    """Initialize config and remove every tool on the global ToolsManager."""
    set_config(AmritaConfig())
    global_tools = ToolsManager()
    # Traverse the internal registry directly: get_tools() evaluates each
    # tool's enable_if(), which requires the global config to be initialized.
    for name in list(global_tools._models):
        global_tools.remove_tool(name)


@pytest.mark.integration
@pytest.mark.requires_amrita
def test_create_amrita_tools_returns_manager(isolated_manager, skill_factory):
    """Test create_amrita_tools() returns a MultiToolsManager.

    Validates:
        - Return type is MultiToolsManager
        - Empty manager has no tools
        - Tools registered after adding skills
    """
    # Test with empty directory
    isolated_manager.discover()
    tools = create_amrita_tools(isolated_manager)

    assert isinstance(tools, MultiToolsManager)
    assert len(tools.get_tools()) == 0

    # Test with skills
    skill_factory("test-skill", "A test skill", "Content")
    isolated_manager.discover()
    tools = create_amrita_tools(isolated_manager)

    assert len(tools.get_tools()) == 1
    assert tools.has_tool("test-skill")


@pytest.mark.integration
@pytest.mark.requires_amrita
def test_amrita_tool_count_matches_skills(isolated_manager, skill_factory):
    """Test that 3 skills create 3 registered tools."""
    skill_factory("skill-1", "First skill", "Content 1")
    skill_factory("skill-2", "Second skill", "Content 2")
    skill_factory("skill-3", "Third skill", "Content 3")

    isolated_manager.discover()
    tools = create_amrita_tools(isolated_manager)

    assert len(tools.get_tools()) == 3
    assert len(isolated_manager.list_skills()) == 3


@pytest.mark.integration
@pytest.mark.requires_amrita
def test_amrita_tool_has_correct_name_and_description(isolated_manager, skill_factory):
    """Test that tool name/description match skill metadata."""
    skill_factory("code-reviewer", "Reviews code quality", "Review this: $ARGUMENTS")
    skill_factory("test-generator", "Generates unit tests", "Generate tests for: $ARGUMENTS")

    isolated_manager.discover()
    tools = create_amrita_tools(isolated_manager)

    meta = tools.get_tool_meta("code-reviewer")
    assert meta is not None
    assert meta.function.name == "code-reviewer"
    # Tool description stays short — usage guidance lives in the system prompt
    assert meta.function.description == "Reviews code quality"

    assert tools.has_tool("test-generator")
    assert not tools.has_tool("nonexistent-skill")


@pytest.mark.integration
@pytest.mark.requires_amrita
def test_amrita_tool_schema_is_openai_paradigm(isolated_manager, skill_factory):
    """Test the tool schema follows the OpenAI-paradigm structure.

    Validates:
        - type == "function"
        - strict mode enabled (consistent with simple_tool / MCP tools)
        - Single "arguments" string parameter, required
    """
    skill_factory("greeter", "Greets someone", "Hello $ARGUMENTS!")

    isolated_manager.discover()
    tools = create_amrita_tools(isolated_manager)

    schema = tools.get_tool_meta("greeter")
    assert schema is not None
    assert schema.type == "function"
    assert schema.strict is True

    params = schema.function.parameters
    assert params.type == "object"
    assert params.required == ["arguments"]

    prop = params.properties["arguments"]
    assert prop.type == "string"
    assert prop.description


@pytest.mark.integration
@pytest.mark.requires_amrita
async def test_amrita_tool_invocation_with_arguments(temp_skills_dir, skill_factory):
    """Test async handler invocation with arguments works correctly."""
    skill_factory("greeter", "Greets someone", "Hello $ARGUMENTS!")

    manager = SkillContext(skill_dirs=[temp_skills_dir])
    manager.discover()
    tools = create_amrita_tools(manager)

    handler = tools.get_tool_func("greeter")
    assert handler is not None

    # faskill handlers use the dict contract; amrita_core types them as
    # ``dict | ToolContext`` and return ``str | None`` — intentionally ignored.
    result = await handler({"arguments": "World"})  # pyright: ignore[reportArgumentType]
    assert isinstance(result, str)

    assert "Hello World!" in result
    assert "Base directory for this skill:" in result
    assert str(temp_skills_dir / "greeter") in result


@pytest.mark.integration
@pytest.mark.requires_amrita
async def test_amrita_tool_invocation_default_arguments(temp_skills_dir, skill_factory):
    """Test handler with missing/None arguments defaults to empty string."""
    skill_factory("echo", "Echoes input", "You said: $ARGUMENTS")

    manager = SkillContext(skill_dirs=[temp_skills_dir])
    manager.discover()
    tools = create_amrita_tools(manager)

    handler = tools.get_tool_func("echo")
    assert handler is not None

    result = await handler({})  # pyright: ignore[reportArgumentType]
    assert isinstance(result, str)
    assert "You said:" in result

    result = await handler({"arguments": None})  # pyright: ignore[reportArgumentType]
    assert isinstance(result, str)
    assert "You said:" in result


@pytest.mark.integration
@pytest.mark.requires_amrita
async def test_amrita_tool_error_propagation(temp_skills_dir, skill_factory):
    """Test skill errors propagate through the AmritaCore handler."""
    skill_factory("test-skill", "Test skill", "Content: $ARGUMENTS")

    manager = SkillContext(skill_dirs=[temp_skills_dir])
    manager.discover()
    tools = create_amrita_tools(manager)

    handler = tools.get_tool_func("test-skill")
    assert handler is not None

    # Remove skill from registry to simulate deletion
    manager._registry._skills.clear()

    with pytest.raises(SkillNotFoundError):
        await handler({"arguments": "test"})  # pyright: ignore[reportArgumentType]


@pytest.mark.integration
@pytest.mark.requires_amrita
def test_register_script_tools(fixtures_dir):
    """Test script tools are registered with fully qualified names."""
    manager = SkillContext(skill_dirs=[fixtures_dir])
    manager.discover()

    skill = manager.load_skill("script-skill")
    tools = register_amrita_script_tools(skill, manager)

    assert len(tools.get_tools()) == len(skill.scripts)
    assert tools.has_tool("script-skill__extract")
    assert tools.has_tool("script-skill__stdin_test")

    meta = tools.get_tool_meta("script-skill__extract")
    assert meta is not None
    assert meta.function.name == "script-skill__extract"
    assert "reads JSON from stdin" in meta.function.description
    assert "How to use this script:" not in meta.function.description


@pytest.mark.integration
@pytest.mark.requires_amrita
async def test_register_script_tools_invocation_success(fixtures_dir):
    """Test successful script execution returns stdout string."""
    manager = SkillContext(skill_dirs=[fixtures_dir])
    manager.discover()

    skill = manager.load_skill("script-skill")
    tools = register_amrita_script_tools(skill, manager)

    handler = tools.get_tool_func("script-skill__extract")
    assert handler is not None

    result = await handler({"arguments": json.dumps({"field": "hello"})})  # pyright: ignore[reportArgumentType]
    assert isinstance(result, str)

    parsed = json.loads(result)
    assert parsed["status"] == "success"
    assert parsed["extracted"] == "hello"


@pytest.mark.integration
@pytest.mark.requires_amrita
async def test_register_script_tools_invocation_failure(fixtures_dir):
    """Test failed script execution returns structured JSON error (not raise)."""
    # Short timeout so timeout_test.py (infinite loop) fails quickly
    manager = SkillContext(skill_dirs=[fixtures_dir], default_script_timeout=2)
    manager.discover()

    skill = manager.load_skill("script-skill")
    tools = register_amrita_script_tools(skill, manager)

    handler = tools.get_tool_func("script-skill__timeout_test")
    assert handler is not None

    result = await handler({"arguments": "{}"})  # pyright: ignore[reportArgumentType]
    assert isinstance(result, str)

    parsed = json.loads(result)
    assert parsed["success"] is False
    assert "error" in parsed
    assert "timed out" in parsed["error"]


@pytest.mark.integration
@pytest.mark.requires_amrita
def test_build_skill_usage_prompt(isolated_manager, skill_factory):
    """Test the system-role prompt snippet lists skills and usage guidance."""
    skill_factory("code-reviewer", "Reviews code quality", "Review this: $ARGUMENTS")
    skill_factory("test-generator", "Generates unit tests", "Generate tests for: $ARGUMENTS")
    isolated_manager.discover()

    prompt = build_skill_usage_prompt(isolated_manager)

    assert "code-reviewer: Reviews code quality" in prompt
    assert "test-generator: Generates unit tests" in prompt
    assert "$ARGUMENTS" in prompt
    assert "## Available faskill skills" in prompt


@pytest.mark.integration
@pytest.mark.requires_amrita
def test_build_skill_usage_prompt_empty(isolated_manager):
    """Empty skill set produces an empty (safe-to-concatenate) snippet."""
    isolated_manager.discover()
    assert build_skill_usage_prompt(isolated_manager) == ""


@pytest.mark.integration
@pytest.mark.requires_amrita
def test_build_script_usage_prompt(fixtures_dir):
    """Test the script system-role prompt snippet lists script tools."""
    manager = SkillContext(skill_dirs=[fixtures_dir])
    manager.discover()

    skill = manager.load_skill("script-skill")
    prompt = build_script_usage_prompt(skill)

    assert "script-skill__extract" in prompt
    assert "script-skill__stdin_test" in prompt
    assert "## Scripts for skill: script-skill" in prompt
    assert "JSON object" in prompt


@pytest.mark.integration
@pytest.mark.requires_amrita
def test_default_mixes_into_global_tools_manager(isolated_manager, skill_factory):
    """copy=False registers directly onto the global ``ToolsManager`` singleton.

    This mirrors AmritaCore's ``on_tools(bound_to=None)`` behaviour: tool
    registration mixes into ``ToolsManager()`` (which ``AbilityContext.tools``
    / ``glb.tools`` resolves to) instead of creating a fresh manager.
    """
    skill_factory("global-skill", "Global skill", "Content")
    isolated_manager.discover()

    result = create_amrita_tools(isolated_manager, copy=False)

    assert isinstance(result, ToolsManager)
    assert result is ToolsManager()  # same singleton
    assert ToolsManager().has_tool("global-skill")


@pytest.mark.integration
@pytest.mark.requires_amrita
def test_default_copy_returns_clone_and_keeps_global_clean(isolated_manager, skill_factory):
    """copy=True (default) registers onto a clone, leaving the global pool clean."""
    skill_factory("global-skill", "Global skill", "Content")
    isolated_manager.discover()

    result = create_amrita_tools(isolated_manager)

    assert isinstance(result, MultiToolsManager)
    assert result is not ToolsManager()  # a clone, not the singleton
    assert result.has_tool("global-skill")
    assert not ToolsManager().has_tool("global-skill")  # global untouched


@pytest.mark.integration
@pytest.mark.requires_amrita
def test_clone_tools_manager_isolates_registry(isolated_manager, skill_factory):
    """Tools registered on a clone never leak into the original manager."""
    skill_factory("clone-skill", "Clone skill", "Content")
    isolated_manager.discover()

    original = MultiToolsManager()
    clone = clone_tools_manager(original)

    # Registering a tool on the clone leaves the original empty.
    from faskill.integrations.amcore import _build_arguments_schema, _register_tool

    schema = _build_arguments_schema(name="clone-only", description="Only on clone")
    _register_tool(clone, schema, lambda data: "ok")

    assert clone.has_tool("clone-only")
    assert not original.has_tool("clone-only")

    # Re-cloning from the clone preserves the snapshot without sharing state.
    clone2 = clone_tools_manager(clone)
    _register_tool(clone2, schema, lambda data: "ok")
    assert clone2.has_tool("clone-only")


@pytest.mark.integration
@pytest.mark.requires_amrita
def test_skill_activation_injects_script_tools(fixtures_dir):
    """Calling a skill tool activates (injects) that skill's script tools."""
    manager = SkillContext(skill_dirs=[fixtures_dir])
    manager.discover()

    tools = create_amrita_tools(manager)

    # Script tools are NOT eagerly registered.
    assert not tools.has_tool("script-skill__extract")
    assert not tools.has_tool("script-skill__convert")

    # Invoking the skill tool activates them on the same manager.
    handler = tools.get_tool_func("script-skill")
    assert handler is not None

    result = asyncio.run(handler({}))  # pyright: ignore[reportArgumentType]
    assert isinstance(result, str)
    assert tools.has_tool("script-skill__extract")
    assert tools.has_tool("script-skill__convert")


@pytest.mark.integration
@pytest.mark.requires_amrita
def test_skill_activation_skips_unavailable_interpreter(fixtures_dir, monkeypatch):
    """Scripts with a missing interpreter are skipped and reported to the model."""
    from faskill.integrations.amcore import _interpreter_available

    manager = SkillContext(skill_dirs=[fixtures_dir])
    manager.discover()

    # Simulate an environment where no interpreter is available.
    monkeypatch.setattr(
        "faskill.integrations.amcore._interpreter_available",
        lambda script: False,
    )

    tools = create_amrita_tools(manager)
    handler = tools.get_tool_func("script-skill")
    assert handler is not None

    result = asyncio.run(handler({}))  # pyright: ignore[reportArgumentType]
    assert isinstance(result, str)

    # No script tools registered and the model is told about them.
    assert not tools.has_tool("script-skill__extract")
    assert "missing interpreter" in result
    assert "extract" in result

    # Sanity: the original availability check is positive for python3/bash.
    skill = manager.load_skill("script-skill")
    assert any(_interpreter_available(script) for script in skill.scripts)


@pytest.mark.integration
@pytest.mark.requires_amrita
def test_custom_tools_manager_reused(isolated_manager, skill_factory):
    """Test passing an existing tools_manager registers onto it (per-session)."""
    skill_factory("skill-a", "Skill A", "Content A")
    skill_factory("skill-b", "Skill B", "Content B")

    isolated_manager.discover()

    shared = MultiToolsManager()
    tools = create_amrita_tools(isolated_manager, tools_manager=shared, copy=False)

    # Same instance returned and populated (copy=False registers in place)
    assert tools is shared
    assert shared.has_tool("skill-a")
    assert shared.has_tool("skill-b")
    # Custom manager does NOT touch the global singleton
    assert not ToolsManager().has_tool("skill-a")
    assert not ToolsManager().has_tool("skill-b")
