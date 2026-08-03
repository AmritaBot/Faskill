# Core Features

This document provides detailed information about faskill's core features and advanced usage patterns.

## Table of Contents

- [Multi-Source Discovery](#multi-source-discovery)
- [Script Execution](#script-execution)
- [Caching System](#caching-system)
- [Common Usage Patterns](#common-usage-patterns)
- [Debugging Tips](#debugging-tips)
- [Performance Tips](#performance-tips)

---

## Multi-Source Discovery

faskill discovers skills from directories you configure. Each directory is treated as a **CUSTOM** source by default, unless it contains a plugin manifest (`.claude-plugin/plugin.json`), in which case it's detected as a **PLUGIN** source with higher priority.

### Basic setup

```python
from faskill import create_context

ctx = create_context(skill_dirs=["./my-skills", "./shared-skills"])
ctx.discover()
```

### Adding sources after construction

```python
ctx = create_context()
ctx.add_source("./my-skills")
ctx.add_source("./plugins/pdf-tools")  # auto-detected as PLUGIN if manifest exists
ctx.discover()
```

### Plugin detection

Any directory containing `.claude-plugin/plugin.json` is automatically treated as a PLUGIN source with priority 10. Plain directories are CUSTOM with priority 5. Plugin skills are also available via qualified names (`plugin-name:skill-name`).

```python
# Access a skill from a specific plugin
skill = ctx.get_skill("pdf-tools:extractor")
```

### Conflict resolution

When two sources define a skill with the same name, the higher-priority source wins. A warning is logged identifying which version was kept and which was ignored. Use qualified names to access shadowed plugin skills.

---

## Script Execution

Skills can include executable scripts for deterministic operations. Scripts are automatically detected and executed with security controls.

### Supported Types

| Extension | Interpreter |
|-----------|-------------|
| `.py` | `python3` |
| `.sh` | `bash` |
| `.js` | `node` |
| `.rb` | `ruby` |
| `.pl` | `perl` |
| `.bat`, `.cmd` | `cmd` |
| `.ps1` | `powershell` |

### Basic Script Execution

```python
from faskill import create_context

ctx = create_context(skill_dirs=["./my-skills"])
ctx.discover()

result = ctx.execute_skill_script(
    skill_name="pdf-extractor",
    script_name="extract",
    arguments={"file": "document.pdf", "pages": "all"},
    timeout=30,
)

if result.success:
    print(result.stdout)
else:
    print(f"Error ({result.exit_code}): {result.stderr}")
```

### Script Directory Structure

Scripts should be placed in a `scripts/` directory or in the skill root:

```
my-skill/
├── SKILL.md
└── scripts/
    ├── extract.py
    ├── convert.sh
    └── utils/
        └── parser.py
```

### Script Input/Output

Scripts receive arguments as JSON via stdin and output results to stdout. All parameter names are automatically normalized to lowercase.

```python
#!/usr/bin/env python3
"""Extract data from PDF file."""

import sys, json

args = json.load(sys.stdin)

# Use lowercase parameter names (normalized automatically)
file_path = args.get("file_path", "document.pdf")
page_range = args.get("page_range", "all")

result = {"extracted_text": "..."}
print(json.dumps(result))
```

### Environment Variables

Scripts automatically receive:

- `SKILL_NAME` — parent skill name
- `SKILL_BASE_DIR` — absolute path to skill directory
- `SKILL_VERSION` — version from metadata
- `FASKILL_VERSION` — current faskill version

### Error Handling

```python
from faskill import (
    ScriptNotFoundError,
    InterpreterNotFoundError,
    PathSecurityError,
)

try:
    result = ctx.execute_skill_script(
        skill_name="my-skill",
        script_name="process",
        arguments={"data": [1, 2, 3]},
    )
except ScriptNotFoundError:
    print("Script not found")
except InterpreterNotFoundError:
    print("Required interpreter not available")
except PathSecurityError:
    print("Security validation failed")
```

### Execution Result Properties

```python
result.exit_code  # 0 = success
result.success  # True if exit_code == 0
result.stdout  # Captured stdout
result.stderr  # Captured stderr
result.execution_time_ms  # Duration in milliseconds
result.timeout  # True if killed by timeout
result.signaled  # True if terminated by signal
result.signal  # Signal name (e.g. SIGSEGV)
result.stdout_truncated  # True if output exceeded 10MB
result.stderr_truncated  # True if stderr exceeded 10MB
```

---

## Caching System

faskill uses an LRU cache backed by `aiologic.Lock`, which safely supports both sync and async access without `asyncio.run()` bridges. Repeated invocations are **up to 25x faster**.

### Configuration

```python
ctx = create_context(skill_dirs=["./skills"], max_cache_size=200)  # default: 100
ctx.discover()
```

### Monitoring

```python
stats = ctx.get_cache_stats()
print(f"Hit rate: {stats.hit_rate:.1%}")
print(f"Usage: {stats.size}/{stats.max_size}")
print(f"Hits: {stats.hits}, Misses: {stats.misses}")
```

### Clearing

```python
ctx.clear_cache("code-reviewer")  # Clear one skill
ctx.clear_cache()  # Clear all
```

---

## Common Usage Patterns

### Custom skill directories

```python
from pathlib import Path

ctx = create_context(skill_dirs=[Path("/custom/skills")])
```

### Error handling

```python
from faskill import SkillNotFoundError, ContentLoadError

try:
    result = ctx.invoke_skill("my-skill", "some args")
except SkillNotFoundError:
    print("Skill not found")
except ContentLoadError:
    print("Skill file was deleted or is unreadable")
```

### Accessing metadata

```python
metadata = ctx.get_skill("code-reviewer")
print(f"Path: {metadata.skill_path}")
print(f"Tools: {metadata.allowed_tools}")
```

### Async usage

```python
import asyncio
from faskill import create_context


async def main():
    ctx = create_context(skill_dirs=["./skills"])
    await ctx.adiscover()

    result = await ctx.ainvoke_skill("code-reviewer", "Review main.py")
    print(result)


asyncio.run(main())
```

---

## Debugging Tips

### Enable logging

```python
import logging

logging.basicConfig(level=logging.DEBUG)
```

### Module-specific logging

```python
logging.getLogger("faskill.core.discovery").setLevel(logging.DEBUG)
```

### Common issues

**Skill not found after discovery:**
- Check skill directory path
- Verify SKILL.md file exists (case-insensitive)
- Check logs for parsing errors

**YAML parsing errors:**
- Validate YAML syntax (use `yamllint`)
- Check for proper `---` delimiters
- Ensure required fields (`name`, `description`) are present

**Arguments not substituted:**
- Use `$ARGUMENTS` (case-sensitive)
- Avoid typos: `$arguments`, `$ARGUMENT`, `$ ARGUMENTS`

---

## Performance Tips

1. **Discover once**: Call `discover()` once at startup, reuse the context
2. **Reuse the context**: Don't create a new `SkillContext` for each invocation — cache is instance-level
3. **Monitor cache**: Use `get_cache_stats()` to verify hit rates (target: >80%)
4. **Configure cache size**: Increase `max_cache_size` for many skills or diverse arguments
5. **Keep skills focused**: Large skills (>200KB) may slow invocation
6. **Use async methods**: `ainvoke_skill()` enables concurrent execution
7. **Python 3.10+**: Better memory efficiency with dataclass slots

