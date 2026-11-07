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


def test_read_resource_rejects_private_paths(context: SkillContext):
    """SKILL.md and dotted files stay out of reach, like the listing says."""
    skill = context.load_skill("pdf-tools")
    (skill.base_directory / ".env").write_text("SECRET=1", encoding="utf-8")

    for path in ("SKILL.md", ".env", "references/../SKILL.md"):
        with pytest.raises(ContentLoadError):
            skill.read_resource(path)


def test_list_resources_skips_symlinks_leaving_the_skill(context: SkillContext, tmp_path: Path):
    """A file symlink pointing outside is not offered to the model."""
    skill = context.load_skill("pdf-tools")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = skill.base_directory / "linked.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")

    paths = [entry.relative_path for entry in skill.list_resources()]
    assert "linked.txt" not in paths


def test_read_resource_resumes_inside_a_long_line(context: SkillContext):
    """A line cut by the byte budget is resumable through start_char."""
    skill = context.load_skill("pdf-tools")
    long_line = "x" * 400
    (skill.base_directory / "long.txt").write_text(long_line, encoding="utf-8")

    first = skill.read_resource("long.txt", max_bytes=200)
    assert "start_char=" in first
    head = first.split("\n")[0]
    start_char = int(first.rsplit("start_char=", 1)[1].rstrip("]"))
    assert start_char == len(head)

    second = skill.read_resource("long.txt", max_bytes=200, start_char=start_char)
    tail = second.split("\n")[0]
    assert tail
    assert long_line.startswith(head + tail)


def test_section_slice_ignores_headings_in_fenced_code(tmp_path: Path):
    """Heading-shaped lines inside a fence are content, not sections."""
    body = (
        "# Real\n\nIntro.\n\n"
        "## Usage\n\n"
        "```markdown\n## Not a section\ntext\n```\n\n"
        "## Next\n\nEnd.\n"
    )
    _make_skill(tmp_path, name="fenced", body=body)
    ctx = SkillContext(skill_dirs=[tmp_path])
    ctx.discover()

    usage = ctx.open_skill("fenced", section="Usage")
    assert "Not a section" in usage
    assert "## Next" not in usage

    missing = ctx.open_skill("fenced", section="Not a section")
    assert "Section not found" in missing


def test_open_skill_bounds_the_file_listing(tmp_path: Path):
    """The listing shares the character budget instead of growing past it."""
    directory = _make_skill(tmp_path, name="many-files")
    for index in range(40):
        (directory / f"notes-{index:02d}.md").write_text("x", encoding="utf-8")
    ctx = SkillContext(skill_dirs=[tmp_path])
    ctx.discover()

    text = ctx.open_skill("many-files", max_chars=700)
    assert "not listed" in text or "listing omitted" in text
    assert len(text) < 1200


def test_open_skill_substitutes_empty_arguments(context: SkillContext):
    """An empty request still clears the placeholder."""
    text = context.open_skill("pdf-tools", arguments="")
    assert "$ARGUMENTS" not in text


def test_open_skill_rejects_oversized_arguments(context: SkillContext):
    """The 1MB argument limit applies to progressive opens too."""
    from faskill.core.exceptions import SizeLimitExceededError

    with pytest.raises(SizeLimitExceededError):
        context.open_skill("pdf-tools", arguments="x" * 1_000_001)


def test_arguments_dollar_escape():
    """``$$ARGUMENTS`` stays a literal token instead of being substituted."""
    from faskill.core.processors import apply_arguments

    assert apply_arguments("Use $$ARGUMENTS here", "q") == "Use $ARGUMENTS here"
