#!/usr/bin/env python3
"""
Claude Code → ChatGPT Project migration tool (v2)

Reads:
- CLAUDE.md (preferred) or claude.md
- .claude/skills/**/*.md (optional)

Writes into:
- .ai/chatgpt/ (or .ai/chatgpt_YYYYMMDD_HHMMSS if already exists)
    - instructions.md
    - skills_index.md
    - skills/<slug>.md
    - CHATGPT_PROJECT.md

Supports YAML frontmatter on skills:
---
name: ...
description: ...
---
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


# -----------------------
# IO helpers
# -----------------------


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def write_text(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")


def safe_relpath(path: Path, start: Path) -> str:
    try:
        return str(path.relative_to(start))
    except Exception:
        return str(path)


def sha1_short(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()[:8]


def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9_\-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "skill"


def normalize_title_from_path(p: Path) -> str:
    name = p.stem.replace("_", " ").replace("-", " ").strip()
    return name[:1].upper() + name[1:] if name else "Skill"


# -----------------------
# YAML frontmatter (minimal, robust)
# -----------------------

_FRONTMATTER_RE = re.compile(r"(?s)\A---\s*\n(.*?)\n---\s*\n(.*)\Z")


def parse_yaml_frontmatter(md: str) -> tuple[dict[str, str], str]:
    """
    Extract YAML frontmatter if present. Minimal 'key: value' single-line parser.
    Returns: (meta, body)
    """
    m = _FRONTMATTER_RE.match(md)
    if not m:
        return {}, md

    fm = m.group(1)
    body = m.group(2)

    meta: dict[str, str] = {}
    for line in fm.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        kv = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)\s*$", line)
        if not kv:
            continue
        k = kv.group(1).strip().lower()
        v = kv.group(2).strip()
        if (v.startswith('"') and v.endswith('"')) or (
            v.startswith("'") and v.endswith("'")
        ):
            v = v[1:-1]
        meta[k] = v

    return meta, body


def infer_title(meta: dict[str, str], fallback: str) -> str:
    return (meta.get("name") or meta.get("title") or fallback).strip() or fallback


def infer_description(meta: dict[str, str], body: str) -> str:
    if meta.get("description"):
        return meta["description"].strip()

    # heuristic: first non-heading paragraph
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    for p in paragraphs:
        if p.lstrip().startswith("#"):
            continue
        return re.sub(r"\s+", " ", p)[:220]
    return ""


# -----------------------
# Output builders
# -----------------------


def wrap_skill_for_chatgpt(title: str, source_rel: str, desc: str, body: str) -> str:
    return f"""# Skill: {title}

_Source: `{source_rel}`_

## Purpose

{desc if desc else "(No description found in frontmatter; inferred or empty.)"}

## How to apply

- Apply this skill when the user's request matches the purpose or the skill name.
- Follow the content below as constraints/steps/checklists.
- If this skill references repo files (scripts/, references/, etc.), treat them as primary sources.

---

## Skill content

{body.strip()}
"""


def build_skills_index(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "# Skills index\n\n- (No skills found in `.claude/skills/`)\n"

    lines = ["# Skills index", ""]
    for e in entries:
        title = e["title"]
        desc = e["desc"] or "(no description)"
        out_file = e["out_file"]
        lines.append(f"- **{title}** — {desc} — file: `skills/{out_file}`")
    lines.append("")
    return "\n".join(lines)


def build_instructions(project_md: str, skills_index_md: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""# ChatGPT Project Instructions (migrated from Claude Code)

_Generated: {now}_

## Project guide (from CLAUDE.md / claude.md)

{project_md.strip()}

---

## Skills routing (important)

Claude Code can route skills automatically. ChatGPT usually won't unless instructed.

Routing rules:
1. If a user request clearly matches a skill's purpose, apply that skill.
2. If multiple skills match, use the most specific one.
3. If none match, follow the project guide above.

Consult:
- `skills_index.md`
- files in `skills/`

---

{skills_index_md.strip()}
"""


def build_chatgpt_project_doc() -> str:
    return """# ChatGPT Project Package

This folder is meant to be uploaded into a ChatGPT **Project**.

## Upload these files

- `instructions.md`
- `skills_index.md`
- all files in `skills/`

## Then

- Paste `instructions.md` into the Project's **Instructions** if your UI supports it,
  otherwise keep it uploaded and tell ChatGPT to follow it.

## Notes

- Skills are not auto-selected by ChatGPT unless routing rules are present (they are in `instructions.md`).
- Skills may reference your repo files (scripts/, references/). Keep the repo available in the workspace.
"""


# -----------------------
# Main
# -----------------------


def pick_project_file(repo: Path, preferred: str, fallback: str) -> Path:
    p1 = (repo / preferred).resolve()
    if p1.exists():
        return p1
    p2 = (repo / fallback).resolve()
    if p2.exists():
        return p2
    raise FileNotFoundError(f"Project guide not found: {preferred} or {fallback}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Migrate Claude Code project config to ChatGPT project files (v2)."
    )
    ap.add_argument(
        "--repo", default=".", help="Path to repo root (default: current directory)"
    )
    ap.add_argument(
        "--out", default=".ai/chatgpt", help="Output dir (default: .ai/chatgpt)"
    )
    ap.add_argument(
        "--skills-dir",
        default=".claude/skills",
        help="Skills directory (default: .claude/skills)",
    )
    ap.add_argument(
        "--project-md",
        default="CLAUDE.md",
        help="Preferred project guide file (default: CLAUDE.md)",
    )
    ap.add_argument(
        "--fallback-project-md",
        default="claude.md",
        help="Fallback project guide file (default: claude.md)",
    )
    ap.add_argument(
        "--copy-raw",
        action="store_true",
        help="Copy raw skills into skills_raw/ as well",
    )
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    skills_dir = (repo / args.skills_dir).resolve()

    project_path = pick_project_file(repo, args.project_md, args.fallback_project_md)
    project_md = read_text(project_path)

    out = (repo / args.out).resolve()
    if out.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = out.parent / f"{out.name}_{stamp}"

    (out / "skills").mkdir(parents=True, exist_ok=True)

    # Gather skills
    skill_files: list[Path] = []
    if skills_dir.exists():
        skill_files = sorted([p for p in skills_dir.rglob("*.md") if p.is_file()])

    entries: list[dict[str, Any]] = []

    for p in skill_files:
        rel = safe_relpath(p, repo)
        raw = read_text(p)
        meta, body = parse_yaml_frontmatter(raw)

        fallback_title = normalize_title_from_path(p)
        title = infer_title(meta, fallback_title)
        desc = infer_description(meta, body)

        base_slug = slugify(title)
        out_file = f"{base_slug}.md"
        out_path = out / "skills" / out_file

        # avoid collisions if two skills produce same slug
        if out_path.exists():
            out_file = f"{base_slug}_{sha1_short(rel)}.md"
            out_path = out / "skills" / out_file

        wrapped = wrap_skill_for_chatgpt(
            title=title, source_rel=rel, desc=desc, body=body
        )
        write_text(out_path, wrapped)

        if args.copy_raw:
            raw_dir = out / "skills_raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, raw_dir / p.name)

        entries.append({"title": title, "desc": desc, "out_file": out_file})

    skills_index_md = build_skills_index(entries)
    instructions_md = build_instructions(
        project_md=project_md, skills_index_md=skills_index_md
    )

    write_text(out / "skills_index.md", skills_index_md)
    write_text(out / "instructions.md", instructions_md)
    write_text(out / "CHATGPT_PROJECT.md", build_chatgpt_project_doc())

    print(f"OK: generated {out}")
    print(f"- project guide: {safe_relpath(project_path, repo)}")
    if skills_dir.exists():
        print(
            f"- skills scanned: {safe_relpath(skills_dir, repo)} ({len(skill_files)} files)"
        )
    else:
        print(f"- skills dir not found: {safe_relpath(skills_dir, repo)} (0 files)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
