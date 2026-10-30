---
name: codeowners-review-gap-audit
description: Audit GitHub CODEOWNERS coverage for critical tracked files and discover unowned workflow, infrastructure, lockfile and policy paths before a pull request. Use for offline review-gate hygiene in GitHub repositories.
license: MIT
compatibility: Python 3.10+ and git CLI (or provide a UTF-8 file list). No network or GitHub authentication needed.
metadata:
  author: AREAZERO Skill Lab
  version: "1.0.0"
---

# Audit CODEOWNERS critical-file review gaps

## Trigger
Use before tightening branch protection or after adding sensitive workflows, infrastructure code, dependency lockfiles or the CODEOWNERS file. GitHub uses the last matching CODEOWNERS pattern and a prescribed file-location precedence.

## Non-trigger
Do not use to prove GitHub branch protection is on, that owners exist, have write access, or that required reviewers actually approve changes. This is not a full gitignore/CodeOwners parser or an authorization test.

## Procedure
1. Work from a local checkout of the **base branch**, where GitHub reads CODEOWNERS for the pull request. Confirm no sensitive file content should be inspected.
2. Run `python scripts/audit.py . --format markdown --fail-on high`; the scanner reads only CODEOWNERS and the list of paths returned by `git ls-files -z --cached`. Never reads tracked source contents or accesses GitHub.
3. Without a Git checkout, prepare a newline-separated UTF-8 path list and pass `--file-list paths.txt`. Reject traversal, abnormal paths and unsupported patterns; no guesses.
4. Review `CO001`–`CO006` in `references/RULES.md`; highlight last-match overrides, CODEOWNERS self-protection and gaps on sensitive tracked paths. Propose explicit patterns and review these in a PR.
5. Separately verify the owners are real GitHub users/teams with write access and branch/ruleset protections are enabled, using authorized GitHub settings/API if appropriate. This **cannot** be inferred from the text file.
6. Record the rules, names-only evidence, input branch, limitations, tests and human sign-off. Re-run against the revised CODEOWNERS.

## Local demo
`python scripts/audit.py examples/safe --file-list examples/safe/paths.txt --format json` exits 0; replace `safe` with `unsafe` to show an explicit empty-owner override and return 2 on high. Run `python -m unittest discover -s tests -v`.

## Safety
An intentionally conservative matcher supports documented basic wildcards, root anchors and directory prefixes, but not the complete Git wildmatch grammar. Errors or unsupported syntax are reported, never silently treated as verified coverage. Tracked paths and owner names can still be sensitive metadata; review before sharing.
