## ADDED Requirements

### Requirement: Project Expert distinguishes implementation evidence from references
When answering for a selected project, Project Expert SHALL treat only verified repositories in the same project series as evidence of that project's implementation. Source from a different series MAY be inspected for an explicit comparison or as a clearly labeled reference, but the answer MUST name that source, state that the corresponding selected-series component was unavailable when applicable, and MUST NOT attribute reference behavior to the selected project. Ambiguous project-series matches MUST NOT be assumed.

#### Scenario: Missing protocol stack in the selected series
- **WHEN** the selected LX06 project has OAM source but no registered LX06 protocol-stack repository, and an LX07A stack is available
- **THEN** the answer says the LX06 stack implementation could not be verified
- **AND** any LX07A findings are labeled reference information
- **AND** it does not present LX07A behavior as LX06 implementation

#### Scenario: Same-series component exists
- **WHEN** the catalog includes a verified same-series repository needed to answer the selected project's question
- **THEN** Project Expert may clone it and cite the returned project identity and path
