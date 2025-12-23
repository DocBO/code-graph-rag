## ADDED Requirements
### Requirement: Slash command parsing
The system SHALL detect supported slash commands in user questions and strip the command tokens before downstream processing.

#### Scenario: Command token stripped
- **WHEN** a user query starts with a recognized slash command
- **THEN** the command token is removed from the query text before embeddings or graph queries are executed

### Requirement: Help command
The system SHALL provide a `/help` command that lists available slash commands and short usage guidance.

#### Scenario: Help output
- **WHEN** a user submits `/help`
- **THEN** the system responds with a list of supported slash commands and their purpose

### Requirement: Semantic seed strategy
The system SHALL provide a `/semantic-seed-strategy` command that performs semantic search, expands graph neighbors, and answers using the expanded context.

#### Scenario: Semantic seed flow
- **WHEN** a user submits a query prefixed with `/semantic-seed-strategy`
- **THEN** the system runs semantic search on the stripped query
- **AND** expands Memgraph neighbors from the semantic hits using a dynamically chosen depth
- **AND** synthesizes the answer from the expanded graph context
