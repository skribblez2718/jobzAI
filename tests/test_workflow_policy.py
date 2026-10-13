from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WorkflowPolicyTests(unittest.TestCase):
    def test_executable_policy_and_exported_workflow_boundaries(self) -> None:
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for workflow policy tests")
        completed = subprocess.run(
            [node or "node", str(PROJECT_ROOT / "tests" / "workflow_policy_checks.js")],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("checks passed", completed.stdout)

    def test_prompt_mirrors_match_embedded_messages(self) -> None:
        stages = (
            ("Preference", "analyze_preference_fit.md", "analyze_preferences.md"),
            ("Skill", "analyze_skills.md", "analyze_skills.md"),
            ("Overall", "analyze_overall_fit.md", "analyze_overall_fit.md"),
        )
        for stage, system_name, user_name in stages:
            workflow = json.loads(
                (
                    PROJECT_ROOT / "workflows" / f"Job Searcher - {stage} Analysis.json"
                ).read_text(encoding="utf-8")
            )
            chain = next(
                node
                for node in workflow["nodes"]
                if node["name"] == f"{stage} Analysis Chain"
            )
            parameters = chain["parameters"]
            expected_system = (
                (PROJECT_ROOT / "prompts" / "system" / system_name)
                .read_text(encoding="utf-8")
                .rstrip()
            )
            expected_user = (
                (PROJECT_ROOT / "prompts" / "user" / user_name)
                .read_text(encoding="utf-8")
                .rstrip()
            )
            with self.subTest(stage=stage):
                self.assertEqual(
                    parameters["messages"]["messageValues"][0]["message"],
                    "=" + expected_system,
                )
                self.assertEqual(parameters["text"], "=" + expected_user)


if __name__ == "__main__":
    unittest.main()
