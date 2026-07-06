#!/usr/bin/env python3
"""
Convert an Instagram data-export zip into Obsidian/digital-garden markdown notes.

Usage:
  python scripts/instagram_to_garden.py ~/dev/<path_to_export>.zip
  python scripts/instagram_to_garden.py path/to/export.zip --dry-run
  python scripts/instagram_to_garden.py path/to/export.zip --publish
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_VAULT = Path.home() / "digital_garden" / "elliott_garden"
NOTES_SUBDIR = "Instagram Archive"
MEDIA_SUBDIR = "_media"
POSTS_JSON = "your_instagram_activity/media/posts_1.json"


def fix_encoding(text: str) -> str:
    """Instagram exports often mangle UTF-8 as Latin-1."""
    if not text:
        return ""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text


def slugify(text: str, max_len: int = 48) -> str:
    text = fix_encoding(text).lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:max_len].rstrip("-") or "post"


def first_line_title(caption: str, fallback: str) -> str:
    caption = fix_encoding(caption).strip()
    if not caption:
        return fallback
    line = caption.splitlines()[0].strip()
    if len(line) > 80:
        line = line[:77].rstrip() + "..."
    return line


def load_posts(export_root: Path) -> list[dict]:
    posts_path = export_root / POSTS_JSON
    if not posts_path.exists():
        raise FileNotFoundError(f"Expected {POSTS_JSON} inside the zip export.")
    with posts_path.open(encoding="utf-8") as f:
        posts = json.load(f)
    if not isinstance(posts, list):
        raise ValueError(f"{POSTS_JSON} should contain a list of posts.")
    return posts


def build_note_slug(post: dict, index: int) -> tuple[str, str, int]:
    media = post.get("media") or []
    if not media:
        raise ValueError(f"Post {index} has no media entries.")
    ts = media[0]["creation_timestamp"]
    date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    caption = fix_encoding(post.get("title", ""))
    slug = slugify(caption) if caption else f"post-{index + 1:02d}"
    return date, slug, ts


def unique_slug(base_date: str, base_slug: str, used: set[str]) -> str:
    candidate = f"{base_date} - {base_slug}"
    if candidate not in used:
        used.add(candidate)
        return candidate
    n = 2
    while f"{base_date} - {base_slug}-{n}" in used:
        n += 1
    candidate = f"{base_date} - {base_slug}-{n}"
    used.add(candidate)
    return candidate


def media_wiki_path(media_slug: str, filename: str) -> str:
    return f"{NOTES_SUBDIR}/{MEDIA_SUBDIR}/{media_slug}/{filename}"


def copy_media(
    export_root: Path,
    media_items: list[dict],
    media_slug: str,
    media_dir: Path,
    dry_run: bool,
) -> list[tuple[str, str]]:
    """Copy post media into the vault and return Obsidian embed paths."""
    copied: list[tuple[str, str]] = []
    dest_dir = media_dir / media_slug

    for i, item in enumerate(media_items, start=1):
        rel_uri = item["uri"]
        ext = Path(rel_uri).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".mp4", ".mov"}:
            continue

        src = export_root / rel_uri
        if not src.exists():
            print(f"  warning: missing media file {rel_uri}", file=sys.stderr)
            continue

        filename = f"{i:02d}{ext}"
        dest = dest_dir / filename
        kind = "video" if ext in {".mp4", ".mov"} else "image"

        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

        copied.append((kind, media_wiki_path(media_slug, filename)))

    return copied


def render_media_markdown(media_refs: list[tuple[str, str]]) -> str:
    return "\n".join(f"![[{path}]]" for _, path in media_refs)


def render_caption(caption: str) -> str:
    caption = fix_encoding(caption).strip()
    if not caption:
        return "_Originally posted on Instagram with no caption._"
    # Preserve paragraph breaks; escape accidental frontmatter-ish lines minimally.
    return caption.replace("\r\n", "\n")


def build_frontmatter(publish: bool) -> str:
    return f"---\ndg-publish: {'true' if publish else 'false'}\n---\n"


def build_prev_next_links(
    ordered_note_names: list[str],
) -> dict[str, tuple[str | None, str | None]]:
    links: dict[str, tuple[str | None, str | None]] = {}
    for i, name in enumerate(ordered_note_names):
        prev_name = ordered_note_names[i - 1] if i > 0 else None
        next_name = ordered_note_names[i + 1] if i < len(ordered_note_names) - 1 else None
        links[name] = (prev_name, next_name)
    return links


def wiki_link(note_name: str, label: str | None = None) -> str:
    label = label or note_name.split(" - ", 1)[-1]
    return f"[[Instagram Archive/{note_name}\\|{label}]]"


def write_intro_note(
    notes_dir: Path,
    note_names: list[str],
    publish: bool,
    dry_run: bool,
) -> None:
    intro_path = notes_dir / "Instagram Archive - Intro.md"
    lines = [
        build_frontmatter(publish).rstrip(),
        "",
        "#instagram #archive",
        "",
        "Archived Instagram posts imported from a Meta data export.",
        "",
        "## Posts (newest first)",
        "",
    ]
    for name in reversed(note_names):
        lines.append(f"- {wiki_link(name)}")

    content = "\n".join(lines) + "\n"
    if dry_run:
        print(f"Would write intro note: {intro_path}")
        return
    notes_dir.mkdir(parents=True, exist_ok=True)
    intro_path.write_text(content, encoding="utf-8")


def convert_export(
    zip_path: Path,
    vault: Path,
    publish: bool = False,
    dry_run: bool = False,
) -> None:
    if not zip_path.exists():
        raise FileNotFoundError(zip_path)

    with tempfile.TemporaryDirectory(prefix="ig-export-") as tmp:
        export_root = Path(tmp)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(export_root)

        posts = load_posts(export_root)
        # Instagram JSON is newest-first; garden blog reads better oldest-first for next links.
        posts = list(reversed(posts))

        notes_dir = vault / NOTES_SUBDIR
        media_dir = notes_dir / MEDIA_SUBDIR
        used_slugs: set[str] = set()
        planned_notes: list[dict] = []

        for index, post in enumerate(posts):
            date, slug, ts = build_note_slug(post, index)
            note_slug = unique_slug(date, slug, used_slugs)
            media_slug = slugify(note_slug)
            title = first_line_title(post.get("title", ""), note_slug)
            media_refs = copy_media(
                export_root,
                post.get("media", []),
                media_slug,
                media_dir,
                dry_run,
            )

            planned_notes.append(
                {
                    "note_slug": note_slug,
                    "title": title,
                    "caption": post.get("title", ""),
                    "ts": ts,
                    "media_refs": media_refs,
                }
            )

        note_names = [n["note_slug"] for n in planned_notes]
        nav = build_prev_next_links(note_names)

        if dry_run:
            print(f"Found {len(planned_notes)} posts in {zip_path.name}")
            print(f"Notes dir: {notes_dir}")
            print(f"Media dir: {media_dir}")
            print()

        for note in planned_notes:
            note_path = notes_dir / f"{note['note_slug']}.md"
            prev_name, next_name = nav[note["note_slug"]]

            body_lines = ["#instagram #archive", ""]
            if prev_name or next_name:
                if prev_name:
                    body_lines.append(f"Previous post: {wiki_link(prev_name)}")
                if next_name:
                    body_lines.append(f"Next post: {wiki_link(next_name)}")
                body_lines.append("")

            body_lines.append(render_caption(note["caption"]))
            if note["media_refs"]:
                body_lines.extend(["", render_media_markdown(note["media_refs"])])

            content = build_frontmatter(publish) + "\n".join(body_lines) + "\n"

            if dry_run:
                images = sum(1 for k, _ in note["media_refs"] if k == "image")
                videos = sum(1 for k, _ in note["media_refs"] if k == "video")
                print(
                    f"- {note['note_slug']}.md  "
                    f"({images} images, {videos} videos, caption={len(fix_encoding(note['caption']))} chars)"
                )
                continue

            notes_dir.mkdir(parents=True, exist_ok=True)
            note_path.write_text(content, encoding="utf-8")
            print(f"Wrote {note_path}")

        write_intro_note(notes_dir, note_names, publish, dry_run)

        if dry_run:
            print("\nDry run only — no files written. Re-run without --dry-run to import.")
        else:
            print(f"\nImported {len(planned_notes)} posts.")
            if not publish:
                print("Notes were created with dg-publish:false. Re-run with --publish to publish them.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", type=Path, help="Path to Instagram export .zip")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Set dg-publish:true on generated notes (default: false for review)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be created without writing files",
    )
    parser.add_argument(
        "--vault",
        type=Path,
        default=DEFAULT_VAULT,
        help=f"Obsidian vault root (default: {DEFAULT_VAULT})",
    )
    args = parser.parse_args()

    try:
        convert_export(
            args.zip_path.expanduser().resolve(),
            args.vault.expanduser().resolve(),
            publish=args.publish,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
