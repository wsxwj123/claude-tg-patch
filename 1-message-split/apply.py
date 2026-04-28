#!/usr/bin/env python3
"""Patch the official claude-plugins/telegram server.ts to support
multi-paragraph messages: one logical reply that splits into several
Telegram messages on every blank-line boundary.

Adds:
  - Access fields:    splitOnParagraph, paragraphDelay
  - reply behaviour:  text.split('\\n\\n') → multiple Telegram messages
                      with optional `typing…` action between them

Idempotent: safe to run many times — checks for marker strings before
each substitution.

Usage:
    python apply.py /path/to/external_plugins/telegram/server.ts

Then in your bot's access.json add:
    "splitOnParagraph": true,
    "paragraphDelay": 600
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path


def patch(content: str) -> str:
    # 1. type: add fields
    if "splitOnParagraph?" not in content:
        content = content.replace(
            "chunkMode?: 'length' | 'newline'",
            "chunkMode?: 'length' | 'newline'\n  splitOnParagraph?: boolean\n  paragraphDelay?: number",
        )

    # 2. readAccess: parse fields
    if "splitOnParagraph: parsed.splitOnParagraph" not in content:
        content = content.replace(
            "chunkMode: parsed.chunkMode,",
            "chunkMode: parsed.chunkMode,\n      splitOnParagraph: parsed.splitOnParagraph,\n      paragraphDelay: parsed.paragraphDelay,",
        )

    # 3. reply: paragraph split
    if "const paragraphs = access.splitOnParagraph" not in content:
        old = r"const chunks = chunk\(text, limit, mode\)\s+const sentIds: number\[\] = \[\]"
        new = (
            "const paragraphs = access.splitOnParagraph\n"
            "          ? text.split('\\n\\n').map(s => s.trim()).filter(s => s.length > 0)\n"
            "          : [text]\n"
            "        const allChunks: string[] = []\n"
            "        for (const para of paragraphs) {\n"
            "          allChunks.push(...chunk(para, limit, mode))\n"
            "        }\n"
            "        const sentIds: number[] = []\n"
            "        const delay = access.splitOnParagraph ? (access.paragraphDelay ?? 0) : 0"
        )
        content = re.sub(old, new, content)
        content = content.replace(
            "for (let i = 0; i < chunks.length; i++)",
            "for (let i = 0; i < allChunks.length; i++)",
        )
        content = content.replace("chunks[i]", "allChunks[i]")
        content = re.sub(r"of \$\{chunks\.length\}", "of ${allChunks.length}", content)

        # delay between paragraphs (typing… indicator)
        content = content.replace(
            "for (let i = 0; i < allChunks.length; i++) {",
            "for (let i = 0; i < allChunks.length; i++) {\n"
            "            if (i > 0 && delay > 0) {\n"
            "              void bot.api.sendChatAction(chat_id, 'typing').catch(() => {})\n"
            "              await new Promise(r => setTimeout(r, delay))\n"
            "            }",
        )
    return content


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("server_ts", help="path to telegram plugin's server.ts")
    ap.add_argument("--no-backup", action="store_true", help="skip writing server.ts.bak")
    args = ap.parse_args()

    p = Path(args.server_ts).expanduser().resolve()
    if not p.is_file():
        print(f"error: {p} not found", file=sys.stderr)
        return 1

    if not args.no_backup and not p.with_suffix(p.suffix + ".bak").exists():
        shutil.copy2(p, p.with_suffix(p.suffix + ".bak"))
        print(f"backed up → {p.name}.bak")

    src = p.read_text(encoding="utf-8")
    out = patch(src)
    if out == src:
        print("no changes (already patched)")
        return 0
    p.write_text(out, encoding="utf-8")
    print(f"patched: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
