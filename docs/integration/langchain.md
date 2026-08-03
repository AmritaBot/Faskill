# LangChain Integration

This guide covers how to integrate faskill with LangChain agents.

## Table of Contents

- [Basic Integration (Sync)](#basic-integration-sync)
- [Async Integration](#async-integration)
- [Script Tool Integration](#script-tool-integration)
- [Tool ID Format and Validation](#tool-id-format-and-validation)
- [Complete Examples](#complete-examples)

---

## Basic Integration (Sync)

```python
from faskill import create_context
from faskill.integrations.langchain import create_langchain_tools
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

# Discover skills
ctx = create_context(skill_dirs=["./skills"])
ctx.discover()

# Convert to LangChain tools
tools = create_langchain_tools(ctx)

# Create agent
llm = ChatOpenAI(model="gpt-4o")
prompt = "You are a helpful assistant. Use the available skill tools to answer user queries."
agent = create_agent(llm, tools, system_prompt=prompt)

# Use agent
result = agent.invoke(
    {"messages": [{"role": "user", "content": "What are common architectural patterns in Python?"}]}
)
```

---

## Async Integration

```python
import asyncio
from faskill import create_context
from faskill.integrations.langchain import create_langchain_tools
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI


async def main():
    ctx = create_context(skill_dirs=["./skills"])
    await ctx.adiscover()

    tools = create_langchain_tools(ctx)
    llm = ChatOpenAI(model="gpt-4o")
    prompt = "You are a helpful assistant. Use the available skill tools to answer user queries."

    agent = create_agent(llm, tools, system_prompt=prompt)
    result = await agent.ainvoke(
        {
            "messages": [
                {"role": "user", "content": "What are common architectural patterns in Python?"}
            ]
        }
    )


asyncio.run(main())
```

---

## Script Tool Integration

faskill follows **progressive disclosure** for context efficiency:

| Level | Content | When loaded |
|-------|---------|-------------|
| **L1** | Metadata (name, description) | `discover()` / `list_skills()` |
| **L2** | Full skill body | Lazily on first `invoke_skill()` |
| **L3** | Scripts | Explicitly via `create_script_tools()` on demand |

`create_langchain_tools()` creates **only prompt-based tools** — script tools are
**not** auto-created.  To expose scripts to an agent, call `create_script_tools()`
after the agent has chosen a skill:

```python
from faskill import create_context
from faskill.integrations.langchain import create_langchain_tools, create_script_tools

ctx = create_context(skill_dirs=["./skills"])
ctx.discover()

# Step 1: Create prompt-based tools (L1 metadata only — no script scanning)
tools = create_langchain_tools(ctx)

# Step 2: When the agent decides to use a particular skill, load scripts on demand
skill = ctx.load_skill("pdf-extractor")
if skill.scripts:  # triggers script detection NOW
    script_tools = create_script_tools(skill, ctx)
    tools.extend(script_tools)  # "pdf-extractor__extract", etc.
```

### How It Works

1. **On-Demand Detection**: Scripts are only detected when `skill.scripts` is accessed
2. **Explicit Tool Creation**: Use `create_script_tools()` to convert scripts into LangChain tools
3. **Agent Access**: LangChain agents can invoke scripts like any other tool
4. **Progressive Disclosure**: Saves token overhead by avoiding up-front scanning of all skill directories

---

## Tool ID Format and Validation

Script tool IDs follow a validated format to ensure LLM provider compatibility.

### Format Rules

- **Format**: `{skill-name}__{script-name}` (double underscore separator)
- **Validation Pattern**: `^[a-z0-9-]+__[a-z0-9_]+$`
- **Max Length**: 60 characters
- **Automatic Normalization**:
  - Skill names: Lowercase with underscores converted to hyphens
  - Script names: Lowercase with underscores preserved

### Examples

```python
# Valid tool IDs:
# ✓ "pdf-extractor__extract" (skill: PDF-Extractor, script: extract.py)
# ✓ "csv-parser__parse" (skill: csv_parser, script: parse.py)
# ✓ "data-processor__transform-json" (skill: DataProcessor, script: transform_json.py)

# Invalid formats raise ToolIDValidationError:
# ✗ "pdf.extractor__extract" (dots not allowed in skill name)
# ✗ "PDF-Extractor__Extract" (uppercase not allowed)
# ✗ "very-long-skill-name-exceeds-limit__script" (exceeds 60 chars)
```

### Error Handling

```python
from faskill import ToolIDValidationError

try:
    tools = create_langchain_tools(ctx)
except ToolIDValidationError as e:
    print(f"Invalid tool ID: {e}")
```

---

## Complete Examples

### Example 1: Basic Agent with Skills

See `examples/langchain_agent.py` for a complete working example:

```python
from faskill import create_context
from faskill.integrations.langchain import create_langchain_tools
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

# Setup
ctx = create_context(skill_dirs=["./skills"])
ctx.discover()
tools = create_langchain_tools(ctx)

# Create agent
llm = ChatOpenAI(model="gpt-4o")
agent = create_agent(llm, tools, system_prompt="You are a helpful assistant.")

# Run query
result = agent.invoke({"messages": [{"role": "user", "content": "Review my code"}]})
```

### Example 2: Async Agent with Progressive Script Disclosure

```python
import asyncio
from faskill import create_context
from faskill.integrations.langchain import create_langchain_tools, create_script_tools


async def main():
    ctx = create_context(skill_dirs=["./skills"])
    await ctx.adiscover()

    # Only prompt tools at first (progressive disclosure)
    tools = create_langchain_tools(ctx)

    # Load scripts on demand for the skill the agent needs
    skill = ctx.load_skill("pdf-extractor")
    if skill.scripts:
        tools += create_script_tools(skill, ctx)

    # Use with async LangChain agent...


asyncio.run(main())
```

### Example 3: Error Handling

```python
from faskill import SkillNotFoundError, ContentLoadError, ScriptNotFoundError

try:
    tools = create_langchain_tools(ctx)
    result = agent.invoke({"messages": [{"role": "user", "content": "..."}]})
except SkillNotFoundError:
    print("Skill not found during tool creation")
except ContentLoadError:
    print("Skill file is unreadable")
except ScriptNotFoundError:
    print("Script not found in skill directory")
```

---

## Best Practices

1. **Discover Once**: Call `discover()` once at startup and reuse the context
2. **Async When Possible**: Use `adiscover()` and `ainvoke_skill()` for better performance
3. **Monitor Cache**: Use `ctx.get_cache_stats()` to verify good cache hit rates
4. **Handle Errors**: Always wrap agent invocations in try-except blocks
5. **Tool Descriptions**: Ensure SKILL.md descriptions are clear for LLM understanding
6. **Script Parameters**: Use lowercase parameter names in scripts for consistency

---

## Additional Resources

- **Basic Usage**: See `examples/basic_usage.py`
- **Async Patterns**: See `examples/async_usage.py`
- **LangChain Agent**: See `examples/langchain_agent.py`
- **Script Execution**: See [Core Features - Script Execution](../core-features.md#script-execution)
- **Debugging**: See [Core Features - Debugging Tips](../core-features.md#debugging-tips)
