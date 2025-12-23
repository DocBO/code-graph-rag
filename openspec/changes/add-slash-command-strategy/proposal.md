## Why
Users need a deterministic way to trigger a semantic-seed graph expansion search, independent of model heuristics.

## What Changes
- Add a slash-command parsing strategy for user questions.
- Introduce `/semantic-seed-strategy` to run semantic search, expand graph neighbors, then answer.
- Add `/help` to list available slash commands.

## Impact
- Affected specs: assistant-commands (new)
- Affected code: prompt/tool orchestration, semantic search tooling, graph query flow
