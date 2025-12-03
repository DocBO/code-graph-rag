# llm-provider-routing Specification

## Purpose
TBD - created by archiving change add-openrouter-support. Update Purpose after archive.
## Requirements
### Requirement: OpenRouter Provider Support
The CLI SHALL treat `openrouter` as a first-class LLM provider option for orchestrator and Cypher roles, using OpenAI-compatible semantics with an OpenRouter base URL and API key authentication.

#### Scenario: Configure OpenRouter via .env
- **GIVEN** a `.env` with `ORCHESTRATOR_PROVIDER=openrouter`, `ORCHESTRATOR_MODEL=gpt-4o-mini`, and `ORCHESTRATOR_API_KEY` set
- **WHEN** the agent starts without CLI overrides
- **THEN** it initializes the orchestrator against `https://openrouter.ai/api/v1` (unless overridden by `ORCHESTRATOR_ENDPOINT`) and succeeds without validation errors.

#### Scenario: Override endpoint for Cypher role
- **GIVEN** CLI flags `--cypher openrouter:qwen-2.5`
- **AND** `CYPHER_API_KEY` is set
- **WHEN** the Cypher generator initializes
- **THEN** it uses the OpenRouter provider with the provided model and accepts a custom endpoint if supplied, falling back to the default otherwise.
