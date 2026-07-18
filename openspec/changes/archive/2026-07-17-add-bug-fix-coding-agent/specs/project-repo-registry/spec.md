## ADDED Requirements

### Requirement: Project repo admin responses expose a member summary

The existing `/admin/project-repos` list and read responses SHALL include a `member_count` field reporting how many registered users are members of each project repository. This field SHALL be derived from the `project_repo_member` table and SHALL never expose member credentials. The existing fields (including `git_token_set`) and token-masking behavior SHALL remain unchanged.

#### Scenario: List response includes member count

- **WHEN** an authenticated admin calls `GET /admin/project-repos`
- **THEN** each entry includes a `member_count` equal to the number of `project_repo_member` rows for that repo
- **AND** no plaintext git token appears in the response

#### Scenario: Read response includes member count

- **WHEN** an admin calls `GET /admin/project-repos/{id}`
- **THEN** the response includes `member_count` for that repository
