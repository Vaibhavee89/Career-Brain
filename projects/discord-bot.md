---
type: project
status: shipped
updated: 2026-10-17
skills: [python, discord.py, llm-api-integration, prompt-design]
links: [https://github.com/Vaibhavee89/DiscordBot]
public: false   # TODO: flip to true once reviewed for recruiter visibility
---

## What it is

A Discord bot (built with Python and `discord.py`) that chats as an AI assistant when mentioned or DMed, answers one-off questions, explains concepts, and summarizes text via Groq's hosted `llama-3.3-70b-versatile` model. It also carries a standard moderation toolkit (kick/ban/mute/clear/lock/slowmode) and a few utility/info commands (`!ping`, `!userinfo`, `!serverinfo`, role management, join/leave welcome embeds).

Source: `main.py` as of commit `3fce8fc` (before this repo was repurposed into the Career Brain project on 2026-10-17; the bot code itself lives on in git history).

## Why I built it

<!-- TODO: fill in — what prompted this project, e.g. a server you ran, a feature you wanted for a community, a way to learn discord.py/LLM integration. Not inferable from the code alone. -->

## Key decisions (and why)

- **Switched the LLM backend from OpenAI to Groq**, after initially shipping with OpenAI. (commits `c31703e` "Add OpenAI integration", `400a9d2` "Switch to a different AI service", `0cad213` "Updated bot to use Groq API instead of OpenAI", all 2025-07-08.)
  <!-- TODO: the actual why — cost, latency, rate limits, API access? -->
- **Left the `members` privileged intent disabled** (`intents.members` commented out in `main.py`) rather than requesting it from Discord, after hitting the privileged-intents error early on (commit `35b895a` "Explained privileged intents error", 2025-07-07). Trades away some member-cache features for a bot that works without an approval step.
- **Mention/DM triggers free-form AI chat; a `!` prefix triggers discrete commands** (`!ask`, `!explain`, `!summarize`, `!chat`, moderation, utility) — keeps natural conversation and explicit commands from colliding in `on_message`.
- **Replies longer than 2000 characters are chunked** before sending, to stay under Discord's per-message limit, rather than truncating.

## Results / metrics

<!-- TODO: did this run in a real server? how many members, how long, any feedback? -->

## What I'd change

- Build the Groq client lazily (or after the env-var check at the bottom of `main.py`) instead of at import time — right now, a missing `GROQ_API_KEY` crashes with a raw `groq.GroqError` traceback before the script's own "please set this env var" message ever prints.
- Split `main.py` into modules (bot setup, AI commands, moderation commands) now that it's ~400 lines in one file.
- <!-- TODO: anything else you'd do differently -->
