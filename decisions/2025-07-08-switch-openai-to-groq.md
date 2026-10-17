---
type: decision
date: 2025-07-08
project: projects/discord-bot.md
public: false
---

## Context

The Discord bot's AI replies were first built on OpenAI's API (commit `c31703e`, "Add OpenAI integration for conversational AI"). Same day, the API backing the bot's responses was changed.

## Options considered

- Keep OpenAI.
- Move to Groq (`llama-3.3-70b-versatile`, OpenAI-compatible-style client).

## Decision

Switched to Groq. Commits: `400a9d2` "Checkpoint before assistant change: Switch to a different AI service for processing user requests" → `0cad213` "Assistant checkpoint: Updated bot to use Groq API instead of OpenAI".

## Why

<!-- TODO: the actual reasoning isn't recoverable from the commit messages alone —
     fill in whatever drove it: cost, speed, free-tier limits, API key access, etc. -->

## Outcome

The bot has run on Groq since (`pyproject.toml` / `requirements.txt` only ever listed `groq`, never `openai`, after this point — aside from a stray `openai` entry that lingered in `pyproject.toml`'s dependency list unused).
<!-- TODO: did Groq hold up — latency, quality, rate limits, any regrets? -->
