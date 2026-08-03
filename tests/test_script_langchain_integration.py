"""Test LangChain integration for script-based tools (v0.3+)."""

import importlib
import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

# Import guards for optional dependencies
try:
    importlib.util.find_spec("langchain_core")  # noqa: F401

    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

# Skip all tests if langchain not installed
pytestmark = pytest.mark.skipif(
    not LANGCHAIN_AVAILABLE, reason="LangChain integration requires: pip install faskill[langchain]"
)


@pytest.fixture
def mock_skill_with_scripts():
    """Create a mock Skill object with scripts."""
    from faskill.core.scripts import ScriptMetadata

    # Create mock script metadata
    script1 = ScriptMetadata(
        name="extract",
        path=Path("scripts/extract.py"),
        script_type="python",
        description="Extract text from PDF files",
    )

    script2 = ScriptMetadata(
        name="convert",
        path=Path("scripts/convert.sh"),
        script_type="shell",
        description="Convert PDF to text format",
    )

    # Create mock Skill with scripts property
    skill = Mock()
    skill.metadata.name = "pdf-extractor"
    skill.scripts = [script1, script2]

    return skill


@pytest.fixture
def mock_manager():
    """Create a mock SkillContext."""
    from faskill.core.scripts import ScriptExecutionResult

    manager = Mock()

    # Mock execute_skill_script to return success
    result = ScriptExecutionResult(
        stdout="Extracted text: Hello, World!",
        stderr="",
        exit_code=0,
        execution_time_ms=45.2,
        script_path=Path("/tmp/test.py"),
        signal=None,
        signal_number=None,
        stdout_truncated=False,
        stderr_truncated=False,
    )
    manager.execute_skill_script.return_value = result

    return manager


def test_create_script_tools_basic(mock_skill_with_scripts, mock_manager):
    """Test create_script_tools creates tools for all scripts."""
    from faskill.integrations.langchain import create_script_tools

    tools = create_script_tools(mock_skill_with_scripts, mock_manager)

    # Should create 2 tools (one per script)
    assert len(tools) == 2

    # Check tool names follow "{skill_name}__{script_name}" format
    tool_names = [tool.name for tool in tools]
    assert "pdf-extractor__extract" in tool_names
    assert "pdf-extractor__convert" in tool_names


def test_create_script_tools_descriptions(mock_skill_with_scripts, mock_manager):
    """Test script descriptions are used in tool descriptions."""
    from faskill.integrations.langchain import create_script_tools

    tools = create_script_tools(mock_skill_with_scripts, mock_manager)

    # Find extract tool
    extract_tool = next(t for t in tools if t.name == "pdf-extractor__extract")

    # Should use script description
    assert extract_tool.description == "Extract text from PDF files"


def test_script_tool_invocation_success(mock_skill_with_scripts, mock_manager):
    """Test script tool invocation returns stdout on success."""
    from faskill.integrations.langchain import create_script_tools

    tools = create_script_tools(mock_skill_with_scripts, mock_manager)
    extract_tool = next(t for t in tools if t.name == "pdf-extractor__extract")

    # Invoke tool with JSON arguments
    result = extract_tool.invoke({"arguments": {"file": "test.pdf"}})

    # Should return stdout
    assert result == "Extracted text: Hello, World!"

    # Should have called execute_skill_script
    mock_manager.execute_skill_script.assert_called_once()
    call_args = mock_manager.execute_skill_script.call_args
    assert call_args.kwargs["skill_name"] == "pdf-extractor"
    assert call_args.kwargs["script_name"] == "extract"
    assert call_args.kwargs["arguments"] == {"file": "test.pdf"}


def test_script_tool_invocation_failure(mock_skill_with_scripts, mock_manager):
    """Test script tool raises ToolException on failure."""
    from langchain_core.tools import ToolException

    from faskill.core.scripts import ScriptExecutionResult
    from faskill.integrations.langchain import create_script_tools

    # Mock execute_skill_script to return failure
    result = ScriptExecutionResult(
        stdout="",
        stderr="Error: File not found",
        exit_code=1,
        execution_time_ms=10.5,
        script_path=Path("/tmp/test.py"),
        signal=None,
        signal_number=None,
        stdout_truncated=False,
        stderr_truncated=False,
    )
    mock_manager.execute_skill_script.return_value = result

    tools = create_script_tools(mock_skill_with_scripts, mock_manager)
    extract_tool = next(t for t in tools if t.name == "pdf-extractor__extract")

    # Should raise ToolException
    with pytest.raises(ToolException) as exc_info:
        extract_tool.invoke({"arguments": {"file": "missing.pdf"}})

    # Error message should include stderr
    assert "Error: File not found" in str(exc_info.value)


def test_create_langchain_tools_prompt_only():
    """Test create_langchain_tools creates only prompt-based tools (progressive disclosure).

    Script tools are NOT auto-created — they must be created explicitly via
    create_script_tools() when needed, following the progressive disclosure pattern.
    """
    from faskill.integrations.langchain import create_langchain_tools

    # Create mock manager with a skill that has scripts
    manager = Mock()

    # Mock list_skills to return skill metadata
    skill_metadata = Mock()
    skill_metadata.name = "pdf-extractor"
    skill_metadata.description = "PDF processing skill"
    manager.list_skills.return_value = [skill_metadata]

    # Create tools — should only create 1 prompt tool, NOT script tools
    tools = create_langchain_tools(manager)

    # Only prompt-based tool, no script tools auto-created
    assert len(tools) == 1
    assert tools[0].name == "pdf-extractor"
    assert tools[0].description == "PDF processing skill"

    # load_skill should NOT have been called (scripts not eagerly loaded)
    manager.load_skill.assert_not_called()


def test_script_tool_with_empty_description(mock_manager):
    """Test script tool with no description uses default."""
    from faskill.core.scripts import ScriptMetadata
    from faskill.integrations.langchain import create_script_tools

    # Create script with empty description
    script = ScriptMetadata(
        name="process",
        path=Path("scripts/process.py"),
        script_type="python",
        description="",  # Empty description
    )

    skill = Mock()
    skill.metadata.name = "test-skill"
    skill.scripts = [script]

    tools = create_script_tools(skill, mock_manager)

    # Should use default description
    assert len(tools) == 1
    assert tools[0].description == "Execute process script"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
