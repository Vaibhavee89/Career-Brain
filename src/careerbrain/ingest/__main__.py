from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import httpx

from careerbrain.core.llm import GroqProvider
from careerbrain.core.retrieval import load_pages
from careerbrain.ingest.generate import generate_outputs
from careerbrain.ingest.github_activity import (
    append_wins,
    fetch_public_events,
    merged_pr_lines,
)
from careerbrain.ingest.inbox import process_inbox

API_KEY_ENV = "GROQ_API_KEY"
WINDOW_DAYS = 7


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Weekly ingest and generate for the brain."
    )
    parser.add_argument("--root", type=Path, required=True, help="brain data repo root")
    parser.add_argument("--github-user", default=os.environ.get("GITHUB_USER", ""))
    parser.add_argument("--skip-github", action="store_true")
    parser.add_argument("--skip-inbox", action="store_true")
    parser.add_argument("--summary", type=Path, default=None, help="write PR body here")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    today = dt.date.today()
    summary = [f"Weekly ingest for {today.isoformat()}.", ""]

    if not args.skip_github:
        if not args.github_user:
            print("Set GITHUB_USER or pass --github-user.", file=sys.stderr)
            return 1
        with httpx.Client(timeout=30.0) as client:
            events = fetch_public_events(
                args.github_user, os.environ.get("GITHUB_TOKEN"), client
            )
        since = today - dt.timedelta(days=WINDOW_DAYS)
        added = append_wins(root, merged_pr_lines(events, since))
        summary.append(f"- GitHub: {added} new merged PR(s) added to wins.md.")
        print(f"github: {added} new win(s)")

    if not args.skip_inbox:
        api_key = os.environ.get(API_KEY_ENV)
        if api_key:
            report = process_inbox(root, GroqProvider(api_key), today)
            summary.append(
                f"- Inbox: {report.notes} note(s), {report.applied} claim(s) applied, "
                f"{report.rejected} rejected, {report.unparseable} unparseable, "
                f"{report.removed} note(s) removed."
            )
            print(
                f"inbox: notes={report.notes} applied={report.applied} "
                f"rejected={report.rejected} unparseable={report.unparseable} "
                f"removed={report.removed}"
            )
        else:
            summary.append(f"- Inbox: skipped, {API_KEY_ENV} not set.")
            print("inbox: skipped")

    pages = load_pages(root)
    written = generate_outputs(root, pages, today)
    summary.append("- Generated: " + ", ".join(f"`{path}`" for path in written) + ".")
    print(f"generated: {len(written)} file(s)")

    if args.summary:
        args.summary.write_text("\n".join(summary) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
