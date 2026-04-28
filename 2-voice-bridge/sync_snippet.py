#!/usr/bin/env python3
"""Inject voice-bridge CLAUDE.md snippets into your bot's CLAUDE.md.

The snippets are wrapped by:
    <!-- VOICE-REPLY-START -->        ... <!-- VOICE-REPLY-END -->
    <!-- GROUP-AUTOCHAT-START -->     ... <!-- GROUP-AUTOCHAT-END -->

Idempotent: existing block → replace; no block → append.
Anything you write *outside* a block (bot-specific overrides) is kept.

Usage:
    python sync_snippet.py /path/to/bot/CLAUDE.md [more/CLAUDE.md ...]

Or copy the snippet files manually if you prefer.
"""
import argparse
import re
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent

# (snippet_source, start_marker, end_marker)
SNIPPETS = [
    (HERE / "CLAUDE-voice-reply-snippet.md", "VOICE-REPLY-START", "VOICE-REPLY-END"),
    (HERE / "CLAUDE-group-autochat-snippet.md", "GROUP-AUTOCHAT-START", "GROUP-AUTOCHAT-END"),
]


def sync_one(target: Path, snippet_text: str, start_marker: str, end_marker: str) -> bool:
    pattern = re.compile(f"<!-- {start_marker}.*?<!-- {end_marker} -->", re.DOTALL)
    content = target.read_text(encoding="utf-8")
    if pattern.search(content):
        new = pattern.sub(snippet_text, content)
        if new != content:
            target.write_text(new, encoding="utf-8")
            return True
        return False
    target.write_text(content.rstrip() + "\n\n" + snippet_text + "\n", encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("targets", nargs="+", help="paths to CLAUDE.md files to update")
    args = ap.parse_args()

    changed = 0
    for t in args.targets:
        p = Path(t).expanduser().resolve()
        if not p.exists():
            print(f"✗ not found: {p}", file=sys.stderr)
            continue
        for src, start, end in SNIPPETS:
            if not src.exists():
                print(f"  ⚠ snippet missing: {src.name}", file=sys.stderr)
                continue
            snippet_text = src.read_text(encoding="utf-8").strip()
            if sync_one(p, snippet_text, start, end):
                print(f"✓ [{start}] → {p}")
                changed += 1
    print(f"done, {changed} change(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
