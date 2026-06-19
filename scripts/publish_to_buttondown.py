#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import urllib.request
import datetime
import subprocess
from pathlib import Path

# Detect repository root relative to this script
REPO_ROOT = Path(__file__).parent.parent
GARDEN_BASE_URL = os.getenv("GARDEN_BASE_URL", "https://freerange-elliott.com")
BUTTONDOWN_API_KEY = os.getenv("BUTTONDOWN_API_KEY")

def pull_latest() -> None:
    print("⏳ Pulling latest changes from git...")
    try:
        subprocess.run(["git", "-C", str(REPO_ROOT), "pull"], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Git pull failed: {e.stderr.decode().strip()}")

def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")

def get_metadata(content: str) -> dict:
    match = re.search(r"^---\s*\n(.*?)\n---\s*\n", content, flags=re.DOTALL)
    if not match: return {}
    inner = match.group(1).strip()
    
    metadata = {}
    # Try JSON first (Digital Garden default)
    try:
        metadata = json.loads(inner)
    except json.JSONDecodeError:
        # Fallback to simple YAML regex for permalink
        perm_match = re.search(r'^permalink:\s*["\']?(.*?)["\']?\s*$', inner, re.MULTILINE)
        if perm_match:
            metadata['permalink'] = perm_match.group(1)
            
    return metadata

def build_permalink_map() -> dict:
    notes_dir = REPO_ROOT / "src/site/notes"
    mapping = {}
    if not notes_dir.exists():
        return mapping
    
    for p in notes_dir.rglob("*.md"):
        try:
            content = p.read_text(encoding="utf-8")
            meta = get_metadata(content)
            permalink = meta.get("permalink")
            
            rel_path = p.relative_to(notes_dir).with_suffix('')
            rel_path_str = str(rel_path)
            
            if not permalink:
                permalink = f"/notes/{slugify(p.stem)}"
                
            mapping[rel_path_str] = permalink
            mapping[p.stem] = permalink
        except Exception:
            pass
            
    return mapping

def strip_frontmatter(content: str) -> str:
    return re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, flags=re.DOTALL)

def strip_tags(content: str) -> str:
    return re.sub(r"(^|\s)#[^\s!@#$%^&*()=+\.,\[{\]};:'\"?><]+", "", content).strip()

def convert_images(content: str, base_url: str) -> str:
    def _replace_wiki(match: re.Match) -> str:
        name = match.group(1).split("|")[0]
        return f"![{name}]({base_url.rstrip('/')}/img/user/{name})"
    content = re.sub(r"!\[\[(.*?)\]\]", _replace_wiki, content)
    content = re.sub(r"!\[(.*?)\]\((/.*?)\)", f"![\\1]({base_url.rstrip('/')}\\2)", content)
    return content

def convert_wikilinks(content: str, base_url: str, permalink_map: dict) -> str:
    def _replace_aliased(match: re.Match) -> str:
        page, alias = match.group(1).strip(), match.group(2).strip()
        page = page.rstrip('\\').strip()
        permalink = permalink_map.get(page) or permalink_map.get(page.split('/')[-1])
        if not permalink:
            permalink = f"/notes/{slugify(page)}"
        return f"[{alias}]({base_url.rstrip('/')}/{permalink.lstrip('/')})"
    
    def _replace_simple(match: re.Match) -> str:
        page = match.group(1).strip()
        permalink = permalink_map.get(page) or permalink_map.get(page.split('/')[-1])
        if not permalink:
            permalink = f"/notes/{slugify(page)}"
        return f"[{page}]({base_url.rstrip('/')}/{permalink.lstrip('/')})"

    content = re.sub(r"\[\[([^\]|]+?)\\?\|([^\]]+)\]\]", _replace_aliased, content)
    return re.sub(r"\[\[([^\]|]+)\]\]", _replace_simple, content)

def fix_standard_links(content: str, base_url: str) -> str:
    # Only match standard links [text](/path), NOT images ![alt](/path)
    return re.sub(r"(?<!!)\[(.*?)\]\((/[^)]*)\)", f"[\\1]({base_url.rstrip('/')}\\2)", content)

def convert_callouts(content: str) -> str:
    return re.sub(r"^>\s*\[!\w+\]\s*\+?", ">", content, flags=re.MULTILINE)

def _is_list_item(line: str) -> bool:
    return bool(re.match(r"^([\*\-] |\d+\. )", line))

def _is_structural_line(line: str) -> bool:
    return bool(re.match(r"^([\*\-] |\d+\. |#{1,6} |>|!\[|```)", line))

def normalize_markdown_for_email(content: str) -> str:
    """Adjust Obsidian-style markdown for Buttondown's Python-Markdown parser."""
    lines = content.split("\n")
    out: list[str] = []

    for i, line in enumerate(lines):
        if _is_list_item(line) and out and out[-1].strip() and not _is_structural_line(out[-1]):
            out.append("")

        if re.match(r"^\* ", line):
            line = "- " + line[2:]

        out.append(line)

        if re.match(r"^!\[.*\]\(.*\)\s*$", line) and i + 1 < len(lines) and lines[i + 1].strip():
            out.append("")

    return "\n".join(out)

def transform_content(content: str, base_url: str, page_url: str, permalink_map: dict) -> str:
    body = strip_frontmatter(content)
    body = strip_tags(body)
    body = convert_images(body, base_url)
    body = convert_wikilinks(body, base_url, permalink_map)
    body = fix_standard_links(body, base_url)
    body = convert_callouts(body)
    body = normalize_markdown_for_email(body)
    
    header = f'<p align="center"><a href="{page_url}">View this on my website</a></p>\n\n---\n\n'
    return header + body

def get_existing_subjects() -> list[str]:
    if not BUTTONDOWN_API_KEY: return []
    url = "https://api.buttondown.email/v1/emails?page_size=100"
    req = urllib.request.Request(url, headers={"Authorization": f"Token {BUTTONDOWN_API_KEY}"})
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return [e['subject'] for e in data.get('results', [])]
    except Exception:
        return []

def select_file() -> Path | None:
    notes_dir = REPO_ROOT / "src/site/notes"
    if not notes_dir.exists(): return None
    
    files = sorted(notes_dir.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
    if not files: return None

    print("\nSelect a note to publish (ordered by last edited):")
    for i, f in enumerate(files, 1):
        mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
        print(f"{i:2}) [{mtime}] {f.relative_to(notes_dir)}")
    
    choice = input(f"\nNumber (1-{len(files)}) or 'q': ")
    if choice.lower() == 'q': return None
    try: return files[int(choice) - 1]
    except (ValueError, IndexError): return None

def post_draft(subject: str, body: str) -> None:
    if not BUTTONDOWN_API_KEY:
        print("Error: BUTTONDOWN_API_KEY not set.")
        sys.exit(1)

    existing = get_existing_subjects()
    if subject in existing:
        confirm = input(f"⚠️  Draft with subject '{subject}' already exists. Continue? (y/N): ")
        if confirm.lower() != 'y': return

    url = "https://api.buttondown.email/v1/emails"
    headers = {"Authorization": f"Token {BUTTONDOWN_API_KEY}", "Content-Type": "application/json"}
    payload = {"subject": subject, "body": body, "status": "draft"}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode())
            print(f"✅ Draft created: {res.get('subject')}\n🔗 Preview: https://buttondown.com/emails/{res.get('id')}")
    except urllib.error.HTTPError as e:
        print(f"❌ API Error: {e.code} {e.read().decode()}")

def main() -> None:
    parser = argparse.ArgumentParser(description="Publish Obsidian note to Buttondown. If no file is provided, an interactive list will be shown.")
    parser.add_argument("file", nargs="?", type=Path, help="Markdown file path (optional, will show list if omitted)")
    parser.add_argument("-s", "--subject", help="Override email subject")
    args = parser.parse_args()

    pull_latest()

    target_file = args.file or select_file()
    if not target_file or not target_file.exists():
        sys.exit(0 if not target_file else 1)

    raw_content = target_file.read_text(encoding="utf-8")
    metadata = get_metadata(raw_content)
    
    subject = args.subject or target_file.stem.replace(" - ", ": ").replace("_", " ")
    
    # Resolve Page URL
    permalink = metadata.get("permalink")
    if not permalink:
        permalink = f"/notes/{slugify(target_file.stem)}"
    page_url = GARDEN_BASE_URL.rstrip('/') + "/" + permalink.lstrip('/')

    print(f"🔗 Web Link: {page_url}")
    
    # Build permalink map for wikilinks
    permalink_map = build_permalink_map()
    body = transform_content(raw_content, GARDEN_BASE_URL, page_url, permalink_map)

    print(f"🚀 Publishing '{subject}'...")
    post_draft(subject, body)

if __name__ == "__main__":
    main()
