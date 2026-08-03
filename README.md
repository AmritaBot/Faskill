# faskill

> **Fork of [maxvaega/skillkit](https://github.com/maxvaega/skillkit)**  
> Extensively refactored with bug fixes, security hardening, and new abstractions.  
> Maintained by [AmritaConstant](https://github.com/AmritaBot).

<div align="center">

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI](https://img.shields.io/pypi/v/faskill)](https://pypi.org/project/faskill/)
[![GitHub release](https://img.shields.io/github/v/release/AmritaBot/faskill)](https://github.com/AmritaBot/faskill/releases)
</div>

**faskill** is a Python library that brings Anthropic's Agent Skills to any LLM-powered agent. It discovers, loads, and invokes packaged expertise — defined in standard SKILL.md files — with progressive disclosure for token efficiency.

## Features

- **SKILL.md compatible** — works with any existing skill, drop-in ready
- **Framework-agnostic** — use standalone or with LangChain (more integrations planned)
- **Model-agnostic** — works with any LLM
- **Multi-source discovery** — custom directories, plugins with priority-based conflict resolution
- **Progressive disclosure** — metadata-first loading, 80% memory reduction, LRU caching; scripts loaded on demand
- **Script execution** — Python, Shell, JavaScript, Ruby, Perl with security validation and timeout enforcement
- **Pluggable runner** — `Runner` abstraction with `HostRunner` default; swap in Docker, Firecracker, etc.
- **Plugin ecosystem** — supports plugin manifests (`.claude-plugin/plugin.json`) with namespaced skill access
- **Comprehensive error hierarchy** — 20+ typed exceptions for precise error handling

---

## Notable Improvements Over Upstream (skillkit)

This fork contains significant refactoring and bug fixes beyond the original:

| Area         | Improvement                                                                                                                                               |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Bug fix**  | `PRIORITY_CUSTOM` no longer decrements — ≥5 sources won't trigger `ValueError: Priority must be positive`                                                 |
| **Bug fix**  | `create_langchain_tools()` no longer eagerly loads all scripts — respects progressive disclosure (L1→L2→L3)                                               |
| **New**      | `InvalidSkillNameError` — names with spaces are rejected (bypass with `NO_FAIL_ON_SPACE=1`)                                                               |
| **New**      | `Runner` abstraction — `HostRunner` (default, warns once about bare host security) with swappable backends                                                |
| **New**      | `ArgumentSerializationError` / `ArgumentSizeError` / `ToolIDValidationError` — fine-grained script errors                                                 |
| **New**      | `ConfigurationError` / `AsyncStateError` / `PluginError` — better error reporting                                                                         |
| **Refactor** | `SkillManager` → `SkillContext` with `create_context()` factory; modular architecture (discovery, parser, registry, invoker, processors, scripts, runner) |
| **Refactor** | Complete test suite (425 tests), 70%+ coverage, comprehensive fixtures                                                                                    |

---

## Installation

```bash
pip install faskill              # Core library
pip install faskill[langchain]   # With LangChain integration
pip install faskill[all]         # All extras
```

---

## Quick Start

### 1. Create a skill

```
.claude/skills/code-reviewer/SKILL.md
```

```markdown
---
name: code-reviewer
description: Review code for best practices and potential issues
allowed-tools: Read, Grep
---

# Code Reviewer

Analyze the provided code for:

- Best practices violations
- Potential bugs
- Security vulnerabilities

Use $ARGUMENTS to access user input.
```

### 2. Use standalone

```python
from faskill import create_context

ctx = create_context(skill_dirs=["./.claude/skills"])
ctx.discover()

# List available skills
for skill in ctx.list_skills():
    print(f"{skill.name}: {skill.description}")

# Invoke a skill
result = ctx.invoke_skill("code-reviewer", "Review function calculate_total()")
print(result)
```

### 3. Use with LangChain

```python
from faskill import create_context
from faskill.integrations.langchain import create_langchain_tools
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

ctx = create_context(skill_dirs=["./.claude/skills"])
ctx.discover()

tools = create_langchain_tools(ctx)

llm = ChatOpenAI(model="gpt-4o")
agent = create_agent(llm, tools, system_prompt="You are a helpful assistant.")
result = agent.invoke({"messages": [{"role": "user", "content": "Review my code"}]})
```

---

## SKILL.md Format

```yaml
---
name: my-skill # Required: unique identifier
description: ... # Required: human-readable description
allowed-tools: Bash, Read # Optional: tool allowlist
version: "1.0" # Optional: semantic version
---
# Skill content with $ARGUMENTS placeholder
```

- **Argument substitution**: `$ARGUMENTS` → user input; `$$ARGUMENTS` → literal `$ARGUMENTS`
- **No placeholder**: arguments are appended to the end

---

## Script Execution

Skills can bundle executable scripts for deterministic operations:

```
my-skill/
├── SKILL.md
└── scripts/
    └── extract.py
```

```python
result = ctx.execute_skill_script(
    skill_name="my-skill",
    script_name="extract",
    arguments={"file": "doc.pdf", "pages": "all"},
    timeout=30,
)

if result.success:
    print(result.stdout)
else:
    print(f"Error ({result.exit_code}): {result.stderr}")
```

Supported types: `.py`, `.sh`, `.js`, `.rb`, `.pl`, `.bat`, `.cmd`, `.ps1`.

### Script runner (pluggable)

`ScriptExecutor` accepts a `runner` parameter — swap in sandboxed backends:

```python
from faskill.core.scripts import ScriptExecutor
from faskill.core.runner import HostRunner  # default (warns once about security)

# Default: bare host
executor = ScriptExecutor(runner=HostRunner())

# Future: Docker, Firecracker, gVisor...
# executor = ScriptExecutor(runner=DockerRunner(image="python:3.12"))
```

---

## API Reference

### `create_context()`

```python
from faskill import create_context

ctx = create_context(
    skill_dirs=["./skills", "./plugins"],  # Directory list; directories with
    # .claude-plugin/plugin.json are
    # detected as plugins
    default_script_timeout=30,  # seconds (1-600)
    max_cache_size=100,  # LRU cache entries
)
```

### `SkillContext`

| Method                                | Description                                       |
| ------------------------------------- | ------------------------------------------------- |
| `discover()`                          | Sync skill discovery                              |
| `adiscover()`                         | Async skill discovery                             |
| `list_skills()`                       | List all discovered skill metadata                |
| `list_skills(include_qualified=True)` | List names including `plugin:skill`               |
| `get_skill(name)`                     | Get metadata by name; raises `SkillNotFoundError` |
| `invoke_skill(name, args)`            | Sync invocation with caching                      |
| `ainvoke_skill(name, args)`           | Async invocation with caching                     |
| `execute_skill_script(...)`           | Execute a bundled script                          |
| `get_cache_stats()`                   | Cache hit/miss statistics                         |
| `clear_cache(name?)`                  | Clear cache entries                               |
| `add_source(path)`                    | Add a skill directory after construction          |

### Key types

| Type                    | Description                                        |
| ----------------------- | -------------------------------------------------- |
| `SkillMetadata`         | Name, description, path, allowed tools, priority   |
| `Skill`                 | Full skill: metadata + content + scripts           |
| `SkillSource`           | Source directory with type and priority            |
| `ScriptMetadata`        | Detected script name, path, language, description  |
| `ScriptExecutionResult` | exit_code, stdout, stderr, execution_time_ms, etc. |
| `CacheStats`            | size, max_size, hits, misses, hit_rate             |
| `Runner`                | Abstract base for script execution backends        |
| `HostRunner`            | Default runner — bare host subprocess (warns once) |

### Exception hierarchy

```
SkillsUseError
├── SkillParsingError
│   ├── InvalidYAMLError
│   ├── MissingRequiredFieldError
│   ├── InvalidSkillNameError          # name contains spaces (bypass: NO_FAIL_ON_SPACE=1)
│   └── InvalidFrontmatterError
├── SkillNotFoundError
├── SkillInvocationError
│   ├── ArgumentProcessingError
│   ├── ArgumentSerializationError
│   ├── ArgumentSizeError
│   └── ContentLoadError
├── ConfigurationError
├── AsyncStateError
├── PluginError
│   ├── ManifestNotFoundError
│   ├── ManifestParseError
│   └── ManifestValidationError
├── ScriptError
│   ├── InterpreterNotFoundError
│   ├── ScriptNotFoundError
│   ├── ScriptPermissionError
│   ├── ArgumentSerializationError
│   ├── ArgumentSizeError
│   └── ToolIDValidationError
├── SkillSecurityError
│   ├── SuspiciousInputError
│   ├── SizeLimitExceededError
│   └── PathSecurityError
```

---

## Examples

See `examples/` directory:

| File                  | What it demonstrates                           |
| --------------------- | ---------------------------------------------- |
| `basic_usage.py`      | Sync and async standalone usage                |
| `async_usage.py`      | Async usage with FastAPI                       |
| `langchain_agent.py`  | LangChain agent integration                    |
| `multi_source.py`     | Multi-source discovery and conflict resolution |
| `file_references.py`  | Secure file path resolution                    |
| `caching_demo.py`     | Cache performance demonstration                |
| `script_execution.py` | Script execution with error handling           |

---

## Documentation

- **[Core Features](docs/core-features.md)** — multi-source discovery, caching, scripts, patterns
- **[API Reference](docs/reference.md)** — SKILL.md spec, system requirements, development
- **[LangChain Integration](docs/integration/langchain.md)** — sync/async, script tools, tool ID format

---

## Where to find skills

- [Anthropic Skills Library](https://github.com/anthropics/skills)
- [Claude-Plugins.dev](https://claude-plugins.dev/skills)
- [awesome-claude-skills](https://github.com/travisvn/awesome-claude-skills)
- [awesome-skills](https://github.com/maxvaega/awesome-skills)

---

## Contributing

1. Fork → branch → make changes → add tests
2. Ensure `uv run pytest` passes (≥70% coverage)
3. Ensure `uv run ruff check src/` and `uv run pyright src/` pass
4. Submit a pull request

See **[CONTRIBUTING.md](CONTRIBUTING.md)** for detailed guidelines.

---

## License

MIT — see [LICENSE](LICENSE) for details.
