## MODIFIED Requirements

### Requirement: External Semantic Embeddings
The system SHALL support generating embeddings via an external API (no local torch/transformers) and storing them in a configurable Qdrant instance.

#### Scenario: External embed + remote Qdrant
- **GIVEN** `.env` defines EMBED_ENDPOINT/EMBED_API_KEY and QDRANT_HOST/QDRANT_PORT (and optional QDRANT_API_KEY)
- **WHEN** the embedding pipeline runs
- **THEN** code is embedded via the external API and vectors are stored in the remote Qdrant collection without requiring local torch/transformers.

#### Scenario: Disable local semantic deps
- **GIVEN** local torch/transformers are absent
- **WHEN** semantic embeddings are requested with external settings configured
- **THEN** the pipeline succeeds by using the external embedder and remote Qdrant.
