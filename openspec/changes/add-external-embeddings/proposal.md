## Why
The current semantic embedding flow requires local torch/transformers and an embedded Qdrant client. We want to support a remote Qdrant instance and external embedding APIs (configured via `.env`) so we can skip heavy local dependencies.

## What Changes
- Add configuration for external Qdrant (host/port/API key) and external embedding API endpoints/keys in `.env`.
- Update embedding generation to call an external embedder over HTTP and store vectors in Qdrant (no local torch/transformers).
- Provide docs and tests to cover the new configuration.

## Impact
- Affected specs: `semantic-search`
- Affected code: embedding pipeline, configuration handling, README/env examples, tests.
