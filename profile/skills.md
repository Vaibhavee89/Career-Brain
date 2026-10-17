---
type: profile
updated: 2026-10-17
public: false
---

<!-- Each skill cites evidence: a project page, a decision log, a commit, a link.
     Don't add a skill here without something that backs it. -->

## Python

- Evidence: [projects/discord-bot.md](../projects/discord-bot.md) — `discord.py` bot, async event handlers, command framework.

## LLM / AI API integration

- Evidence: [projects/discord-bot.md](../projects/discord-bot.md), [decisions/2025-07-08-switch-openai-to-groq.md](../decisions/2025-07-08-switch-openai-to-groq.md) — integrated and then migrated between two LLM providers (OpenAI → Groq) in a live project.

## Dependency / environment management

- Evidence: this repo's git history — migrated the project from `pip` + `requirements.txt` to `uv` (`pyproject.toml`, `uv.lock`, pinned `.python-version`).

<!-- TODO: add more skills as projects/decisions accumulate evidence for them. -->
