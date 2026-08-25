## ADDED Requirements

### Requirement: Semantic match source metadata

The system SHALL preserve the source file path stored with a Qdrant embedding
and expose it with quick semantic-retrieval matches. When graph-based location
resolution is unavailable, the stored path SHALL be shown as the result source.

#### Scenario: Markdown chunk result

- **GIVEN** a Qdrant match for a Markdown `File` node contains `file_path`
- **WHEN** quick semantic retrieval returns the match to the control panel
- **THEN** the match header shows that Markdown file path rather than an
  unknown or empty file location

#### Scenario: Symbol with graph location

- **GIVEN** a symbol has both a graph-resolved location and Qdrant `file_path`
- **WHEN** quick semantic retrieval formats the match
- **THEN** it retains the graph-resolved location and source-line metadata
