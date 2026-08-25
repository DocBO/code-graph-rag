## ADDED Requirements

### Requirement: Focused Qdrant embedding corpus

The system SHALL write Qdrant embeddings only for Python classes, functions,
and methods using their names plus available docstrings, and for Markdown file
content split into bounded chunks. The system SHALL NOT alter Memgraph
ingestion because of this Qdrant selection policy.

#### Scenario: Python symbol with a docstring

- **GIVEN** a Python function, method, or class has a name and docstring
- **WHEN** semantic embeddings are generated
- **THEN** Qdrant receives a document containing the symbol name and docstring,
  but not its implementation body

#### Scenario: Python symbol without a docstring

- **GIVEN** a Python function, method, or class has no docstring
- **WHEN** semantic embeddings are generated
- **THEN** Qdrant receives a document containing its name

#### Scenario: Markdown documentation

- **GIVEN** a Markdown file whose content exceeds the configured chunk size
- **WHEN** semantic embeddings are generated
- **THEN** Qdrant receives bounded chunks with the Markdown file path in each
  payload

#### Scenario: Other source content

- **GIVEN** a non-Python source file or a Python implementation body
- **WHEN** semantic embeddings are generated
- **THEN** that content is not written to Qdrant solely as file/source text

#### Scenario: Graph ingestion

- **GIVEN** any supported repository file
- **WHEN** the repository is ingested
- **THEN** Memgraph nodes, relationships, and source handling continue to use
  the existing ingestion strategy
