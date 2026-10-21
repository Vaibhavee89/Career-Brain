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

> This repo started as a Discord bot. It was renamed to Career Brain on
> 2026-10-17. The original code is in git history, and the Discord platform
> support lives on as an adapter in `src/careerbrain/adapters/discord_bot.py`.

## 📁 Structure

```
.
├── profile/
│   ├── about.md            # who I am, pitch, target roles
│   ├── skills.md            # skills, each backed by evidence
│   └── resume-variants/     # generated resume variants (later)
├── projects/
│   ├── career-brain.md      # real project page, filled from this repo's history
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

## 🔎 How answers are found

A question goes through three retrieval steps, and each one falls back to the next if it fails:

1. **Pinecone semantic search (primary).** At API startup, every public page is synced into a Pinecone index with integrated embeddings (`llama-text-embed-v2`). The sync replaces the index contents, so a page made private is removed on the next restart. A question is matched by meaning, which lets paraphrases like "failing data jobs" find a page that says "Airflow DAG failures". Only one Groq call is made for the answer.
2. **LLM page picker.** If Pinecone is unset, unreachable, or returns nothing, the model is shown a short index of the public pages and returns the paths that answer the question.
3. **Keyword search.** If the model's reply can't be parsed or its call fails, the original token-overlap search runs. Append-only logs such as `wins.md` are down-weighted so they don't crowd out curated pages.

Retrieval only ever sees `public: true` pages. The model answers in its own words and is asked not to copy page text.

**Why it was built this way**

- Keyword search only matched shared words, so questions worded differently from the pages found nothing.
- Sending every page to the model worked for a small corpus but used two Groq calls per question, which strains the free quota and adds latency. Pinecone's embedding removes the page-picking call.
- The fallbacks keep the chat answering when Pinecone is down, unconfigured, or still indexing, so retrieval can't silently break the chat.
- Pinecone holds only public pages, so private content never leaves the repo.

**Configuration**

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` | Answer generation, and the fallback page picker |
| `PINECONE_API_KEY` | Pinecone access. Set as a secret; never commit it. |
| `PINECONE_INDEX_HOST` | Host of the index that holds the public pages |
| `CAREERBRAIN_SITE_URL` | Base URL used to build page links in replies |
| `CAREERBRAIN_RESUME_URL` | Downloadable resume link shared when someone asks for the CV |

The Discord and Slack adapters use the keyword and LLM paths only; they don't sync to Pinecone yet.

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
4. ✅ **Public site + `/ask-me` chat** — a generated, sanitized view built only
   from `public: true` pages, for recruiters to query directly. Deployed on
   GitHub Pages, with the chat API on Render and the Next.js frontend on Vercel.
5. 🚧 **Semantic retrieval** *(current)* — Pinecone embeddings for meaning-based
   search, with the LLM and keyword fallbacks described above.

## 📜 License

MIT License. See [LICENSE](LICENSE).
