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
from careerbrain.core.types import PAGES_URL_DIR, Page, page_slug, page_title
from careerbrain.ingest.generate import build_profile_readme

COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
PAGES_DIR = PAGES_URL_DIR
CATEGORIES = (
    ("project", "projects", "Projects"),
    ("experience", "experience", "Experience"),
    ("decision", "decisions", "Decisions"),
)
SUGGESTED_QUESTIONS = (
    "What's Vaibhavee's strongest project?",
    "Tell me about Vaibhavee's experience.",
    "Can I get Vaibhavee's resume?",
    "What are Vaibhavee's skills?",
)
CSS = """
:root { color-scheme: light dark; --fg: #1d1d1f; --bg: #fff; --muted: #6e6e73; --accent: #0b57d0; --line: #d2d2d7; --card: #f5f5f7; --ok: #1a7f37; --bad: #c0392b; }
@media (prefers-color-scheme: dark) {
  :root { --fg: #f5f5f7; --bg: #111; --muted: #a1a1a6; --accent: #7aa7ff; --line: #3a3a3c; --card: #1c1c1e; --ok: #3fb950; --bad: #ff6b5e; }
}
body { margin: 0; font: 16px/1.6 system-ui, sans-serif; color: var(--fg); background: var(--bg); }
header, main { max-width: 760px; margin: 0 auto; padding: 16px; }
header { display: flex; flex-wrap: wrap; gap: 8px 16px; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--line); }
header a.brand { color: var(--fg); text-decoration: none; font-weight: 600; }
nav a { color: var(--accent); margin-left: 16px; text-decoration: none; }
nav a[aria-current="page"] { text-decoration: underline; }
a { color: var(--accent); }
code, pre { font-family: ui-monospace, monospace; }
ul.cards { list-style: none; padding: 0; display: grid; gap: 8px; }
ul.cards li { border: 1px solid var(--line); border-radius: 8px; padding: 12px 16px; }
ul.cards a { text-decoration: none; font-weight: 600; }

.badge { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--muted); border: 1px solid var(--line); border-radius: 999px; padding: 4px 10px; margin: 8px 0; }
.badge .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
.badge.ok .dot { background: var(--ok); }
.badge.bad .dot { background: var(--bad); }

#log { min-height: 200px; display: flex; flex-direction: column; gap: 10px; padding: 4px 0; }
.msg { display: flex; gap: 8px; max-width: 85%; }
.msg .avatar { flex: none; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; background: var(--card); color: var(--muted); }
.msg .bubble { border-radius: 12px; padding: 8px 12px; white-space: pre-wrap; }
.msg.you { align-self: flex-end; flex-direction: row-reverse; }
.msg.you .bubble { background: var(--accent); color: #fff; }
.msg.bot .bubble { background: var(--card); }
.msg.you .avatar { background: var(--accent); color: #fff; }
.sources { font-size: 13px; color: var(--muted); display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.sources a { border: 1px solid var(--line); border-radius: 999px; padding: 2px 10px; text-decoration: none; color: var(--muted); }

.chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }
.chips button { font: inherit; font-size: 13px; border: 1px solid var(--line); background: transparent; color: var(--fg); border-radius: 999px; padding: 6px 12px; cursor: pointer; }
.chips button:hover { border-color: var(--accent); color: var(--accent); }

form { display: flex; gap: 8px; margin-top: 12px; }
input { flex: 1; padding: 10px; font: inherit; border-radius: 8px; border: 1px solid var(--line); background: transparent; color: var(--fg); }
button { padding: 10px 16px; font: inherit; border-radius: 8px; border: 0; background: var(--accent); color: #fff; cursor: pointer; }
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
<header><a class="brand" href="{root}index.html">Career Brain</a><nav>{nav}</nav></header>
<main>
{body}
</main>
{script}
</body>
</html>
"""
ASK_BODY = """<h1>Ask me</h1>
<p>Answers come only from public pages.</p>
<div id="chat-badge"></div>
<div id="log" aria-live="polite"></div>
<div class="chips" id="chips"></div>
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
  var badge = document.getElementById("chat-badge");
  var chips = document.getElementById("chips");
  var suggestions = cfg.suggestions || [];
  var pagesDir = cfg.pagesDir || "pages";
  if (!cfg.apiUrl) {
    form.hidden = true;
    status.textContent = "Chat is not configured for this site.";
    return;
  }
  function setBadge(ok) {
    while (badge.firstChild) { badge.removeChild(badge.firstChild); }
    var span = document.createElement("span");
    span.className = "badge " + (ok ? "ok" : "bad");
    var dot = document.createElement("span");
    dot.className = "dot";
    span.appendChild(dot);
    span.appendChild(document.createTextNode(ok ? "LLM Wiki Active" : "Chat is offline"));
    badge.appendChild(span);
  }
  fetch(cfg.apiUrl + "/healthz").then(function (r) { setBadge(r.ok); }).catch(function () { setBadge(false); });
  suggestions.forEach(function (text) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = text;
    btn.addEventListener("click", function () {
      input.value = text;
      form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event("submit", { cancelable: true }));
    });
    chips.appendChild(btn);
  });
  function newId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return Math.random().toString(36).slice(2) + Date.now().toString(36);
  }
  var userId = "";
  try {
    userId = localStorage.getItem("cb-user") || "";
    if (!userId) { userId = newId(); localStorage.setItem("cb-user", userId); }
  } catch (e) { userId = newId(); }
  function slug(path) {
    return path.replace(/\\.md$/, "").split("/").join("--");
  }
  function addMessage(role, text) {
    var row = document.createElement("div");
    row.className = "msg " + role;
    var avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = role === "you" ? "You" : "AI";
    var bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    row.appendChild(avatar);
    row.appendChild(bubble);
    log.appendChild(row);
    row.scrollIntoView({ block: "end" });
  }
  function addSources(paths) {
    var row = document.createElement("div");
    row.className = "sources";
    row.appendChild(document.createTextNode("Sources:"));
    paths.forEach(function (path) {
      var a = document.createElement("a");
      a.href = pagesDir + "/" + slug(path) + ".html";
      a.textContent = path;
      row.appendChild(a);
    });
    log.appendChild(row);
    row.scrollIntoView({ block: "end" });
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
            addSources(data.sources);
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

    by_type: dict[str, list[Page]] = {}
    for page in public:
        by_type.setdefault(page.frontmatter.get("type", ""), []).append(page)
    nav_items = [
        (f"{slug}.html", label)
        for fm_type, slug, label in CATEGORIES
        if by_type.get(fm_type)
    ]
    nav_items.append(("ask-me.html", "Ask Me"))

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
        _write(
            out / "index.html", _layout("Career Brain", "", index_body, "", nav_items)
        )
    )

    for page in public:
        target = out / PAGES_DIR / f"{_slug(page.path)}.html"
        body = render_markdown(_without_title(page.body))
        target.write_text(
            _layout(
                _title(page),
                "../",
                f"<h1>{html.escape(_title(page))}</h1>\n{body}",
                "",
                nav_items,
            ),
            encoding="utf-8",
        )
        written.append(target.relative_to(out).as_posix())

    for fm_type, slug, label in CATEGORIES:
        pages = by_type.get(fm_type)
        if not pages:
            continue
        body = (
            f"<h1>{html.escape(label)}</h1>\n<ul class='cards'>\n"
            + "".join(
                f'<li><a href="{PAGES_DIR}/{_slug(page.path)}.html">{html.escape(_title(page))}</a></li>\n'
                for page in pages
            )
            + "</ul>"
        )
        written.append(
            _write(out / f"{slug}.html", _layout(label, "", body, "", nav_items))
        )

    config = json.dumps(
        {
            "apiUrl": api_url.rstrip("/") if api_url else None,
            "pagesDir": PAGES_DIR,
            "suggestions": list(SUGGESTED_QUESTIONS),
        }
    ).replace("</", "<\\/")
    script = f"<script>window.CAREERBRAIN = {config};</script>\n{CHAT_SCRIPT}"
    written.append(
        _write(out / "ask-me.html", _layout("Ask me", "", ASK_BODY, script, nav_items))
    )
    return written


def render_markdown(text: str) -> str:
    return markdown.markdown(COMMENT.sub("", text), extensions=["fenced_code"])


def _layout(
    title: str,
    root: str,
    body: str,
    script: str,
    nav_items: Sequence[tuple[str, str]] = (("ask-me.html", "Ask Me"),),
) -> str:
    nav = "".join(
        f'<a href="{root}{href}">{html.escape(label)}</a>' for href, label in nav_items
    )
    return LAYOUT.format(
        title=html.escape(title), css=CSS, root=root, body=body, script=script, nav=nav
    )


def _write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return path.name


_slug = page_slug
_title = page_title


def without_title(body: str) -> str:
    """A page's body with its leading `# ` heading line removed."""
    lines = body.split("\n")
    for index, line in enumerate(lines):
        if line.startswith("# "):
            return "\n".join(lines[:index] + lines[index + 1 :])
    return body


_without_title = without_title


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
