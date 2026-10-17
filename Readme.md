# 🧠 Career Brain

A personal knowledge repo: markdown pages that hold my career context — not
just *what* I built, but *why* I made the calls I made. The idea (and the
company-brain / personal-brain split) comes from
[Slite's "What is a Company Brain?"](https://slite.com/learn/company-brain).
A personal brain is the simpler, lower-stakes version: the knowledge is
mine, and a wrong answer only costs me a bad answer.

Eventually this becomes an LLM wiki wired to an MCP server, so any AI tool
can query it (`search_brain`, `get_page`, `get_resume`, `recent_wins`) and
answer things like "what's my strongest project with LLM integration?" with
real citations. Right now it's phase 1: structure and seed content.

> This repo used to host a Discord bot. That code still exists in git
> history (see [projects/discord-bot.md](projects/discord-bot.md)) — it's
> now documented as the first real project in the brain instead of being
> the thing the repo does.

## 📁 Structure

```
.
├── profile/
│   ├── about.md            # who I am, pitch, target roles
│   ├── skills.md            # skills, each backed by evidence
│   └── resume-variants/     # generated resume variants (later)
├── projects/
│   ├── discord-bot.md       # real project page, filled from this repo's history
│   └── _template.md         # copy this for a new project
├── decisions/
│   ├── 2025-07-08-switch-openai-to-groq.md   # real decision log
│   └── _template.md
├── experience/
│   └── _template.md         # public-safe summaries only — no employer internals
├── learning/                # courses, notes, what stuck
├── job-search/              # outreach, interview notes — private, not for publishing
├── inbox/                   # raw dumps, processed later by the ingest script
├── wins.md                  # dated one-line log of shipped things
├── brain.config.yaml        # paths + visibility defaults + phase roadmap
└── LICENSE
```

## ✍️ Page conventions

Every page has YAML frontmatter with at least `type`, `updated`, and
`public` (`true`/`false`). **Nothing is public by default** — a page only
gets published once it's been reviewed, and even then only the parts marked
`public: true` ever leave this repo in a generated site, resume, or chat
answer.

Project and decision pages follow the templates in `projects/_template.md`
and `decisions/_template.md`. The one rule that matters most: **cite a
source for any claim that isn't something you just reasoned through live**
(a commit, a PR, a note). Don't let a page accumulate claims nobody can
trace back to anything.

## 🗺️ Roadmap

See `brain.config.yaml` for the live status of each phase.

1. ✅ **Structure + seed pages** — folders, templates, and real content for
   the one project this repo already had history for.
2. ✅ **Ingest script + weekly PR workflow** — drop notes in `inbox/`, a
   scheduled job reads it plus recent GitHub activity, updates the right
   pages, and opens a PR (never pushes directly) so nothing lands unreviewed.
3. ✅ **MCP server** — 4 tools (`search_brain`, `get_page`, `get_resume`,
   `recent_wins`) over this repo, so any AI tool can answer questions from
   it with citations.
4. 🚧 **Public site + `/ask-me` chat** *(current)* — a generated, sanitized
   view built only from `public: true` pages, for recruiters to query
   directly. Site and chat are built; deployment is pending.

## 📜 License

MIT License. See [LICENSE](LICENSE).
