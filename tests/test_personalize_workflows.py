from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from scripts.personalize_workflows import (
    CONFIG_PLACEHOLDER_COUNTS,
    PERSONAL_FIELDS,
    PLACEHOLDER_PATTERN,
    PersonalizationError,
    render_workflows,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_WORKFLOWS = PROJECT_ROOT / "workflows"


class PersonalizeWorkflowsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.data_dir = self.root / "private"
        self.data_dir.mkdir()
        self.output_dir = self.root / "personalized"
        self.values = self._write_valid_inputs()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write_valid_inputs(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for field in PERSONAL_FIELDS:
            if field.numeric_salary:
                value = "150000 USD base salary"
            elif field.filename == "resume.md":
                value = (
                    "# Example Candidate\n\n"
                    'Built `tools` with quotes "and" apostrophes, ${notInterpolation}, '
                    "and literal {{ resume braces }}."
                )
            else:
                value = f"Completed personal content for {field.description}."
            (self.data_dir / field.filename).write_text(value + "\n", encoding="utf-8")
            values[field.token] = value
        return values

    @staticmethod
    def _collect_tokens(value: object, counts: Counter[str]) -> None:
        if isinstance(value, str):
            counts.update(PLACEHOLDER_PATTERN.findall(value))
        elif isinstance(value, list):
            for item in value:
                PersonalizeWorkflowsTests._collect_tokens(item, counts)
        elif isinstance(value, dict):
            for item in value.values():
                PersonalizeWorkflowsTests._collect_tokens(item, counts)

    @staticmethod
    def _walk_strings(value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [
                text
                for item in value
                for text in PersonalizeWorkflowsTests._walk_strings(item)
            ]
        if isinstance(value, dict):
            return [
                text
                for item in value.values()
                for text in PersonalizeWorkflowsTests._walk_strings(item)
            ]
        return []

    def test_generates_private_inactive_workflows_and_preserves_ui_tokens(self) -> None:
        result = render_workflows(
            source_dir=SOURCE_WORKFLOWS,
            data_dir=self.data_dir,
            output_dir=self.output_dir,
            check_only=False,
        )

        self.assertEqual(result.workflow_count, 4)
        self.assertEqual(result.personal_field_count, len(PERSONAL_FIELDS))
        self.assertEqual(result.output_dir, self.output_dir)

        output_files = sorted(self.output_dir.glob("*.json"))
        self.assertEqual(len(output_files), 4)
        counts: Counter[str] = Counter()
        for path in output_files:
            workflow = json.loads(path.read_text(encoding="utf-8"))
            self.assertIs(workflow["active"], False)
            self._collect_tokens(workflow, counts)
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

        self.assertEqual(counts, CONFIG_PLACEHOLDER_COUNTS)

        main_workflow = json.loads(
            (self.output_dir / "Job Searcher.json").read_text(encoding="utf-8")
        )
        envelope = next(
            node
            for node in main_workflow["nodes"]
            if node["name"] == "Build Analysis Envelope"
        )
        expected_literal = json.dumps(
            self.values["[YOUR_RESUME_IN_MARKDOWN]"],
            ensure_ascii=True,
        )
        self.assertIn(
            f"const resume = {expected_literal};",
            envelope["parameters"]["jsCode"],
        )

    def test_every_private_field_is_injected_exactly_where_contract_requires(
        self,
    ) -> None:
        render_workflows(
            source_dir=SOURCE_WORKFLOWS,
            data_dir=self.data_dir,
            output_dir=self.output_dir,
            check_only=False,
        )

        workflows = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in self.output_dir.glob("*.json")
        ]
        output_strings = self._walk_strings(workflows)
        main_workflow = next(
            workflow for workflow in workflows if workflow["name"] == "Job Searcher"
        )
        envelope = next(
            node
            for node in main_workflow["nodes"]
            if node["name"] == "Build Analysis Envelope"
        )

        for field in PERSONAL_FIELDS:
            value = self.values[field.token]
            if field.filename == "resume.md":
                self.assertIn(
                    f"const resume = {json.dumps(value, ensure_ascii=True)};",
                    envelope["parameters"]["jsCode"],
                )
                continue
            occurrences = sum(text.count(value) for text in output_strings)
            self.assertEqual(
                occurrences,
                field.expected_occurrences,
                msg=(
                    f"{field.token} must be injected {field.expected_occurrences} "
                    "time(s) in the generated workflows"
                ),
            )

    def test_check_mode_validates_without_writing(self) -> None:
        result = render_workflows(
            source_dir=SOURCE_WORKFLOWS,
            data_dir=self.data_dir,
            output_dir=self.output_dir,
            check_only=True,
        )

        self.assertEqual(result.workflow_count, 4)
        self.assertIsNone(result.output_dir)
        self.assertFalse(self.output_dir.exists())

    @unittest.skipIf(shutil.which("node") is None, "Node.js is unavailable")
    def test_generated_code_nodes_are_valid_javascript(self) -> None:
        render_workflows(
            source_dir=SOURCE_WORKFLOWS,
            data_dir=self.data_dir,
            output_dir=self.output_dir,
            check_only=False,
        )

        for workflow_path in self.output_dir.glob("*.json"):
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            for index, node in enumerate(workflow["nodes"]):
                code = node.get("parameters", {}).get("jsCode")
                if not isinstance(code, str):
                    continue
                code_path = self.root / f"{workflow_path.stem}-{index}.js"
                code_path.write_text(code, encoding="utf-8")
                completed = subprocess.run(
                    ["node", "--check", str(code_path)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    msg=f"{workflow_path.name}/{node['name']}: {completed.stderr}",
                )

    def test_missing_private_file_fails_closed(self) -> None:
        (self.data_dir / "resume.md").unlink()

        with self.assertRaisesRegex(PersonalizationError, "missing resume file"):
            render_workflows(
                source_dir=SOURCE_WORKFLOWS,
                data_dir=self.data_dir,
                output_dir=self.output_dir,
                check_only=True,
            )

    def test_unfinished_template_marker_is_rejected(self) -> None:
        path = self.data_dir / "domain-priorities.md"
        path.write_text("[[ADD_DOMAIN_PRIORITY]]\n", encoding="utf-8")

        with self.assertRaisesRegex(PersonalizationError, "unfinished"):
            render_workflows(
                source_dir=SOURCE_WORKFLOWS,
                data_dir=self.data_dir,
                output_dir=self.output_dir,
                check_only=True,
            )

    def test_n8n_expression_delimiters_are_rejected_outside_resume(self) -> None:
        path = self.data_dir / "growth-and-learning-preferences.md"
        path.write_text("Evaluate {{ dangerous_expression }}\n", encoding="utf-8")

        with self.assertRaisesRegex(PersonalizationError, "expression delimiters"):
            render_workflows(
                source_dir=SOURCE_WORKFLOWS,
                data_dir=self.data_dir,
                output_dir=self.output_dir,
                check_only=True,
            )

    def test_salary_requires_amount_currency_and_basis(self) -> None:
        path = self.data_dir / "target-annual-salary.md"
        path.write_text("$150,000\n", encoding="utf-8")

        with self.assertRaisesRegex(PersonalizationError, "AMOUNT CURRENCY BASIS"):
            render_workflows(
                source_dir=SOURCE_WORKFLOWS,
                data_dir=self.data_dir,
                output_dir=self.output_dir,
                check_only=True,
            )

    def test_salary_rejects_unknown_currency_code(self) -> None:
        path = self.data_dir / "target-annual-salary.md"
        path.write_text("150000 ZZZ base salary\n", encoding="utf-8")

        with self.assertRaisesRegex(PersonalizationError, "ISO 4217"):
            render_workflows(
                source_dir=SOURCE_WORKFLOWS,
                data_dir=self.data_dir,
                output_dir=self.output_dir,
                check_only=True,
            )

    def test_oversized_private_input_is_rejected(self) -> None:
        path = self.data_dir / "domain-priorities.md"
        path.write_text("x" * (32 * 1024 + 1), encoding="utf-8")

        with self.assertRaisesRegex(PersonalizationError, "byte limit"):
            render_workflows(
                source_dir=SOURCE_WORKFLOWS,
                data_dir=self.data_dir,
                output_dir=self.output_dir,
                check_only=True,
            )

    def test_output_must_not_overlap_public_workflows(self) -> None:
        with self.assertRaisesRegex(PersonalizationError, "must not overlap"):
            render_workflows(
                source_dir=SOURCE_WORKFLOWS,
                data_dir=self.data_dir,
                output_dir=SOURCE_WORKFLOWS / "private-output",
                check_only=True,
            )

    def test_existing_output_directory_is_not_overwritten(self) -> None:
        self.output_dir.mkdir()
        sentinel = self.output_dir / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(PersonalizationError, "already exists"):
            render_workflows(
                source_dir=SOURCE_WORKFLOWS,
                data_dir=self.data_dir,
                output_dir=self.output_dir,
                check_only=False,
            )
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_workflow_placeholder_drift_is_rejected(self) -> None:
        source_dir = self.root / "workflows"
        shutil.copytree(SOURCE_WORKFLOWS, source_dir)
        preference_path = source_dir / "Job Searcher - Preference Analysis.json"
        text = preference_path.read_text(encoding="utf-8")
        preference_path.write_text(
            text.replace(
                "[YOUR_DOMAIN_PREFERENCES_AND_EXCLUSIONS]",
                "[YOUR_UNKNOWN_PERSONAL_FIELD]",
                1,
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(PersonalizationError, "placeholder"):
            render_workflows(
                source_dir=source_dir,
                data_dir=self.data_dir,
                output_dir=self.output_dir,
                check_only=True,
            )

    def test_swapped_valid_tokens_are_rejected_by_field_contract(self) -> None:
        source_dir = self.root / "workflows"
        shutil.copytree(SOURCE_WORKFLOWS, source_dir)
        preference_path = source_dir / "Job Searcher - Preference Analysis.json"
        text = preference_path.read_text(encoding="utf-8")
        first = "[YOUR_DOMAIN_PREFERENCES_AND_EXCLUSIONS]"
        second = "[YOUR_COLLABORATION_AND_TEAM_PREFERENCES]"
        text = text.replace(first, "[TEMP_SWAP]", 1)
        text = text.replace(second, first, 1)
        preference_path.write_text(
            text.replace("[TEMP_SWAP]", second, 1),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            PersonalizationError, "placeholder-bearing field changed"
        ):
            render_workflows(
                source_dir=source_dir,
                data_dir=self.data_dir,
                output_dir=self.output_dir,
                check_only=True,
            )

    def test_credential_bearing_source_is_rejected(self) -> None:
        source_dir = self.root / "workflows"
        shutil.copytree(SOURCE_WORKFLOWS, source_dir)
        main_path = source_dir / "Job Searcher.json"
        workflow = json.loads(main_path.read_text(encoding="utf-8"))
        workflow["nodes"][0]["credentials"] = {"example": {"id": "private"}}
        main_path.write_text(json.dumps(workflow), encoding="utf-8")

        with self.assertRaisesRegex(PersonalizationError, "credential assignments"):
            render_workflows(
                source_dir=source_dir,
                data_dir=self.data_dir,
                output_dir=self.output_dir,
                check_only=True,
            )

    def test_duplicate_workflow_json_key_is_rejected(self) -> None:
        source_dir = self.root / "workflows"
        shutil.copytree(SOURCE_WORKFLOWS, source_dir)
        main_path = source_dir / "Job Searcher.json"
        text = main_path.read_text(encoding="utf-8")
        main_path.write_text(
            text.replace('{\n  "name":', '{\n  "name": "duplicate",\n  "name":', 1),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(PersonalizationError, "duplicate JSON object key"):
            render_workflows(
                source_dir=source_dir,
                data_dir=self.data_dir,
                output_dir=self.output_dir,
                check_only=True,
            )

    def test_dangling_template_marker_is_rejected(self) -> None:
        path = self.data_dir / "domain-priorities.md"
        path.write_text("[[UNFINISHED_MARKER\n", encoding="utf-8")

        with self.assertRaisesRegex(PersonalizationError, "unfinished"):
            render_workflows(
                source_dir=SOURCE_WORKFLOWS,
                data_dir=self.data_dir,
                output_dir=self.output_dir,
                check_only=True,
            )

    @unittest.skipUnless(os.name == "posix", "POSIX file modes are unavailable")
    def test_output_permissions_ignore_permissive_or_restrictive_umask(self) -> None:
        previous_umask = os.umask(0o777)
        try:
            render_workflows(
                source_dir=SOURCE_WORKFLOWS,
                data_dir=self.data_dir,
                output_dir=self.output_dir,
                check_only=False,
            )
        finally:
            os.umask(previous_umask)

        self.assertEqual(self.output_dir.stat().st_mode & 0o777, 0o700)
        for path in self.output_dir.glob("*.json"):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_private_input_symlink_is_rejected(self) -> None:
        real_file = self.root / "real-resume.md"
        real_file.write_text("Private resume", encoding="utf-8")
        resume_path = self.data_dir / "resume.md"
        resume_path.unlink()
        resume_path.symlink_to(real_file)

        with self.assertRaisesRegex(PersonalizationError, "symbolic link"):
            render_workflows(
                source_dir=SOURCE_WORKFLOWS,
                data_dir=self.data_dir,
                output_dir=self.output_dir,
                check_only=True,
            )


if __name__ == "__main__":
    unittest.main()
