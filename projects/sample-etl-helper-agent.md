---
type: project
status: shipped
updated: 2026-10-17
skills: [python, llm-agents, mcp, airflow]
links: []
public: true
---

> SAMPLE PAGE: throwaway content for retrieval testing. Delete before real use.

## What it is

An AI agent that lets analysts debug failed Airflow DAG runs on their own, instead of waiting on the Data Platform team.

## Why I built it

The Data Platform team was handling 200+ DAG run failures per day by hand. Source: CV, Blinkit SDE intern entry.

## Key decisions (and why)

- Connected the agent to Airflow, Commuter, Slack, and Grafana through MCP servers, so it could pull run state from each system instead of relying on pasted logs. Source: CV.
- Added custom diagnostics for Spot Instance interruptions and OOM failures. Source: CV.

## Results / metrics

- Enabled analysts to self-resolve 200+ DAG run failures per day. Source: CV.

## What I'd change

<!-- Sample: fill in real hindsight here. -->
