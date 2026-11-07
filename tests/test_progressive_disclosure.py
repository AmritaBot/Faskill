"""Tests for progressive disclosure: skill body, resources, and section slicing."""

from pathlib import Path

import pytest

from faskill.core.exceptions import ContentLoadError, PathSecurityError
from faskill.core.manager import SkillContext

BODY = (
    "# PDF Tools\n\n"
    "Handle the request: $ARGUMENTS\n\n"
    "## Workflow\n\n"
    "Step one.\n\n"
    "## Reference\n\n"
    "See references/api.md for details.\n"
)


def _make_skill(root: Path, name: str = "pdf-tools", body: str = BODY) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: PDF helpers.\n---\n\n{body}",
        encoding="utf-8",
    )
    references = directory / "references"
    references.mkdir()
    (references / "api.md").write_text(
        "\n".join(f"line {index}" for index in range(50)), encoding="utf-8"
    )
    scripts = directory / "scripts"
    scripts.mkdir()
    (scripts / "run.py").write_text(
        '#!/usr/bin/env python3\n"""Run the thing."""\nprint("hi")\n', encoding="utf-8"
    )
    return directory


@pytest.fixture
def context(tmp_path: Path) -> SkillContext:
    _make_skill(tmp_path)
    ctx = SkillContext(skill_dirs=[tmp_path])
    ctx.discover()
    return ctx


def test_body_strips_frontmatter(context: SkillContext):
    skill = context.load_skill("pdf-tools")
    assert skill.body.startswith("# PDF Tools")
    assert "name: pdf-tools" not in skill.body
    assert not skill.body.startswith("---")


async def test_invoke_no_longer_returns_raw_file(context: SkillContext):
    skill = context.load_skill("pdf-tools")
    rendered = skill.invoke("summarize it")
    assert "summarize it" in rendered
    assert "name: pdf-tools" not in rendered
    assert "Base directory for this skill" not in rendered

    async_rendered = await skill.ainvoke("summarize it")
    assert "name: pdf-tools" not in async_rendered
    assert "summarize it" in async_rendered


def test_list_resources(context: SkillContext):
    skill = context.load_skill("pdf-tools")
    resources = {entry.relative_path: entry for entry in skill.list_resources()}
    assert "references/api.md" in resources
    assert "scripts/run.py" in resources
    assert resources["scripts/run.py"].is_script is True
    assert resources["references/api.md"].is_script is False
    assert "SKILL.md" not in resources


def test_read_resource_line_range(context: SkillContext):
    skill = context.load_skill("pdf-tools")
    text = skill.read_resource("references/api.md", start_line=10, end_line=13)
    assert text.startswith("line 10\nline 11\nline 12")
    assert "continue with start_line=13" in text


def test_read_resource_full(context: SkillContext):
    skill = context.load_skill("pdf-tools")
    text = skill.read_resource("references/api.md")
    assert text.startswith("line 0")
    assert text.rstrip().endswith("line 49")


def test_read_resource_rejects_traversal(context: SkillContext):
    skill = context.load_skill("pdf-tools")
    with pytest.raises(PathSecurityError):
        skill.read_resource("../../etc/passwd")


def test_read_resource_rejects_binary(context: SkillContext):
    skill = context.load_skill("pdf-tools")
    (skill.base_directory / "assets").mkdir()
    (skill.base_directory / "assets" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\r")
    with pytest.raises(ContentLoadError):
        skill.read_resource("assets/logo.png")


def test_open_skill_returns_body_and_files(context: SkillContext):
    text = context.open_skill("pdf-tools", arguments="merge two PDFs")
    assert text.startswith("[skill: pdf-tools]")
    assert "merge two PDFs" in text
    assert "references/api.md" in text
    assert "skill_read" in text
    assert str(context.load_skill("pdf-tools").base_directory) not in text


def test_open_skill_section(context: SkillContext):
    text = context.open_skill("pdf-tools", section="Workflow")
    assert "Step one." in text
    assert "See references/api.md" not in text


def test_open_skill_unknown_section_lists_headings(context: SkillContext):
    text = context.open_skill("pdf-tools", section="Missing")
    assert "Section not found: Missing" in text
    assert "## Workflow" in text


def test_open_skill_truncates(tmp_path: Path):
    long_body = "# Long\n\n" + "\n".join(f"row {index} " + "x" * 40 for index in range(400))
    _make_skill(tmp_path, name="long-skill", body=long_body)
    ctx = SkillContext(skill_dirs=[tmp_path])
    ctx.discover()

    text = ctx.open_skill("long-skill", max_chars=500)
    assert "[truncated at" in text
    assert len(text) < len(long_body)


def test_read_skill_resource_wrapper(context: SkillContext):
    text = context.read_skill_resource("pdf-tools", "scripts/run.py")
    assert 'print("hi")' in text
