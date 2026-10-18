from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from collections.abc import Sequence
from pathlib import Path

import markdown

from careerbrain.core.retrieval import load_pages
from careerbrain.core.types import Page
from careerbrain.ingest.generate import build_profile_readme

COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
PAGES_DIR = "pages"
CSS = """
:root { color-scheme: light dark; --fg: #1d1d1f; --bg: #fff; --muted: #6e6e73; --accent: #0b57d0; --line: #d2d2d7; }
@media (prefers-color-scheme: dark) {
  :root { --fg: #f5f5f7; --bg: #111; --muted: #a1a1a6; --accent: #7aa7ff; --line: #3a3a3c; }
}
body { margin: 0; font: 16px/1.6 system-ui, sans-serif; color: var(--fg); background: var(--bg); }
header, main { max-width: 760px; margin: 0 auto; padding: 16px; }
header { display: flex; justify-content: space-between; border-bottom: 1px solid var(--line); }
header a { color: var(--fg); text-decoration: none; font-weight: 600; }
nav a { color: var(--accent); margin-left: 16px; text-decoration: none; }
a { color: var(--accent); }
code, pre { font-family: ui-monospace, monospace; }
#log { min-height: 200px; border: 1px solid var(--line); border-radius: 8px; padding: 12px; }
#log p { margin: 8px 0; white-space: pre-wrap; }
#log p.you { color: var(--muted); }
#log p.sources { color: var(--muted); font-size: 14px; }
form { display: flex; gap: 8px; margin-top: 12px; }
input { flex: 1; padding: 10px; font: inherit; border-radius: 8px; border: 1px solid var(--line); background: transparent; color: var(--fg); }
button { padding: 10px 16px; font: inherit; border-radius: 8px; border: 0; background: var(--accent); color: #fff; }
#status { color: var(--muted); min-height: 1.5em; }
"""
LAYOUT = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<header><a href="{root}index.html">Career Brain</a><nav><a href="{root}ask-me.html">Ask me</a></nav></header>
<main>
{body}
</main>
{script}
</body>
</html>
"""
ASK_BODY = """<h1>Ask me</h1>
<p>Answers come only from public pages.</p>
<div id="log" aria-live="polite"></div>
<form id="ask-form" autocomplete="off">
  <input id="question" maxlength="2000" placeholder="Ask about my work" aria-label="Question">
  <button type="submit">Ask</button>
</form>
<div id="status"></div>"""
CHAT_SCRIPT = """<script>
(function () {
  var cfg = window.CAREERBRAIN || {};
  var form = document.getElementById("ask-form");
  var log = document.getElementById("log");
  var input = document.getElementById("question");
  var status = document.getElementById("status");
  if (!cfg.apiUrl) {
    form.hidden = true;
    status.textContent = "Chat is not configured for this site.";
    return;
  }
  function newId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return Math.random().toString(36).slice(2) + Date.now().toString(36);
  }
  var userId = "";
  try {
    userId = localStorage.getItem("cb-user") || "";
    if (!userId) { userId = newId(); localStorage.setItem("cb-user", userId); }
  } catch (e) { userId = newId(); }
  function addMessage(kind, text) {
    var p = document.createElement("p");
    p.className = kind;
    p.textContent = text;
    log.appendChild(p);
    p.scrollIntoView({ block: "end" });
  }
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var question = input.value.trim();
    if (!question) return;
    input.value = "";
    addMessage("you", question);
    status.textContent = "Thinking...";
    fetch(cfg.apiUrl + "/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, message: question })
    }).then(function (response) {
      var retry = response.headers.get("Retry-After");
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (response.status === 429) {
          addMessage("bot", "Too many questions. Try again in about " + (retry || "a few") + " seconds.");
        } else if (!response.ok) {
          addMessage("bot", data.detail || "Something went wrong.");
        } else {
          (data.chunks || []).forEach(function (chunk) { addMessage("bot", chunk); });
          if (data.sources && data.sources.length) {
            addMessage("sources", "Sources: " + data.sources.join(", "));
          }
        }
      });
    }).catch(function () {
      addMessage("bot", "Could not reach the chat service.");
    }).then(function () {
      status.textContent = "";
    });
  });
})();
</script>"""


def build_site(root: Path, out: Path, api_url: str | None = None) -> list[str]:
    public = [page for page in load_pages(root) if page.is_public]
    out.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(out / PAGES_DIR, ignore_errors=True)
    (out / PAGES_DIR).mkdir()
    written: list[str] = []

    index_body = render_markdown(build_profile_readme(public))
    index_body += (
        "<h2>Pages</h2>\n<ul>\n"
        + "".join(
            f'<li><a href="{PAGES_DIR}/{_slug(page.path)}.html">{html.escape(_title(page))}</a></li>\n'
            for page in public
        )
        + "</ul>"
    )
    written.append(
        _write(out / "index.html", _layout("Career Brain", "", index_body, ""))
    )

    for page in public:
        target = out / PAGES_DIR / f"{_slug(page.path)}.html"
        body = render_markdown(_without_title(page.body))
        target.write_text(
            _layout(
                _title(page), "../", f"<h1>{html.escape(_title(page))}</h1>\n{body}", ""
            ),
            encoding="utf-8",
        )
        written.append(target.relative_to(out).as_posix())

    config = json.dumps({"apiUrl": api_url.rstrip("/") if api_url else None}).replace(
        "</", "<\\/"
    )
    script = f"<script>window.CAREERBRAIN = {config};</script>\n{CHAT_SCRIPT}"
    written.append(_write(out / "ask-me.html", _layout("Ask me", "", ASK_BODY, script)))
    return written


def render_markdown(text: str) -> str:
    return markdown.markdown(COMMENT.sub("", text), extensions=["fenced_code"])


def _layout(title: str, root: str, body: str, script: str) -> str:
    return LAYOUT.format(
        title=html.escape(title), css=CSS, root=root, body=body, script=script
    )


def _write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return path.name


def _slug(path: str) -> str:
    return path.removesuffix(".md").replace("/", "--")


def _without_title(body: str) -> str:
    lines = body.split("\n")
    for index, line in enumerate(lines):
        if line.startswith("# "):
            return "\n".join(lines[:index] + lines[index + 1 :])
    return body


def _title(page: Page) -> str:
    for line in page.body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return page.path.rsplit("/", 1)[-1].removesuffix(".md").replace("-", " ").title()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the public Career Brain site.")
    parser.add_argument("--root", type=Path, required=True, help="brain data repo root")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument("--api-url", default=None, help="base URL of the /ask API")
    args = parser.parse_args(argv)
    written = build_site(args.root.resolve(), args.out.resolve(), args.api_url)
    print(f"site: {len(written)} file(s) written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
