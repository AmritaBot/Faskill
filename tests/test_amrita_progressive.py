"""Progressive-disclosure mode for the AmritaCore integration."""

import pytest

pytest.importorskip("amrita_core")

from amrita_core.config import AmritaConfig, set_config
from amrita_core.tools.manager import ToolsManager

from faskill.core.manager import SkillContext
from faskill.integrations.amcore import build_skill_usage_prompt, create_amrita_tools


def _reset_global_tools() -> None:
    """Configure AmritaCore and empty the global tool registry."""
    set_config(AmritaConfig())
    global_tools = ToolsManager()
    for name in list(global_tools._models):
        global_tools.remove_tool(name)


@pytest.fixture(autouse=True)
def _isolate_global_tools():
    _reset_global_tools()
    yield
    _reset_global_tools()


def _context(temp_skills_dir, skill_factory) -> SkillContext:
    directory = skill_factory(
        "pdf-tools",
        "Extract and merge PDFs.",
        "# PDF Tools\n\nUse $ARGUMENTS carefully.\n\n## Workflow\n\nStep one.\n",
    )
    references = directory / "references"
    references.mkdir()
    (references / "api.md").write_text("reference line one\nline two\n", encoding="utf-8")
    skill_factory("other-skill", "Something else.", "Other body")
    manager = SkillContext(skill_dirs=[temp_skills_dir])
    manager.discover()
    return manager


@pytest.mark.integration
@pytest.mark.requires_amrita
def test_registers_two_tools_only(temp_skills_dir, skill_factory):
    manager = _context(temp_skills_dir, skill_factory)
    tools = create_amrita_tools(manager, mode="progressive")

    assert tools.has_tool("skill_open")
    assert tools.has_tool("skill_read")
    assert not tools.has_tool("pdf-tools")
    assert not tools.has_tool("other-skill")
    assert len(tools.get_tools()) == 2


@pytest.mark.integration
@pytest.mark.requires_amrita
async def test_open_returns_body_and_file_list(temp_skills_dir, skill_factory):
    manager = _context(temp_skills_dir, skill_factory)
    tools = create_amrita_tools(manager, mode="progressive")

    handler = tools.get_tool_func("skill_open")
    assert handler is not None
    result = await handler({"name": "pdf-tools", "arguments": "merge two files"})  # pyright: ignore[reportArgumentType]

    assert isinstance(result, str)
    assert result.startswith("[skill: pdf-tools]")
    assert "merge two files" in result
    assert "references/api.md" in result
    assert "description: Extract and merge PDFs." not in result


@pytest.mark.integration
@pytest.mark.requires_amrita
async def test_open_section_and_unknown_skill(temp_skills_dir, skill_factory):
    manager = _context(temp_skills_dir, skill_factory)
    tools = create_amrita_tools(manager, mode="progressive")
    handler = tools.get_tool_func("skill_open")
    assert handler is not None

    section = await handler({"name": "pdf-tools", "section": "Workflow"})  # pyright: ignore[reportArgumentType]
    assert isinstance(section, str)
    assert "Step one." in section

    missing = await handler({"name": "nope"})  # pyright: ignore[reportArgumentType]
    assert isinstance(missing, str)
    assert "not found" in missing
    assert "pdf-tools" in missing


@pytest.mark.integration
@pytest.mark.requires_amrita
async def test_read_resource(temp_skills_dir, skill_factory):
    manager = _context(temp_skills_dir, skill_factory)
    tools = create_amrita_tools(manager, mode="progressive")
    handler = tools.get_tool_func("skill_read")
    assert handler is not None

    result = await handler({"name": "pdf-tools", "path": "references/api.md"})  # pyright: ignore[reportArgumentType]
    assert isinstance(result, str)
    assert "reference line one" in result

    traversal = await handler({"name": "pdf-tools", "path": "../../etc/passwd"})  # pyright: ignore[reportArgumentType]
    assert isinstance(traversal, str)
    assert "Failed to read" in traversal


@pytest.mark.integration
@pytest.mark.requires_amrita
def test_usage_prompt_points_to_progressive_tools(temp_skills_dir, skill_factory):
    manager = _context(temp_skills_dir, skill_factory)
    prompt = build_skill_usage_prompt(manager, mode="progressive")

    assert "skill_open" in prompt
    assert "skill_read" in prompt
    assert "pdf-tools: Extract and merge PDFs." in prompt
    assert "$ARGUMENTS" not in prompt


@pytest.mark.integration
@pytest.mark.requires_amrita
def test_tool_name_collision_is_reported(temp_skills_dir, skill_factory):
    """A pre-occupied skill_open name fails loudly instead of misrouting."""
    from amrita_core.tools.manager import MultiToolsManager

    from faskill.core.exceptions import ConfigurationError
    from faskill.integrations.amcore import _build_arguments_schema, _register_tool

    manager = _context(temp_skills_dir, skill_factory)
    tools = MultiToolsManager()
    _register_tool(
        tools,
        _build_arguments_schema(name="skill_open", description="Occupied"),
        lambda data: "other",
    )

    with pytest.raises(ConfigurationError):
        create_amrita_tools(manager, tools_manager=tools, copy=False, mode="progressive")


@pytest.mark.integration
@pytest.mark.requires_amrita
async def test_tool_errors_do_not_leak_paths(temp_skills_dir, skill_factory):
    """Failure text names the error type, never the host path."""
    manager = _context(temp_skills_dir, skill_factory)
    tools = create_amrita_tools(manager, mode="progressive")
    handler = tools.get_tool_func("skill_read")
    assert handler is not None

    result = await handler({"name": "pdf-tools", "path": "missing.md"})  # pyright: ignore[reportArgumentType]
    assert isinstance(result, str)
    assert str(temp_skills_dir) not in result
    assert "ContentLoadError" in result
