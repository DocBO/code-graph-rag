## ADDED Requirements

### Requirement: Focused semantic retrieval guidance

The general codebase-query agent SHALL treat Qdrant semantic retrieval as a
discovery mechanism for Python API names/docstrings and Markdown documentation.
It SHALL use Memgraph and source-reading tools for source bodies, non-Python
code, and structural relationships.

#### Scenario: Intent-based Python or documentation question

- **GIVEN** a query asks about a Python capability or documented concept
- **WHEN** the agent chooses a retrieval strategy
- **THEN** it may use semantic retrieval to find candidate APIs or Markdown
  sources before corroborating results

#### Scenario: Non-Python implementation question

- **GIVEN** a query needs implementation details from non-Python code
- **WHEN** the agent chooses a retrieval strategy
- **THEN** it uses graph or source-reading tools rather than treating a
  Qdrant semantic miss as evidence that the code is absent
