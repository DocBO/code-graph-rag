1. [ ] Define external embedding/Qdrant config: env vars for embed API endpoint/key/model and Qdrant host/port/API key.
2. [ ] Implement an embedding client that calls the external API and writes vectors to remote Qdrant (no torch/transformers).
3. [ ] Update README/.env examples for external embedding + remote Qdrant; add tests covering client selection and a mocked embedding call.
