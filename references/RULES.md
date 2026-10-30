# Findings and evidence

| ID | Severity | Meaning | Review action |
|---|---|---|---|
| CO001 | HIGH | CODEOWNERS is missing at all three valid locations | Add a protected CODEOWNERS file on the base branch. |
| CO002 | HIGH | CODEOWNERS file reaches 3 MiB | Shrink the file; GitHub does not load oversized files. |
| CO003 | MEDIUM | Unsupported syntax, malformed owner, or empty pattern | Fix invalid entry and verify with GitHub. |
| CO004 | HIGH | Critical tracked path has no matching rule | Add a specific owner pattern and verify. |
| CO005 | HIGH | Final matching rule on a critical path has *zero* owners | Remove or replace intentional ownerless override. |
| CO006 | MEDIUM | All rules are ownerless | Add explicitly assigned owners. |

The scanner recognizes root-anchored patterns, filename globs and basic slash-aware `*`/`**`/`?`. It deliberately does not emulate the entire GitHub matcher, apply branch protection, or validate owners. GitHub's CODEOWNERS base branch and API are authoritative.
