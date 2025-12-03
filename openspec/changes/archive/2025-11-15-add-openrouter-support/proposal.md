## Why
Users want to use OpenRouter as a first-class LLM provider instead of relying on ad-hoc OpenAI compatibility tweaks. The CLI currently recognizes only Google, OpenAI, and Ollama, so OpenRouter configs fail validation and docs do not describe how to connect.

## What Changes
- Add an `openrouter` provider that plugs into the existing provider registry with sensible defaults (base URL, validation, optional headers).
- Extend configuration/docs/tests so orchestrator and Cypher roles can target OpenRouter through `.env`, CLI flags, or defaults.
- Document the provider in README and `.env.example`, including key env vars and example commands.

## Impact
- Affected specs: `llm-provider-routing`
- Affected code: provider registry/module, settings parsing, `.env.example`, README, tests covering providers.
