from __future__ import annotations

import hashlib
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
    DERIVED_PLACEHOLDER_COUNTS,
    JAVASCRIPT_CONFIG_ASSIGNMENTS,
    PERSONAL_FIELDS,
    PLACEHOLDER_PATTERN,
    SOURCE_FIELD_CONTRACTS,
    PersonalizationError,
    _expected_source_placeholders,
    _replace_string,
    load_personal_values,
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
            elif field.integer_bounds is not None:
                value = "4"
            elif field.allowed_values:
                value = "fully_remote"
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
            if field.token in JAVASCRIPT_CONFIG_ASSIGNMENTS:
                assignment = JAVASCRIPT_CONFIG_ASSIGNMENTS[field.token].replace(
                    field.token, value
                )
                self.assertEqual(envelope["parameters"]["jsCode"].count(assignment), 1)
                self.assertEqual(
                    sum(text.count(assignment) for text in output_strings),
                    field.expected_occurrences,
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

    def test_scalar_and_derived_source_counts_match_the_new_contract(self) -> None:
        expected = _expected_source_placeholders()
        self.assertEqual(expected["[TARGET_ANNUAL_SALARY]"], 1)
        self.assertEqual(expected["[TARGET_MAX_ANNUAL_TRIPS]"], 1)
        self.assertEqual(expected["[YOUR_REQUIRED_WORK_ARRANGEMENT]"], 1)
        self.assertEqual(expected["[YOUR_RESUME_SHA256]"], 1)
        self.assertEqual(expected["[YOUR_WORK_ARRANGEMENT_REQUIREMENTS]"], 2)
        self.assertEqual(expected["[YOUR_ELIGIBLE_WORK_LOCATION]"], 2)
        self.assertEqual(
            DERIVED_PLACEHOLDER_COUNTS, Counter({"[YOUR_RESUME_SHA256]": 1})
        )
        self.assertEqual(
            {field.token: field.expected_occurrences for field in PERSONAL_FIELDS},
            {
                "[YOUR_RESUME_IN_MARKDOWN]": 1,
                "[YOUR_DOMAIN_PREFERENCES_AND_EXCLUSIONS]": 1,
                "[YOUR_COLLABORATION_AND_TEAM_PREFERENCES]": 1,
                "[YOUR_GROWTH_AND_LEARNING_PREFERENCES]": 1,
                "[YOUR_IDEAL_ROLE_CHARACTERISTICS]": 1,
                "[YOUR_ADDITIONAL_COMPANY_OR_DOMAIN_SIGNALS]": 1,
                "[YOUR_TEAM_AND_CULTURE_PRIORITIES]": 1,
                "[YOUR_GROWTH_AND_CHALLENGE_PRIORITIES]": 1,
                "[YOUR_DOMAIN_PRIORITIES]": 1,
                "[YOUR_WORK_ARRANGEMENT_REQUIREMENTS]": 2,
                "[YOUR_ELIGIBLE_WORK_LOCATION]": 2,
                "[YOUR_ADDITIONAL_LOCATION_PREFERENCES]": 1,
                "[TARGET_ANNUAL_SALARY]": 1,
                "[TARGET_MAX_ANNUAL_TRIPS]": 1,
                "[YOUR_REQUIRED_WORK_ARRANGEMENT]": 1,
            },
        )

    def test_public_templates_match_required_personal_files(self) -> None:
        template_paths = sorted((PROJECT_ROOT / "data" / "templates").glob("*.md"))
        self.assertEqual(
            {path.name for path in template_paths},
            {field.filename for field in PERSONAL_FIELDS},
        )
        for path in template_paths:
            with self.subTest(filename=path.name):
                template = path.read_text(encoding="utf-8")
                self.assertIn("[[", template)
                self.assertIn("]]", template)

    def test_every_placeholder_bearing_source_field_has_a_pinned_contract(self) -> None:
        def placeholder_paths(
            value: object, parts: tuple[str | int, ...] = ()
        ) -> set[tuple[str | int, ...]]:
            if isinstance(value, str):
                return {parts} if PLACEHOLDER_PATTERN.search(value) else set()
            paths: set[tuple[str | int, ...]] = set()
            if isinstance(value, list):
                for index, item in enumerate(value):
                    paths.update(placeholder_paths(item, (*parts, index)))
            elif isinstance(value, dict):
                for key, item in value.items():
                    paths.update(placeholder_paths(item, (*parts, key)))
            return paths

        actual: set[tuple[str, tuple[str | int, ...]]] = set()
        pinned: set[tuple[str, tuple[str | int, ...]]] = set()
        for path in sorted(SOURCE_WORKFLOWS.glob("*.json")):
            workflow = json.loads(path.read_text(encoding="utf-8"))
            actual.update((path.name, parts) for parts in placeholder_paths(workflow))
            for contract in SOURCE_FIELD_CONTRACTS:
                if contract.workflow_filename != path.name:
                    continue
                indices = [
                    index
                    for index, node in enumerate(workflow["nodes"])
                    if node["name"] == contract.node_name
                ]
                self.assertEqual(len(indices), 1)
                pinned.add((path.name, ("nodes", indices[0], *contract.path)))
        self.assertEqual(actual, pinned)
        self.assertEqual(len(pinned), len(SOURCE_FIELD_CONTRACTS))

    def test_maximum_annual_trips_accepts_digits_and_inclusive_bounds(self) -> None:
        token = "[TARGET_MAX_ANNUAL_TRIPS]"
        assignment = 'const maxAnnualTrips = Number("[TARGET_MAX_ANNUAL_TRIPS]");'
        for value in ("0", "4", "365", "0004"):
            with self.subTest(value=value):
                (self.data_dir / "maximum-annual-trips.md").write_text(
                    f" \n{value}\n\t", encoding="utf-8"
                )
                values = load_personal_values(self.data_dir)
                self.assertEqual(values[token], value)
                self.assertEqual(
                    _replace_string(assignment, values),
                    f'const maxAnnualTrips = Number("{value}");',
                )

    def test_maximum_annual_trips_rejects_out_of_bounds_and_non_digits(self) -> None:
        for value in (
            "-1",
            "366",
            "999999999999",
            "+4",
            "4.0",
            "4e0",
            "0x4",
            "٤",
            "４",
            "4 trips",
            "4\n5",
            "`4`",
            "${4}",
            '4"); throw new Error("unsafe"); //',
            "{{4}}",
            "}}",
            "[[ENTER_TRIPS]]",
        ):
            with self.subTest(value=value):
                (self.data_dir / "maximum-annual-trips.md").write_text(
                    value, encoding="utf-8"
                )
                with self.assertRaises(PersonalizationError):
                    load_personal_values(self.data_dir)
                with self.assertRaises(PersonalizationError):
                    render_workflows(
                        source_dir=SOURCE_WORKFLOWS,
                        data_dir=self.data_dir,
                        output_dir=self.output_dir,
                        check_only=False,
                    )
                self.assertFalse(self.output_dir.exists())

    def test_required_work_arrangement_accepts_only_configured_enum_values(
        self,
    ) -> None:
        token = "[YOUR_REQUIRED_WORK_ARRANGEMENT]"
        assignment = (
            'const requiredWorkArrangement = "[YOUR_REQUIRED_WORK_ARRANGEMENT]";'
        )
        for value in ("fully_remote", "hybrid", "on_site", "any"):
            with self.subTest(value=value):
                (self.data_dir / "required-work-arrangement.md").write_text(
                    f" \n{value}\n\t", encoding="utf-8"
                )
                values = load_personal_values(self.data_dir)
                self.assertEqual(values[token], value)
                self.assertEqual(
                    _replace_string(assignment, values),
                    f'const requiredWorkArrangement = "{value}";',
                )

    def test_required_work_arrangement_rejects_other_values_and_delimiters(
        self,
    ) -> None:
        for value in (
            "remote",
            "Fully_remote",
            "FULLY_REMOTE",
            "fully remote",
            "on-site",
            "fully_remote\nany",
            '"fully_remote"',
            "`fully_remote`",
            "${fully_remote}",
            'fully_remote"; throw new Error("unsafe"); //',
            "{{fully_remote}}",
            "}}",
            "[[ENTER_ARRANGEMENT]]",
        ):
            with self.subTest(value=value):
                (self.data_dir / "required-work-arrangement.md").write_text(
                    value, encoding="utf-8"
                )
                with self.assertRaises(PersonalizationError):
                    load_personal_values(self.data_dir)
                with self.assertRaises(PersonalizationError):
                    render_workflows(
                        source_dir=SOURCE_WORKFLOWS,
                        data_dir=self.data_dir,
                        output_dir=self.output_dir,
                        check_only=False,
                    )
                self.assertFalse(self.output_dir.exists())

    def test_new_config_inputs_are_required(self) -> None:
        for filename, description in (
            ("maximum-annual-trips.md", "maximum annual trips"),
            ("required-work-arrangement.md", "required work arrangement"),
        ):
            with self.subTest(filename=filename):
                path = self.data_dir / filename
                original = path.read_text(encoding="utf-8")
                path.unlink()
                try:
                    with self.assertRaisesRegex(
                        PersonalizationError, f"missing {description} file"
                    ):
                        load_personal_values(self.data_dir)
                finally:
                    path.write_text(original, encoding="utf-8")

    def test_new_config_inputs_cannot_be_empty_or_oversized(self) -> None:
        for filename in ("maximum-annual-trips.md", "required-work-arrangement.md"):
            path = self.data_dir / filename
            original = path.read_text(encoding="utf-8")
            try:
                for value, message in ((" \n\t", "empty"), ("9" * 129, "byte limit")):
                    with self.subTest(filename=filename, message=message):
                        path.write_text(value, encoding="utf-8")
                        with self.assertRaisesRegex(PersonalizationError, message):
                            load_personal_values(self.data_dir)
            finally:
                path.write_text(original, encoding="utf-8")

    def test_scalar_config_placeholders_require_exact_safe_assignments(self) -> None:
        values = load_personal_values(self.data_dir)
        for token, assignment in JAVASCRIPT_CONFIG_ASSIGNMENTS.items():
            with self.subTest(token=token, context="safe"):
                self.assertEqual(
                    _replace_string(assignment, values),
                    assignment.replace(token, values[token]),
                )
            for unsafe_context in (
                token,
                f'const other = "{token}";',
                assignment.replace('"', "`"),
                assignment + f'\nconst other = "{token}";',
            ):
                with self.subTest(token=token, context=unsafe_context):
                    with self.assertRaisesRegex(
                        PersonalizationError, "configuration assignment context"
                    ):
                        _replace_string(unsafe_context, values)

    def test_resume_sha256_is_derived_from_trimmed_validated_utf8(self) -> None:
        for resume in (
            "# Example Candidate\nBuilt tools.",
            '# Example Candidate\nRésumé: café, 日本語, 🛠️; "quotes", `ticks`, '
            "${notInterpolation}, {{ literal braces }}.\u2028\u2029",
        ):
            with self.subTest(resume=resume):
                (self.data_dir / "resume.md").write_text(
                    f" \n\t{resume}\n ", encoding="utf-8"
                )
                values = load_personal_values(self.data_dir)
                expected_digest = hashlib.sha256(
                    resume.strip().encode("utf-8")
                ).hexdigest()
                rendered = _replace_string(
                    "const resume = `[YOUR_RESUME_IN_MARKDOWN]`;\n"
                    'const resumeSha256 = "[YOUR_RESUME_SHA256]";',
                    values,
                )
                self.assertEqual(
                    rendered,
                    f"const resume = {json.dumps(resume.strip(), ensure_ascii=True)};\n"
                    f'const resumeSha256 = "{expected_digest}";',
                )
                self.assertRegex(expected_digest, r"^[a-f0-9]{64}$")
                self.assertNotIn("[YOUR_RESUME_SHA256]", values)
                self.assertEqual(len(values), len(PERSONAL_FIELDS))
                counts: Counter[str] = Counter()
                self._collect_tokens(rendered, counts)
                self.assertFalse(counts)

    def test_resume_sha256_does_not_hash_the_escaped_javascript_literal(self) -> None:
        values = load_personal_values(self.data_dir)
        resume = values["[YOUR_RESUME_IN_MARKDOWN]"]
        raw_digest = hashlib.sha256(resume.encode("utf-8")).hexdigest()
        escaped_digest = hashlib.sha256(
            json.dumps(resume, ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        self.assertNotEqual(raw_digest, escaped_digest)
        self.assertEqual(_replace_string("[YOUR_RESUME_SHA256]", values), raw_digest)

    def test_derived_resume_hash_cannot_be_supplied_as_personal_content(self) -> None:
        (self.data_dir / "resume.md").write_text(
            "Candidate content [YOUR_RESUME_SHA256]", encoding="utf-8"
        )
        with self.assertRaisesRegex(PersonalizationError, "placeholder tokens"):
            load_personal_values(self.data_dir)

    def test_invalid_resume_is_rejected_before_deriving_its_hash(self) -> None:
        for content, message in (
            (b"Candidate content\x00", "NUL character"),
            (b"Candidate content\xff", "not valid UTF-8"),
        ):
            with self.subTest(message=message):
                (self.data_dir / "resume.md").write_bytes(content)
                with self.assertRaisesRegex(PersonalizationError, message):
                    load_personal_values(self.data_dir)

    @unittest.skipIf(shutil.which("node") is None, "Node.js is unavailable")
    def test_personalized_config_and_resume_literals_are_valid_javascript(self) -> None:
        (self.data_dir / "resume.md").write_text(
            '# Example Candidate\nRésumé 日本語 🛠️; "quotes", `ticks`, '
            "${notInterpolation}, {{ literal braces }}.\u2028\u2029",
            encoding="utf-8",
        )
        values = load_personal_values(self.data_dir)
        source = "\n".join(JAVASCRIPT_CONFIG_ASSIGNMENTS.values()) + (
            "\nconst resume = `[YOUR_RESUME_IN_MARKDOWN]`;\n"
            'const resumeSha256 = "[YOUR_RESUME_SHA256]";'
        )
        code_path = self.root / "personalized-literals.js"
        code_path.write_text(_replace_string(source, values), encoding="utf-8")
        completed = subprocess.run(
            ["node", "--check", str(code_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)

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
