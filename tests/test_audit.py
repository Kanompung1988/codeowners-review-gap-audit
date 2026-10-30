import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit import analyze, codeowners_path, critical, parse_rules, tracked_files, translate_glob, valid_path


class RulesTest(unittest.TestCase):
    def test_critical_workflow(self): self.assertTrue(critical(".github/workflows/build.yml"))
    def test_critical_lock(self): self.assertTrue(critical("pnpm-lock.yaml"))
    def test_noncritical(self): self.assertFalse(critical("docs/README.md"))
    def test_valid_path(self): self.assertTrue(valid_path("src/app.py"))
    def test_invalid_parent(self): self.assertFalse(valid_path("../secret"))
    def test_invalid_absolute(self): self.assertFalse(valid_path("/etc/passwd"))
    def test_invalid_backslash(self): self.assertFalse(valid_path("a\\b"))
    def test_last_owner_wins(self):
        r, _ = parse_rules("* @all\n/.github/workflows/ @dev\n/.github/workflows/\n")
        self.assertEqual([x for x in r if x["regex"].fullmatch(".github/workflows/ci.yml")][-1]["owners"], [])
    def test_root_anchored(self):
        rx = translate_glob("/docs/")
        self.assertTrue(rx.fullmatch("docs/a.md"))
        self.assertFalse(rx.fullmatch("src/docs/a.md"))
    def test_unanchored_directory(self):
        rx = translate_glob("apps/")
        self.assertTrue(rx.fullmatch("src/apps/a.ts"))
        self.assertTrue(rx.fullmatch("apps/a.ts"))
    def test_unanchored_suffix(self):
        self.assertTrue(translate_glob("*.py").fullmatch("lib/main.py"))
    def test_anchored_pattern(self):
        self.assertFalse(translate_glob("docs/*").fullmatch("docs/api/deep.txt"))
    def test_globstar(self):
        self.assertTrue(translate_glob("**/logs/").fullmatch("lib/logs/err.txt"))
    def test_case_sensitive(self):
        self.assertFalse(translate_glob("Dockerfile").fullmatch("dockerfile"))
    def test_negation_rejected(self):
        r, e = parse_rules("!secrets @u\n")
        self.assertEqual(len(r), 0); self.assertEqual(e[0]["rule"], "CO003")
    def test_brackets_rejected(self):
        r, e = parse_rules("*.py[ab] @u")
        self.assertEqual(len(r), 0); self.assertEqual(len(e), 1)
    def test_comment_ignored(self):
        r, e = parse_rules("# foo\n    #ignored\n*.py @dev # note")
        self.assertEqual(len(r), 1); self.assertEqual(len(e), 0)
    def test_email_owner(self):
        r, e = parse_rules("*.go dev@example.com")
        self.assertEqual(r[0]["owners"], ["dev@example.com"]); self.assertFalse(e)
    def test_team_owner(self):
        r, e = parse_rules("*.go @org/team")
        self.assertEqual(r[0]["owners"], ["@org/team"]); self.assertFalse(e)
    def test_invalid_owner(self):
        r, e = parse_rules("* 123")
        self.assertFalse(r); self.assertTrue(e)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(); self.root = Path(self.d.name)
    def tearDown(self): self.d.cleanup()
    def put(self, path, text):
        p = self.root / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
    def test_no_codeowners(self):
        self.assertEqual(analyze(self.root, ["Dockerfile"])["findings"][0]["rule"], "CO001")
    def test_precedence(self):
        self.put("CODEOWNERS", "* @root"); self.put("docs/CODEOWNERS", "* @docs"); self.put(".github/CODEOWNERS", "* @gh")
        self.assertEqual(codeowners_path(self.root).relative_to(self.root).as_posix(), ".github/CODEOWNERS")
    def test_full_coverage(self):
        self.put(".github/CODEOWNERS", "* @all")
        self.assertEqual(analyze(self.root, [".github/CODEOWNERS", "Dockerfile"])["findings"], [])
    def test_uncovered(self):
        self.put(".github/CODEOWNERS", "*.md @docs")
        self.assertEqual(analyze(self.root, [".github/workflows/ci.yml"])["findings"][0]["rule"], "CO004")
    def test_empty_rule_override(self):
        self.put(".github/CODEOWNERS", "* @all\n/.github/")
        self.assertEqual(analyze(self.root, [".github/CODEOWNERS"])["findings"][0]["rule"], "CO005")
    def test_oversized(self):
        self.put("CODEOWNERS", "x" * (3*1024*1024))
        self.assertEqual(analyze(self.root, ["Dockerfile"])["findings"][0]["rule"], "CO002")
    def test_file_list_rejects_traversal(self):
        self.put("names.txt", "../password\n")
        with self.assertRaises(ValueError): tracked_files(self.root, self.root / "names.txt")
    def test_file_list_deduplicates(self):
        self.put("names.txt", "Dockerfile\nDockerfile\n")
        self.assertEqual(tracked_files(self.root, self.root / "names.txt"), ["Dockerfile"])
    def test_git_tracked_files(self):
        if subprocess.run(["git", "--version"], capture_output=True).returncode: self.skipTest("git absent")
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True)
        self.put("Dockerfile", "FROM scratch")
        subprocess.run(["git", "-C", str(self.root), "add", "Dockerfile"], check=True)
        self.assertEqual(tracked_files(self.root), ["Dockerfile"])
    def test_cli_exit(self):
        self.put(".github/CODEOWNERS", "* @all\n/.github/")
        self.put("file-list.txt", ".github/CODEOWNERS\n")
        script = Path(__file__).resolve().parents[1]/"scripts/audit.py"
        args = [sys.executable, str(script), str(self.root), "--file-list", str(self.root/"file-list.txt"), "--format", "json"]
        p = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(p.returncode, 2); self.assertEqual(json.loads(p.stdout)["findings"][0]["rule"], "CO005")
        self.assertEqual(subprocess.run(args+["--fail-on", "none"], capture_output=True).returncode, 0)

if __name__ == "__main__": unittest.main()
