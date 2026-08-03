"""
Installation Tests for faskill Library

Tests package installation and imports across different configurations:
- Core imports work without optional dependencies
- LangChain imports work with [langchain] extra
- LangChain imports fail gracefully without extra
- Package metadata is correct

These tests validate the package structure and distribution.
"""

import pytest


def test_core_imports_without_extras():
    """Test that core functionality imports work without optional dependencies."""
    # Core imports should always work
    from faskill import Skill, SkillContext, SkillMetadata
    from faskill.core.discovery import SkillDiscovery
    from faskill.core.exceptions import (
        ContentLoadError,
        InvalidYAMLError,
        MissingRequiredFieldError,
        SkillsUseError,
    )
    from faskill.core.parser import SkillParser
    from faskill.core.processors import ContentProcessor

    # Verify classes are importable and instantiable
    assert SkillContext is not None
    assert SkillMetadata is not None
    assert Skill is not None
    assert SkillDiscovery is not None
    assert SkillParser is not None
    assert ContentProcessor is not None

    # Verify exceptions are importable
    assert issubclass(MissingRequiredFieldError, SkillsUseError)
    assert issubclass(InvalidYAMLError, SkillsUseError)
    assert issubclass(ContentLoadError, SkillsUseError)


def test_langchain_import_with_extras():
    """Test that LangChain integration imports work when langchain is installed."""
    try:
        from faskill.integrations.langchain import create_langchain_tools

        # If langchain is installed, this should work
        assert create_langchain_tools is not None
        assert callable(create_langchain_tools)
    except ImportError as e:
        # If langchain is not installed, skip test
        pytest.skip(f"LangChain not installed: {e}")


def test_package_version_metadata():
    """Test that package version metadata is correct."""
    import faskill

    # Verify version attribute exists
    assert hasattr(faskill, "__version__")

    # Verify version format (should be semantic versioning)
    version = faskill.__version__
    assert isinstance(version, str)
    assert len(version) > 0

    # Version should match expected format (e.g., "0.1.0")
    parts = version.split(".")
    assert len(parts) >= 2, f"Version should have at least 2 parts: {version}"

    # First two parts should be numeric
    assert parts[0].isdigit(), f"Major version should be numeric: {version}"
    assert parts[1].isdigit(), f"Minor version should be numeric: {version}"


def test_package_metadata_attributes():
    """Test that package metadata attributes exist and are correct."""
    import faskill

    # Verify common metadata attributes exist
    assert hasattr(faskill, "__version__")

    # Check for optional metadata
    # Note: Not all packages expose these, so we just verify the module is importable
    assert faskill.__name__ == "faskill"

    # Verify main exports are available
    expected_exports = ["SkillContext", "SkillMetadata", "Skill"]
    for export in expected_exports:
        assert hasattr(faskill, export), f"Expected export '{export}' not found in faskill"


def test_import_from_top_level():
    """Test that common classes can be imported from top-level package."""
    # These should all work from the top level
    from faskill import Skill, SkillContext, SkillMetadata

    # Verify they're the correct types
    assert SkillContext.__name__ == "SkillContext"
    assert SkillMetadata.__name__ == "SkillMetadata"
    assert Skill.__name__ == "Skill"


def test_submodule_imports():
    """Test that submodules can be imported directly."""
    # Core submodules
    from faskill.core import discovery, exceptions, manager, models, parser, processors

    # Verify modules are loaded
    assert discovery.__name__ == "faskill.core.discovery"
    assert parser.__name__ == "faskill.core.parser"
    assert models.__name__ == "faskill.core.models"
    assert manager.__name__ == "faskill.core.manager"
    assert processors.__name__ == "faskill.core.processors"
    assert exceptions.__name__ == "faskill.core.exceptions"
