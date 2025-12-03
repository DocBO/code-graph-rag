1. [x] Add an `OpenRouterProvider` to `codebase_rag/providers/base.py`, register it, and ensure config parsing can supply endpoint/API key defaults for orchestrator and Cypher roles.
2. [x] Update `.env.example`, README provider docs, and any CLI help text to show how to configure OpenRouter (including default endpoint and env vars).
3. [x] Extend provider-focused unit tests to cover the new provider (registry discovery, validation, model creation path) and document how to smoke-test via `make test`.
4. [x] Run `pytest` (or `make test`) plus `openspec validate add-openrouter-support --strict` to prove the requirements hold.
