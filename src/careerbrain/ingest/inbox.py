from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path

from careerbrain.core.llm import LLMError, LLMProvider
from careerbrain.core.memory import Message
from careerbrain.core.retrieval import resolve_inside
from careerbrain.core.types import PathTraversalError

WINS_FILE = "wins.md"
INBOX_DIR = "inbox"
CLAIM_DIRS = (
    "profile",
    "projects",
    "decisions",
    "experience",
    "learning",
    "job-search",
)
PROMPT = """You pick career facts worth recording from a raw note.
Reply with only a JSON array. Each item is an object with keys:
  "target": one of the allowed targets below,
  "heading": the exact text of a "## " heading in that target, or null,
  "text": a phrase copied word for word from the note.
Copy text exactly; do not paraphrase. Return [] if nothing is worth recording.
Allowed targets:
"""


@dataclass(frozen=True)
class Claim:
    target: str
    heading: str | None
    text: str


@dataclass
class InboxReport:
    notes: int = 0
    applied: int = 0
    rejected: int = 0
    unparseable: int = 0
    removed: int = 0


def allowed_targets(root: Path) -> list[str]:
    targets = [WINS_FILE] if (root / WINS_FILE).is_file() else []
    for directory in CLAIM_DIRS:
        for path in sorted((root / directory).rglob("*.md")):
            rel = path.relative_to(root).as_posix()
            if "_template" in path.name or "resume-variants" in path.parts:
                continue
            targets.append(rel)
    return targets


def parse_claims(raw: str) -> list[Claim] | None:
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        items = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(items, list):
        return None
    claims = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            return None
        target = item.get("target")
        heading = item.get("heading")
        if not isinstance(target, str) or not (
            heading is None or isinstance(heading, str)
        ):
            return None
        claims.append(Claim(target=target, heading=heading, text=item["text"].strip()))
    return claims


def apply_claim(
    root: Path,
    claim: Claim,
    note_rel: str,
    note_text: str,
    today: dt.date,
    allowed: set[str],
) -> bool:
    if claim.target not in allowed or not claim.text:
        return False
    if _squash(claim.text) not in _squash(note_text):
        return False
    try:
        path = resolve_inside(root, claim.target)
    except PathTraversalError:
        return False
    if not path.is_file():
        return False

    body = path.read_text(encoding="utf-8")
    if claim.heading is not None and f"## {claim.heading}" not in body.split("\n"):
        return False
    if claim.text in body:
        return True
    if claim.target == WINS_FILE:
        entry = f"- {today.isoformat()} — {claim.text} (source: {note_rel})"
    else:
        entry = f"- {claim.text} (source: {note_rel})"

    if claim.heading is None:
        updated = body.rstrip("\n") + "\n" + entry + "\n"
    else:
        updated = _insert_under_heading(body, claim.heading, entry)
        if updated is None:
            return False
    path.write_text(updated, encoding="utf-8")
    return True


def process_inbox(root: Path, llm: LLMProvider, today: dt.date) -> InboxReport:
    report = InboxReport()
    inbox = root / INBOX_DIR
    if not inbox.is_dir():
        return report
    allowed = allowed_targets(root)
    prompt = PROMPT + "\n".join(f"- {target}" for target in allowed)
    for note in sorted(inbox.glob("*.md")):
        if note.name == "README.md":
            continue
        report.notes += 1
        note_text = note.read_text(encoding="utf-8")
        note_rel = note.relative_to(root).as_posix()
        try:
            raw = llm.complete([Message("system", prompt), Message("user", note_text)])
        except LLMError:
            report.unparseable += 1
            continue
        claims = parse_claims(raw)
        if claims is None:
            report.unparseable += 1
            continue
        results = [
            apply_claim(root, claim, note_rel, note_text, today, set(allowed))
            for claim in claims
        ]
        report.applied += results.count(True)
        report.rejected += results.count(False)
        if results and all(results):
            note.unlink()
            report.removed += 1
    return report


def _squash(text: str) -> str:
    return " ".join(text.split())


def _insert_under_heading(body: str, heading: str, entry: str) -> str | None:
    lines = body.split("\n")
    try:
        start = lines.index(f"## {heading}")
    except ValueError:
        return None
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    insert_at = end
    while insert_at > start + 1 and lines[insert_at - 1].strip() == "":
        insert_at -= 1
    lines.insert(insert_at, entry)
    return "\n".join(lines)
