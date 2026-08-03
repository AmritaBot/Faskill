# Reference

This document provides reference information for faskill including SKILL.md format specification, system requirements, and development guidelines.

## Table of Contents

- [SKILL.md Format](#skillmd-format)
- [System Requirements](#system-requirements)
- [Development](#development)
- [API Overview](#api-overview)
- [Exception Hierarchy](#exception-hierarchy)

---

## SKILL.md Format

### Required Fields

- `name` (string): Unique skill identifier. **Must not contain spaces** — names with spaces raise `InvalidSkillNameError`. Set the environment variable `NO_FAIL_ON_SPACE=1` to bypass this validation.
- `description` (string): Human-readable skill description

### Optional Fields

- `allowed-tools` (list): Tool names allowed for this skill (not enforced in v0.1)

### Example

```yaml
---
name: git-helper
description: Generate git commit messages and workflow guidance
allowed-tools: Bash, Read
---
# Git Helper Skill

Content with $ARGUMENTS placeholder...
```

### Argument Substitution

- `$ARGUMENTS` → replaced with user-provided arguments
- `$$ARGUMENTS` → literal `$ARGUMENTS` (escaped)
- No placeholder + arguments → arguments appended to end
- No placeholder + no arguments → content unchanged

---

## System Requirements

### Python Version

- **Python**: 3.10+ (3.10, 3.11, 3.12 supported)

### Core Dependencies

- **PyYAML** ≥ 6.0 — YAML frontmatter parsing
- **aiofiles** ≥ 23.0 — async file I/O for skill content loading
- **aiologic** ≥ 0.17.1 — async-safe locking for the invocation cache

### Optional Dependencies

- **langchain-core** ≥ 0.1.0 + **pydantic** ≥ 2.0 — LangChain tool integration

### Installation

```bash
# Core library
pip install faskill

# With LangChain integration
pip install faskill[langchain]

# All optional extras
pip install faskill[all]
```

---

## Development

### Setup

```bash
git clone https://github.com/AmritaBot/faskill.git
cd faskill
python3.10 -m venv .venv
source .venv/bin/activate
pip install -e ".[all]"
```

### Run tests

The project includes a comprehensive pytest-based test suite with 70%+ coverage validating core functionality, integrations, and edge cases.
For detailed testing instructions, test organization, markers, and debugging tips, see **[tests/README.md](../tests/README.md)**.

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov

# Run specific test markers
pytest -m async          # Async tests only
pytest -m integration    # Integration tests only
pytest -m unit           # Unit tests only

# Run specific test file
pytest tests/test_manager.py

# Run with verbose output
pytest -v
```

### Code Quality

```bash
# Lint code
ruff check src/faskill

# Format code
ruff format src/faskill

# Type check
pyright src/faskill
```

### Running Examples

```bash
# Basic sync usage
python examples/basic_usage.py

# Async usage
python examples/async_usage.py

# LangChain integration
python examples/langchain_agent.py

# Multi-source discovery
python examples/multi_source.py

# File path resolution
python examples/file_references.py

# Cache performance demo
python examples/caching_demo.py

# Script execution
python examples/script_execution.py
```

---

## API Overview

### `create_context()`

Factory function — the recommended entry point for creating a `SkillContext`.

```python
from faskill import create_context

ctx = create_context(
    skill_dirs=["./skills", "./plugins"],
    default_script_timeout=30,  # seconds
    max_cache_size=100,  # LRU entries
)
ctx.discover()
```

### `SkillContext`

Main orchestration class for skill discovery and invocation.

**Key Methods**:

| Method | Description |
|--------|-------------|
| `discover()` | Synchronous skill discovery |
| `adiscover()` | Async skill discovery |
| `add_source(path)` | Add a skill directory (CUSTOM or PLUGIN) |
| `invoke_skill(name, args)` | Invoke a skill by name |
| `ainvoke_skill(name, args)` | Async skill invocation |
| `get_skill(name)` | Get skill metadata (progressive disclosure L1) |
| `list_skills()` | List all discovered skill names |
| `execute_skill_script(skill_name, script_name, arguments, timeout)` | Execute a script |
| `get_cache_stats()` | Get cache hit/miss statistics |
| `clear_cache(skill_name=None)` | Clear cache entries |

### `SkillMetadata`

Dataclass containing skill metadata (Level 1 of progressive disclosure).

**Key Fields**:

- `name: str` — Skill identifier
- `description: str` — Human-readable description
- `skill_path: Path` — Path to skill directory
- `allowed_tools: List[str]` — Allowed tool names
- `source: str` — Source location ("CUSTOM", "PLUGIN", etc.)
- `priority: int` — Discovery priority (higher wins on conflict)

### `Skill`

Dataclass containing full skill content (Level 2 of progressive disclosure).

**Key Fields**:

- `metadata: SkillMetadata` — Skill metadata
- `content: str` — Full SKILL.md content with arguments substituted
- `scripts: List[ScriptMetadata]` — Available script files

### `ScriptMetadata`

Dataclass describing an executable script associated with a skill.

### `ScriptExecutionResult`

Dataclass returned by `execute_skill_script()` with `exit_code`, `stdout`, `stderr`, `execution_time_ms`, `timeout`, `signaled`, and truncation fields.

### `FilePathResolver`

Utility for resolving relative file paths within a skill's directory hierarchy.

---

## Exception Hierarchy

```python
SkillsUseError                         # Base exception for all faskill errors
├── SkillParsingError                  # Base for YAML/frontmatter parsing errors
│   ├── InvalidYAMLError               # YAML syntax error in frontmatter
│   ├── MissingRequiredFieldError      # Required field (name/description) missing
│   ├── InvalidSkillNameError          # Skill name contains spaces (bypass: NO_FAIL_ON_SPACE=1)
│   └── InvalidFrontmatterError        # Invalid frontmatter structure
├── SkillInvocationError               # Base for runtime invocation errors
│   ├── SkillNotFoundError             # Skill not found in any source
│   ├── ContentLoadError               # Failed to read skill file
│   ├── ArgumentProcessingError        # Argument substitution failure
│   ├── ArgumentSerializationError     # Argument JSON serialization failure
│   ├── ArgumentSizeError              # Arguments exceed size limit
│   ├── InterpreterNotFoundError       # Script interpreter not available
│   ├── ScriptNotFoundError            # Referenced script not found
│   └── ScriptPermissionError          # Insufficient permissions for script
└── SkillSecurityError                 # Base for security-related errors
    ├── SuspiciousInputError           # Potentially malicious input detected
    ├── SizeLimitExceededError         # Content exceeds configured size limit
    ├── PathSecurityError              # Path traversal or security violation
    └── ToolIDValidationError          # Invalid tool ID format
```

---

## Additional Resources

- **Core Features**: See [docs/core-features.md](core-features.md)
- **LangChain Integration**: See [docs/integration/langchain.md](integration/langchain.md)
- **Contributing**: See [CONTRIBUTING.md](../CONTRIBUTING.md)
- **Examples**: See [examples/](../examples/) directory
