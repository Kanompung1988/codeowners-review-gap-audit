#!/usr/bin/env python3
"""Offline, names-only CODEOWNERS review gap audit. Never opens source file bodies."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

MAX_CODEOWNERS = 3 * 1024 * 1024
MAX_FILELIST = 10 * 1024 * 1024
SEVERITY = {"low": 1, "medium": 2, "high": 3}
CRITICAL = (
    ".github/CODEOWNERS", ".github/workflows/", "infra/", "terraform/",
    "migrations/", "db/migrations/", "Dockerfile", "pyproject.toml",
    "package-lock.json", "pnpm-lock.yaml", ".github/dependabot.yml",
)


def critical(path: str) -> bool:
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in CRITICAL)


def valid_path(raw: str) -> bool:
    p = PurePosixPath(raw)
    return bool(raw) and not raw.startswith("/") and not any(x in ("..", ".") for x in raw.split("/")) and "\\" not in raw and str(p) == raw


def codeowners_path(root: Path) -> Path | None:
    for rel in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
        candidate = root / rel
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None


def translate_glob(pattern: str) -> re.Pattern[str]:
    """Documented gitignore-like subset. Unknown syntax rejected by parser."""
    leading = pattern.startswith("/")
    body = pattern.lstrip("/")
    directory = body.endswith("/")
    if directory:
        body = body[:-1]
    anchored = leading or "/" in body
    i = 0
    pieces: list[str] = []
    while i < len(body):
        if body.startswith("**/", i):
            pieces.append("(?:.*/)?")
            i += 3
        elif body.startswith("**", i):
            pieces.append(".*")
            i += 2
        elif body[i] == "*":
            pieces.append("[^/]*")
            i += 1
        elif body[i] == "?":
            pieces.append("[^/]")
            i += 1
        else:
            pieces.append(re.escape(body[i]))
            i += 1
    prefix = "^" if anchored else "^(?:.*/)?"
    suffix = r"(?:/.*)$" if directory else "$"
    return re.compile(prefix + "".join(pieces) + suffix)


def parse_rules(content: str) -> tuple[list[dict], list[dict]]:
    rules: list[dict] = []
    errors: list[dict] = []
    for n, raw in enumerate(content.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("#", 1)[0].split()
        if not parts:
            continue
        pat, owners = parts[0], parts[1:]
        if pat.startswith("!") or pat.startswith("\\#") or any(ch in pat for ch in "[]") or "\\" in pat:
            errors.append({"rule": "CO003", "severity": "medium", "location": f"CODEOWNERS:{n}", "message": "Unsupported CODEOWNERS pattern (negation, bracket range or backslash)."})
            continue
        if not pat.strip("/"):
            errors.append({"rule": "CO003", "severity": "medium", "location": f"CODEOWNERS:{n}", "message": "Empty CODEOWNERS pattern."})
            continue
        if any(not (re.fullmatch(r"@[\w-]+(?:/[\w.-]+)?", owner) or re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", owner)) for owner in owners):
            errors.append({"rule": "CO003", "severity": "medium", "location": f"CODEOWNERS:{n}", "message": "Unsupported owner syntax; this line was skipped."})
            continue
        rules.append({"pattern": pat, "owners": owners, "line": n, "regex": translate_glob(pat)})
    return rules, errors


def tracked_files(root: Path, file_list: Path | None = None) -> list[str]:
    if file_list is not None:
        if file_list.stat().st_size > MAX_FILELIST:
            raise ValueError("File list exceeds 10 MiB")
        paths = file_list.read_text(encoding="utf-8").splitlines()
    else:
        result = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached"], capture_output=True, check=False, timeout=15)
        if result.returncode:
            raise ValueError("git ls-files failed; use --file-list with paths relative to root")
        if len(result.stdout) > MAX_FILELIST:
            raise ValueError("Tracked path list exceeds 10 MiB")
        paths = [p.decode("utf-8", "replace") for p in result.stdout.split(b"\0") if p]
    if len(paths) > 50000:
        raise ValueError("Refusing more than 50,000 paths")
    invalid = [p for p in paths if not valid_path(p)]
    if invalid:
        raise ValueError("Unsafe/noncanonical path in file list; first invalid line omitted")
    return sorted(set(paths))


def analyze(root: Path, paths: list[str]) -> dict:
    found: list[dict] = []
    owners_path = codeowners_path(root)
    if owners_path is None:
        return {"source": None, "checked_files": len(paths), "findings": [{"rule": "CO001", "severity": "high", "location": "CODEOWNERS", "message": "No CODEOWNERS at .github/, root or docs/."}]}
    if owners_path.stat().st_size >= MAX_CODEOWNERS:
        return {"source": owners_path.relative_to(root).as_posix(), "checked_files": len(paths), "findings": [{"rule": "CO002", "severity": "high", "location": "CODEOWNERS", "message": "CODEOWNERS is >= 3 MiB; GitHub will not load it."}]}
    rules, errors = parse_rules(owners_path.read_text(encoding="utf-8"))
    found.extend(errors)
    for path in paths:
        if not critical(path):
            continue
        matched = next((r for r in reversed(rules) if r["regex"].fullmatch(path)), None)
        if matched is None:
            found.append({"rule": "CO004", "severity": "high", "location": path, "message": "Critical tracked file has no matching CODEOWNERS rule."})
        elif not matched["owners"]:
            found.append({"rule": "CO005", "severity": "high", "location": path, "message": f"Last matching CODEOWNERS rule on line {matched['line']} deliberately leaves this critical file unowned."})
    if rules and all(not r["owners"] for r in rules):
        found.append({"rule": "CO006", "severity": "medium", "location": "CODEOWNERS", "message": "No rules assign any reviewers."})
    return {"source": owners_path.relative_to(root).as_posix(), "checked_files": len(paths), "findings": sorted(found, key=lambda x: (x["location"], x["rule"]))}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Offline CODEOWNERS critical-file coverage audit")
    p.add_argument("root", type=Path, help="Local repository root")
    p.add_argument("--file-list", type=Path, help="Text file of tracked repo-relative paths; bypass git")
    p.add_argument("--format", choices=("json", "markdown"), default="markdown")
    p.add_argument("--fail-on", choices=("none", "medium", "high"), default="high")
    args = p.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("root is not a directory")
        report = analyze(root, tracked_files(root, args.file_list))
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": "Input invalid or unreadable; verify root, git availability and UTF-8."}), file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(f"# CODEOWNERS review gap audit\n\nTracked files checked: {report['checked_files']}\n\nFindings: {len(report['findings'])}\n")
        for x in report["findings"]:
            print(f"- **{x['severity'].upper()} {x['rule']}** `{x['location']}` — {x['message']}")
    threshold = SEVERITY.get(args.fail_on, 99)
    return 2 if any(SEVERITY[x["severity"]] >= threshold for x in report["findings"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
