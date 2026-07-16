#!/usr/bin/env python3
"""Copy Instagram archive videos from the Obsidian vault into the site img folder.

Digital Garden publishes images but not MP4/MOV files. Run this after publishing
Instagram archive notes so videos are available at /img/user/... on the live site.

Usage:
  python scripts/sync_instagram_videos.py
  python scripts/sync_instagram_videos.py --dry-run
  python scripts/sync_instagram_videos.py --vault ~/digital_garden/elliott_garden
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_VAULT = Path.home() / "digital_garden" / "elliott_garden"
ARCHIVE_NAME = "freerange_elliott Instagram Archive"
VIDEO_EXTENSIONS = {".mp4", ".mov"}


def sync_videos(vault: Path, site_media_root: Path, dry_run: bool) -> tuple[int, int, int]:
    vault_media = vault / ARCHIVE_NAME / "_media"
    if not vault_media.is_dir():
        raise FileNotFoundError(f"Expected vault media directory: {vault_media}")

    copied = 0
    skipped = 0
    missing_dest_parents = 0

    for src in sorted(vault_media.rglob("*")):
        if not src.is_file() or src.suffix.lower() not in VIDEO_EXTENSIONS:
            continue

        rel = src.relative_to(vault_media)
        dest = site_media_root / rel

        if dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime and dest.stat().st_size == src.stat().st_size:
            skipped += 1
            continue

        action = "Would copy" if dry_run else "Copying"
        print(f"{action}: {rel}")

        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied += 1
        else:
            copied += 1
            if not dest.parent.exists():
                missing_dest_parents += 1

    return copied, skipped, missing_dest_parents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vault",
        type=Path,
        default=DEFAULT_VAULT,
        help=f"Obsidian vault root (default: {DEFAULT_VAULT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without copying files",
    )
    args = parser.parse_args()

    vault = args.vault.expanduser().resolve()
    site_media_root = (
        REPO_ROOT / "src/site/img/user" / ARCHIVE_NAME / "_media"
    )

    print(f"Vault media: {vault / ARCHIVE_NAME / '_media'}")
    print(f"Site media:  {site_media_root}")
    if args.dry_run:
        print("Dry run — no files will be written.\n")

    try:
        copied, skipped, _ = sync_videos(vault, site_media_root, args.dry_run)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(
        f"\nDone: {copied} to copy"
        + ("" if args.dry_run else "d")
        + f", {skipped} unchanged."
    )
    if copied and not args.dry_run:
        print(
            '\nNext: git add "src/site/img/user/freerange_elliott Instagram Archive/_media" && git commit && git push'
        )


if __name__ == "__main__":
    main()
