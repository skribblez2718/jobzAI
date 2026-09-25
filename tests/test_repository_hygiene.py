from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

from scripts.personalize_workflows import PERSONAL_FIELDS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"

SENSITIVE_PATH_PATTERN = re.compile(
    r"(?i)(?:^|/)(?:data/private|personalized-workflows[^/]*)(?:/|$)"
    r"|(?:^|/)(?:\.env(?:\.|$)|id_rsa(?:\.pub)?$|.*\.(?:pem|p12|pfx|key)$)"
)
UUID_PATTERN = re.compile(rb"(?i)\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b")
SHA_PATTERN = re.compile(rb"(?i)\b[0-9a-f]{40,64}\b")
SENSITIVE_TEXT_PATTERNS = {
    "private key": re.compile(rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    "AWS access key": re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(
        rb"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"
    ),
    "GitLab token": re.compile(rb"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    "OpenAI API key": re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "Google API key": re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b"),
    "Slack token": re.compile(rb"\bxox[abprs]-[A-Za-z0-9-]{20,}\b"),
    "Stripe live key": re.compile(rb"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b"),
    "JSON web token": re.compile(
        rb"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
    ),
    "email address": re.compile(
        rb"(?i)(?<![A-Z0-9._%+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"
        rb"(?![A-Z0-9._%+-])"
    ),
    "formatted phone number": re.compile(
        rb"(?<![A-Z0-9])(?:\+\d[ .()-]*)?(?:\(?\d{2,4}\)?[ .-])"
        rb"\d{2,4}[ .-]\d{3,4}(?![A-Z0-9])"
    ),
    "US social security number": re.compile(rb"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
}
REQUIRED_IGNORED_PATHS = (
    "data/private/resume.md",
    "personalized-workflows-ci/",
    ".env",
    ".env.local",
    "keys/production.pem",
    "keys/production.key",
)


class RepositoryHygieneTests(unittest.TestCase):
    @staticmethod
    def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
        )

    def _publish_candidate_paths(self) -> list[Path]:
        completed = self._git(
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        return [
            Path(path.decode("utf-8", errors="surrogateescape"))
            for path in completed.stdout.split(b"\0")
            if path
        ]

    def test_sensitive_local_paths_are_ignored(self) -> None:
        for path in REQUIRED_IGNORED_PATHS:
            with self.subTest(path=path):
                completed = self._git("check-ignore", "-q", path)
                self.assertEqual(
                    completed.returncode,
                    0,
                    f"sensitive local path is not ignored: {path}",
                )

    def test_public_templates_keep_private_fields_as_markers(self) -> None:
        template_directory = PROJECT_ROOT / "data" / "templates"
        for field in PERSONAL_FIELDS:
            path = template_directory / field.filename
            with self.subTest(template=path.name):
                content = path.read_text(encoding="utf-8")
                self.assertRegex(
                    content,
                    r"\[\[[^]\n]+\]\]",
                    "public template must retain at least one [[...]] marker",
                )

    def test_publish_candidates_have_no_sensitive_paths_or_high_confidence_matches(
        self,
    ) -> None:
        candidate_paths = self._publish_candidate_paths()
        forbidden_paths = [
            path.as_posix()
            for path in candidate_paths
            if SENSITIVE_PATH_PATTERN.search(path.as_posix())
        ]
        self.assertEqual(forbidden_paths, [], "sensitive path staged for publication")

        matches: dict[str, list[str]] = {label: [] for label in SENSITIVE_TEXT_PATTERNS}
        for path in candidate_paths:
            absolute_path = PROJECT_ROOT / path
            if not absolute_path.is_file():
                continue
            content = absolute_path.read_bytes()
            if b"\0" in content:
                continue
            normalized = SHA_PATTERN.sub(
                b"<digest>", UUID_PATTERN.sub(b"<uuid>", content)
            )
            for label, pattern in SENSITIVE_TEXT_PATTERNS.items():
                if pattern.search(normalized):
                    matches[label].append(path.as_posix())

        detected = {label: paths for label, paths in matches.items() if paths}
        self.assertEqual(
            detected, {}, "sensitive content detected in publish candidates"
        )

    def test_ci_workflow_has_read_only_pinned_dependencies_and_no_secrets(self) -> None:
        workflow = CI_WORKFLOW.read_text(encoding="utf-8")
        uses = re.findall(r"^\s*uses:\s+[^@\s]+@([^\s#]+)", workflow, re.MULTILINE)

        self.assertIn("pull_request:", workflow)
        self.assertIn("push:", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertNotIn("${{ secrets.", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn(
            "BASE_REF: ${{ github.event.forced && github.event.after || '' }}",
            workflow,
        )
        self.assertIn('GITLEAKS_ENABLE_COMMENTS: "false"', workflow)
        self.assertIn('GITLEAKS_ENABLE_UPLOAD_ARTIFACT: "false"', workflow)
        self.assertTrue(uses, "CI workflow must use pinned actions")
        self.assertTrue(
            all(re.fullmatch(r"[0-9a-f]{40}", revision) for revision in uses),
            "every action dependency must be pinned to a full commit SHA",
        )


if __name__ == "__main__":
    unittest.main()
