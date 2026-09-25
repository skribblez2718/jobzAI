#!/usr/bin/env python3
"""Generate private workflow copies from bounded personal Markdown inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import stat
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "private"
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "workflows"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "personalized-workflows"

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)

PLACEHOLDER_PATTERN = re.compile(r"\[(?:YOUR|TARGET|RSS_FEED_URL)[A-Z0-9_]*\]")
SALARY_PATTERN = re.compile(
    r"(?P<amount>[1-9][0-9]{3,8}) (?P<currency>[A-Z]{3}) "
    r"(?P<basis>base salary|total compensation)"
)
MIN_TARGET_SALARY = 1_000
MAX_TARGET_SALARY = 999_999_999
# ISO 4217 List One (current currencies and funds), maintained by SIX and
# refreshed for this project on 2026-09-21:
# https://www.six-group.com/dam/download/financial-information/data-center/iso-currrency/lists/list-one.xml
ISO_4217_CODES = frozenset(
    """
    AED AFN ALL AMD AOA ARS AUD AWG AZN BAM BBD BDT BHD BIF BMD BND BOB BOV
    BRL BSD BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUP
    CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF
    GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR
    KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT
    MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN
    PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE
    SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX
    USD USN UYI UYU UYW UZS VED VES VND VUV WST XAD XAF XAG XAU XBA XBB XBC
    XBD XCD XCG XDR XOF XPD XPF XPT XSU XTS XUA XXX YER ZAR ZMW ZWG
    """.split()
)
MAX_WORKFLOW_FILES = 32
MAX_WORKFLOW_BYTES = 8 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_COLLECTION_ITEMS = 100_000


class PersonalizationError(Exception):
    """Raised when private inputs or workflow templates violate the contract."""


@dataclass(frozen=True)
class PersonalField:
    token: str
    filename: str
    description: str
    max_bytes: int
    expected_occurrences: int = 1
    allow_n8n_delimiters: bool = False
    numeric_salary: bool = False


PERSONAL_FIELDS: tuple[PersonalField, ...] = (
    PersonalField(
        token="[YOUR_RESUME_IN_MARKDOWN]",
        filename="resume.md",
        description="resume",
        max_bytes=256 * 1024,
        allow_n8n_delimiters=True,
    ),
    PersonalField(
        token="[YOUR_DOMAIN_PREFERENCES_AND_EXCLUSIONS]",
        filename="domain-preferences-and-exclusions.md",
        description="domain preferences and exclusions",
        max_bytes=32 * 1024,
    ),
    PersonalField(
        token="[YOUR_COLLABORATION_AND_TEAM_PREFERENCES]",
        filename="collaboration-and-team-preferences.md",
        description="collaboration and team preferences",
        max_bytes=32 * 1024,
    ),
    PersonalField(
        token="[YOUR_GROWTH_AND_LEARNING_PREFERENCES]",
        filename="growth-and-learning-preferences.md",
        description="growth and learning preferences",
        max_bytes=32 * 1024,
    ),
    PersonalField(
        token="[YOUR_IDEAL_ROLE_CHARACTERISTICS]",
        filename="ideal-role-characteristics.md",
        description="ideal role characteristics",
        max_bytes=32 * 1024,
    ),
    PersonalField(
        token="[YOUR_ADDITIONAL_COMPANY_OR_DOMAIN_SIGNALS]",
        filename="additional-company-or-domain-signals.md",
        description="additional company or domain signals",
        max_bytes=32 * 1024,
    ),
    PersonalField(
        token="[YOUR_TEAM_AND_CULTURE_PRIORITIES]",
        filename="team-and-culture-priorities.md",
        description="team and culture priorities",
        max_bytes=32 * 1024,
    ),
    PersonalField(
        token="[YOUR_GROWTH_AND_CHALLENGE_PRIORITIES]",
        filename="growth-and-challenge-priorities.md",
        description="growth and challenge priorities",
        max_bytes=32 * 1024,
    ),
    PersonalField(
        token="[YOUR_DOMAIN_PRIORITIES]",
        filename="domain-priorities.md",
        description="domain priorities",
        max_bytes=32 * 1024,
    ),
    PersonalField(
        token="[YOUR_WORK_ARRANGEMENT_REQUIREMENTS]",
        filename="work-arrangement-requirements.md",
        description="work arrangement and mandatory location conditions",
        max_bytes=8 * 1024,
        expected_occurrences=2,
    ),
    PersonalField(
        token="[YOUR_ELIGIBLE_WORK_LOCATION]",
        filename="eligible-work-location.md",
        description="eligible work location",
        max_bytes=8 * 1024,
        expected_occurrences=2,
    ),
    PersonalField(
        token="[YOUR_ADDITIONAL_LOCATION_PREFERENCES]",
        filename="additional-location-preferences.md",
        description="additional non-gating location preferences",
        max_bytes=32 * 1024,
    ),
    PersonalField(
        token="[TARGET_ANNUAL_SALARY]",
        filename="target-annual-salary.md",
        description="target annual salary",
        max_bytes=128,
        expected_occurrences=2,
        numeric_salary=True,
    ),
)

CONFIG_PLACEHOLDER_COUNTS: Counter[str] = Counter(
    {
        "[RSS_FEED_URL_1]": 1,
        "[RSS_FEED_URL_2]": 1,
        "[RSS_FEED_URL_3]": 1,
        "[RSS_FEED_URL_4]": 1,
        "[RSS_FEED_URL_5]": 1,
        "[YOUR_FROM_EMAIL]": 2,
        "[YOUR_TO_EMAIL]": 2,
    }
)


@dataclass(frozen=True)
class SourceFieldContract:
    workflow_filename: str
    node_name: str
    path: tuple[str | int, ...]
    sha256: str


# Pin every placeholder-bearing source field so token movement or an unsafe context
# change fails closed until the generator contract is deliberately reviewed.
SOURCE_FIELD_CONTRACTS: tuple[SourceFieldContract, ...] = (
    SourceFieldContract(
        "Job Searcher.json",
        "Send Jobs Email",
        ("parameters", "fromEmail"),
        "cde5c4b0b33b752806d82ce1c93286f87c13c7bac82b4e3ebdd7b2632a6ff0d9",
    ),
    SourceFieldContract(
        "Job Searcher.json",
        "Send Jobs Email",
        ("parameters", "toEmail"),
        "62328b57796a3bfca85abf2127c9c2c90730a6753c5c88d444f24af2bf59f065",
    ),
    SourceFieldContract(
        "Job Searcher.json",
        "Send No New Jobs Email",
        ("parameters", "fromEmail"),
        "cde5c4b0b33b752806d82ce1c93286f87c13c7bac82b4e3ebdd7b2632a6ff0d9",
    ),
    SourceFieldContract(
        "Job Searcher.json",
        "Send No New Jobs Email",
        ("parameters", "toEmail"),
        "62328b57796a3bfca85abf2127c9c2c90730a6753c5c88d444f24af2bf59f065",
    ),
    SourceFieldContract(
        "Job Searcher.json",
        "RSS Feed 1",
        ("parameters", "url"),
        "8978cb5c0ee8da315c6c84eef1caa2bd7666bf7c30baa19e523eaff40cb91fc8",
    ),
    SourceFieldContract(
        "Job Searcher.json",
        "RSS Feed 2",
        ("parameters", "url"),
        "7fbca22964cdf394db6079871223dce428657dde03bc9e28822765101335230c",
    ),
    SourceFieldContract(
        "Job Searcher.json",
        "RSS Feed 3",
        ("parameters", "url"),
        "b42f7a3d6e3c523e1f804060543e05fa6fb8742ce69e0570f6c8451565761e3c",
    ),
    SourceFieldContract(
        "Job Searcher.json",
        "RSS Feed 4",
        ("parameters", "url"),
        "732d6d6e89608f1e472e0075739109f4c3dc061f762cf9e278614775f1ad11b9",
    ),
    SourceFieldContract(
        "Job Searcher.json",
        "RSS Feed 5",
        ("parameters", "url"),
        "9bbc6d944a72afbf247a30957c80a00db935dfa30290d9751755045278f8a67c",
    ),
    SourceFieldContract(
        "Job Searcher.json",
        "Build Analysis Envelope",
        ("parameters", "jsCode"),
        "0e1359814b1f7b74881a5ad5f22e9ae7ff6b25acd14ce529d1576ce9d81bad22",
    ),
    SourceFieldContract(
        "Job Searcher - Preference Analysis.json",
        "Preference Analysis Chain",
        ("parameters", "messages", "messageValues", 0, "message"),
        "39f98f88e65f92ed996ae44e97ab1e35707aa28c14e9acbaa7b2f10e5d3a4f6d",
    ),
    SourceFieldContract(
        "Job Searcher - Overall Analysis.json",
        "Overall Analysis Chain",
        ("parameters", "text"),
        "7184c465b9c60fdd53b4712aeee81032d02484f1d1d34b3a7714a27edf0eacb0",
    ),
    SourceFieldContract(
        "Job Searcher - Overall Analysis.json",
        "Overall Analysis Chain",
        ("parameters", "messages", "messageValues", 0, "message"),
        "e2fcb79704af65a34877ec4c353b7352579a0c26d1852a039612b32ded959ee9",
    ),
)


@dataclass(frozen=True)
class RenderResult:
    workflow_count: int
    personal_field_count: int
    output_dir: Path | None


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PersonalizationError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _validate_json(
    value: object,
    location: str = "$",
    depth: int = 0,
) -> JsonValue:
    if depth > MAX_JSON_DEPTH:
        raise PersonalizationError(
            f"{location}: JSON nesting exceeds the {MAX_JSON_DEPTH}-level limit"
        )
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PersonalizationError(f"{location}: non-finite JSON number")
        return value
    if isinstance(value, list):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise PersonalizationError(
                f"{location}: JSON array exceeds the {MAX_COLLECTION_ITEMS}-item limit"
            )
        return [
            _validate_json(item, f"{location}[{index}]", depth + 1)
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise PersonalizationError(
                f"{location}: JSON object exceeds the {MAX_COLLECTION_ITEMS}-item limit"
            )
        normalized: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PersonalizationError(
                    f"{location}: JSON object key is not a string"
                )
            normalized[key] = _validate_json(item, f"{location}.{key}", depth + 1)
        return normalized
    raise PersonalizationError(
        f"{location}: unsupported JSON value type {type(value).__name__}"
    )


def _require_directory(path: Path, label: str) -> None:
    if path.is_symlink():
        raise PersonalizationError(f"{label} must not be a symbolic link: {path}")
    if not path.is_dir():
        raise PersonalizationError(
            f"{label} does not exist or is not a directory: {path}"
        )


def _read_personal_field(data_dir: Path, field: PersonalField) -> str:
    path = data_dir / field.filename
    if path.is_symlink():
        raise PersonalizationError(f"private input must not be a symbolic link: {path}")
    try:
        metadata = path.stat()
    except FileNotFoundError as error:
        raise PersonalizationError(
            f"missing {field.description} file: {path}"
        ) from error
    if not stat.S_ISREG(metadata.st_mode):
        raise PersonalizationError(f"private input is not a regular file: {path}")
    if metadata.st_size > field.max_bytes:
        raise PersonalizationError(f"{path} exceeds its {field.max_bytes}-byte limit")
    try:
        value = path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError as error:
        raise PersonalizationError(
            f"private input is not valid UTF-8: {path}"
        ) from error
    if not value:
        raise PersonalizationError(f"private input is empty: {path}")
    if "\x00" in value:
        raise PersonalizationError(f"private input contains a NUL character: {path}")
    if "[[" in value or "]]" in value:
        raise PersonalizationError(
            f"private input still contains an unfinished [[...]] template marker: {path}"
        )
    if PLACEHOLDER_PATTERN.search(value):
        raise PersonalizationError(
            f"private input must not contain workflow placeholder tokens: {path}"
        )
    if not field.allow_n8n_delimiters and ("{{" in value or "}}" in value):
        raise PersonalizationError(
            f"private input must not contain n8n expression delimiters '{{{{' or '}}}}': {path}"
        )
    if field.numeric_salary:
        salary_match = SALARY_PATTERN.fullmatch(value)
        if salary_match is None:
            raise PersonalizationError(
                f"{path} must use 'AMOUNT CURRENCY BASIS', for example "
                "'150000 USD base salary'"
            )
        currency = salary_match.group("currency")
        if currency not in ISO_4217_CODES:
            raise PersonalizationError(
                f"{path} currency must be a current ISO 4217 code"
            )
        salary = int(salary_match.group("amount"))
        if not MIN_TARGET_SALARY <= salary <= MAX_TARGET_SALARY:
            raise PersonalizationError(
                f"{path} amount must be from {MIN_TARGET_SALARY} through "
                f"{MAX_TARGET_SALARY}"
            )
    return value


def load_personal_values(data_dir: Path) -> dict[str, str]:
    """Read and validate every private Markdown input."""
    _require_directory(data_dir, "private data directory")
    return {
        field.token: _read_personal_field(data_dir, field) for field in PERSONAL_FIELDS
    }


def _collect_placeholders(value: JsonValue, counts: Counter[str]) -> None:
    if isinstance(value, str):
        counts.update(PLACEHOLDER_PATTERN.findall(value))
        return
    if isinstance(value, list):
        for item in value:
            _collect_placeholders(item, counts)
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_placeholders(item, counts)


def _reject_credential_assignments(value: JsonValue, location: str = "$") -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_credential_assignments(item, f"{location}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "credentials":
                raise PersonalizationError(
                    f"credential assignments are not allowed in workflow sources: {location}.{key}"
                )
            _reject_credential_assignments(item, f"{location}.{key}")


def _expected_source_placeholders() -> Counter[str]:
    expected = Counter(
        {field.token: field.expected_occurrences for field in PERSONAL_FIELDS}
    )
    expected.update(CONFIG_PLACEHOLDER_COUNTS)
    return expected


def _replace_string(value: str, personal_values: dict[str, str]) -> str:
    resume_token = "[YOUR_RESUME_IN_MARKDOWN]"
    if resume_token in value:
        wrapped_token = f"`{resume_token}`"
        if wrapped_token not in value or value.count(resume_token) != value.count(
            wrapped_token
        ):
            raise PersonalizationError(
                "resume placeholder is no longer in its expected JavaScript template-literal context"
            )
        resume_literal = json.dumps(personal_values[resume_token], ensure_ascii=True)
        value = value.replace(wrapped_token, resume_literal)

    for field in PERSONAL_FIELDS:
        if field.token == resume_token:
            continue
        value = value.replace(field.token, personal_values[field.token])
    return value


def _replace_personal_placeholders(
    value: JsonValue,
    personal_values: dict[str, str],
) -> JsonValue:
    if isinstance(value, str):
        return _replace_string(value, personal_values)
    if isinstance(value, list):
        return [_replace_personal_placeholders(item, personal_values) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_personal_placeholders(item, personal_values)
            for key, item in value.items()
        }
    return value


def _load_workflows(source_dir: Path) -> dict[str, dict[str, JsonValue]]:
    _require_directory(source_dir, "workflow source directory")
    paths = sorted(source_dir.glob("*.json"))
    if not paths:
        raise PersonalizationError(f"no workflow JSON files found in {source_dir}")
    if len(paths) > MAX_WORKFLOW_FILES:
        raise PersonalizationError(
            f"workflow source exceeds the {MAX_WORKFLOW_FILES}-file limit: {source_dir}"
        )

    workflows: dict[str, dict[str, JsonValue]] = {}
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise PersonalizationError(
                f"workflow source must be a regular file: {path}"
            )
        if path.stat().st_size > MAX_WORKFLOW_BYTES:
            raise PersonalizationError(
                f"workflow source exceeds the {MAX_WORKFLOW_BYTES}-byte limit: {path}"
            )
        try:
            parsed: object = json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
            )
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
        ) as error:
            raise PersonalizationError(
                f"cannot parse workflow JSON {path}: {error}"
            ) from error
        normalized = _validate_json(parsed)
        if not isinstance(normalized, dict):
            raise PersonalizationError(f"workflow root must be a JSON object: {path}")
        if not isinstance(normalized.get("nodes"), list):
            raise PersonalizationError(f"workflow has no nodes array: {path}")
        _reject_credential_assignments(normalized)
        workflows[path.name] = normalized
    return workflows


def _get_contract_value(
    workflows: dict[str, dict[str, JsonValue]],
    contract: SourceFieldContract,
) -> str:
    workflow = workflows.get(contract.workflow_filename)
    if workflow is None:
        raise PersonalizationError(
            f"required workflow is missing: {contract.workflow_filename}"
        )
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        raise PersonalizationError(
            f"workflow has no nodes array: {contract.workflow_filename}"
        )
    matches = [
        node
        for node in nodes
        if isinstance(node, dict) and node.get("name") == contract.node_name
    ]
    if len(matches) != 1:
        raise PersonalizationError(
            f"expected one node named {contract.node_name!r} in "
            f"{contract.workflow_filename}; found {len(matches)}"
        )

    current: JsonValue = matches[0]
    for part in contract.path:
        if isinstance(part, int):
            if not isinstance(current, list) or not 0 <= part < len(current):
                raise PersonalizationError(
                    f"placeholder field path changed in {contract.workflow_filename}/"
                    f"{contract.node_name}: {contract.path}"
                )
            current = current[part]
        else:
            if not isinstance(current, dict) or part not in current:
                raise PersonalizationError(
                    f"placeholder field path changed in {contract.workflow_filename}/"
                    f"{contract.node_name}: {contract.path}"
                )
            current = current[part]
    if not isinstance(current, str):
        raise PersonalizationError(
            f"placeholder field is no longer text in {contract.workflow_filename}/"
            f"{contract.node_name}: {contract.path}"
        )
    return current


def _verify_source_field_contracts(
    workflows: dict[str, dict[str, JsonValue]],
) -> None:
    for contract in SOURCE_FIELD_CONTRACTS:
        value = _get_contract_value(workflows, contract)
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        if digest != contract.sha256:
            raise PersonalizationError(
                f"placeholder-bearing field changed in {contract.workflow_filename}/"
                f"{contract.node_name}; review the generator contract before continuing"
            )


def _paths_overlap(first: Path, second: Path) -> bool:
    first_resolved = first.resolve(strict=False)
    second_resolved = second.resolve(strict=False)
    return (
        first_resolved == second_resolved
        or first_resolved.is_relative_to(second_resolved)
        or second_resolved.is_relative_to(first_resolved)
    )


def _validate_path_boundaries(
    source_dir: Path,
    data_dir: Path,
    output_dir: Path,
) -> None:
    if _paths_overlap(output_dir, source_dir):
        raise PersonalizationError(
            "output directory must not overlap the public workflow source directory"
        )
    if _paths_overlap(output_dir, data_dir):
        raise PersonalizationError(
            "output directory must not overlap the private data directory"
        )


def _render(
    source_dir: Path,
    data_dir: Path,
    output_dir: Path,
) -> tuple[dict[str, str], int]:
    _validate_path_boundaries(source_dir, data_dir, output_dir)
    personal_values = load_personal_values(data_dir)
    workflows = _load_workflows(source_dir)
    _verify_source_field_contracts(workflows)

    source_counts: Counter[str] = Counter()
    for workflow in workflows.values():
        _collect_placeholders(workflow, source_counts)
    expected_counts = _expected_source_placeholders()
    if source_counts != expected_counts:
        missing = expected_counts - source_counts
        unexpected = source_counts - expected_counts
        details: list[str] = []
        if missing:
            details.append(f"missing or reduced placeholders: {dict(missing)}")
        if unexpected:
            details.append(f"unexpected or duplicated placeholders: {dict(unexpected)}")
        raise PersonalizationError(
            "workflow placeholder contract changed; " + "; ".join(details)
        )

    rendered: dict[str, str] = {}
    output_counts: Counter[str] = Counter()
    for filename, workflow in workflows.items():
        personalized = _replace_personal_placeholders(workflow, personal_values)
        if not isinstance(personalized, dict):
            raise PersonalizationError(
                f"personalized workflow root changed type: {filename}"
            )
        personalized["active"] = False
        _reject_credential_assignments(personalized)
        _collect_placeholders(personalized, output_counts)
        rendered[filename] = (
            json.dumps(
                personalized,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        )

    if output_counts != CONFIG_PLACEHOLDER_COUNTS:
        raise PersonalizationError(
            "generated workflows did not preserve exactly the expected web-interface placeholders"
        )
    return rendered, len(personal_values)


def _write_atomically(output_dir: Path, rendered: dict[str, str]) -> None:
    if output_dir.exists() or output_dir.is_symlink():
        raise PersonalizationError(
            f"output directory already exists; remove it or choose another path: {output_dir}"
        )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}-",
            dir=output_dir.parent,
        )
    )
    try:
        os.chmod(staging, 0o700)
        for filename, content in rendered.items():
            destination = staging / filename
            descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            os.chmod(destination, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        staging.rename(output_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def render_workflows(
    source_dir: Path,
    data_dir: Path,
    output_dir: Path,
    *,
    check_only: bool,
) -> RenderResult:
    """Validate private inputs and generate inactive personalized workflow copies."""
    rendered, personal_field_count = _render(source_dir, data_dir, output_dir)
    if check_only:
        return RenderResult(
            workflow_count=len(rendered),
            personal_field_count=personal_field_count,
            output_dir=None,
        )
    _write_atomically(output_dir, rendered)
    return RenderResult(
        workflow_count=len(rendered),
        personal_field_count=personal_field_count,
        output_dir=output_dir,
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate inactive private workflow copies from personal Markdown files. "
            "RSS URLs, email addresses, credentials, and provider settings remain for n8n."
        )
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"private Markdown directory (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help=f"public workflow template directory (default: {DEFAULT_SOURCE_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"new private output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate inputs and placeholder contracts without writing output",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = render_workflows(
            source_dir=args.source_dir,
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            check_only=args.check,
        )
    except PersonalizationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.check:
        print(
            f"Validated {result.personal_field_count} personal files against "
            f"{result.workflow_count} workflow templates; no output was written."
        )
    else:
        print(
            f"Generated {result.workflow_count} inactive personalized workflows in "
            f"{result.output_dir}."
        )
        print(
            "RSS feed URLs and sender/recipient email placeholders were preserved "
            "for configuration in n8n."
        )
        print("The output contains private data; do not commit or share it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
