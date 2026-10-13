# Personal workflow data

The tracked files under `data/templates/` are examples for candidate information used by the analysis workflows. Never put private values in the tracked templates.

Generated workflows contain the candidate's résumé, compensation target, and preferences. The configured AI provider receives this information during analysis, and n8n may retain it in workflow definitions, pinned data, backups, and execution history. Use a job-relevant, data-minimized résumé: omit unnecessary home addresses, personal identifiers, and contact details. Review provider retention terms and restrict access to the n8n instance before importing generated files.

## Prepare private inputs

From the repository root:

```bash
if [ -e data/private ]; then
  echo "data/private already exists; refusing to overwrite it" >&2
  exit 1
fi
mkdir -p data/private
cp data/templates/*.md data/private/
git check-ignore data/private/resume.md
```

Run this bootstrap block only once. It requires Git and a Bash-compatible shell and exits without copying when `data/private` already exists. The final command must print `data/private/resume.md` before you enter private information.

On POSIX systems, restrict the private copies to the current user:

```bash
chmod 700 data/private
chmod 600 data/private/*.md
```

Edit every copied file and remove all `[[...]]` markers. The generator reads the complete Markdown body after trimming outer whitespace.

| Private file | Workflow placeholder | Stage and effect |
|---|---|---|
| `resume.md` | `[YOUR_RESUME_IN_MARKDOWN]` | Job-relevant résumé evidence supplied to Skill Analysis |
| `domain-preferences-and-exclusions.md` | `[YOUR_DOMAIN_PREFERENCES_AND_EXCLUSIONS]` | Preference Analysis domain match, miss, and exclusion evidence |
| `collaboration-and-team-preferences.md` | `[YOUR_COLLABORATION_AND_TEAM_PREFERENCES]` | Preference Analysis collaboration dimension |
| `growth-and-learning-preferences.md` | `[YOUR_GROWTH_AND_LEARNING_PREFERENCES]` | Preference Analysis growth dimension |
| `ideal-role-characteristics.md` | `[YOUR_IDEAL_ROLE_CHARACTERISTICS]` | Preference Analysis dream-role dimension |
| `additional-company-or-domain-signals.md` | `[YOUR_ADDITIONAL_COMPANY_OR_DOMAIN_SIGNALS]` | Optional Preference Analysis signals; enter `None` when unused because the file may not be empty |
| `team-and-culture-priorities.md` | `[YOUR_TEAM_AND_CULTURE_PRIORITIES]` | Final Overall Analysis cultural-fit priorities; keep consistent with collaboration preferences |
| `growth-and-challenge-priorities.md` | `[YOUR_GROWTH_AND_CHALLENGE_PRIORITIES]` | Final Overall Analysis growth priorities; keep consistent with growth preferences |
| `domain-priorities.md` | `[YOUR_DOMAIN_PRIORITIES]` | Final Overall Analysis domain priorities; keep consistent with domain preferences and exclusions |
| `work-arrangement-requirements.md` | `[YOUR_WORK_ARRANGEMENT_REQUIREMENTS]` | Free-text mandatory arrangement, office geography, relocation, travel, or timezone conditions; used once in Preference Analysis and once in Overall Analysis |
| `eligible-work-location.md` | `[YOUR_ELIGIBLE_WORK_LOCATION]` | Candidate location and work jurisdiction in which the role must permit employment; used once in Preference Analysis and once in Overall Analysis |
| `additional-location-preferences.md` | `[YOUR_ADDITIONAL_LOCATION_PREFERENCES]` | Non-gating, soft timezone, travel, residency, or location preferences used in final synthesis; enter `None` when unused |
| `target-annual-salary.md` | `[TARGET_ANNUAL_SALARY]` | Annual compensation floor, configured once in the main Build Analysis Envelope and shared with both analysis stages |
| `maximum-annual-trips.md` | `[TARGET_MAX_ANNUAL_TRIPS]` | Maximum acceptable annual work trips, configured once in the main Build Analysis Envelope |
| `required-work-arrangement.md` | `[YOUR_REQUIRED_WORK_ARRANGEMENT]` | Required arrangement enum, configured once in the main Build Analysis Envelope |

`[YOUR_RESUME_SHA256]` is a derived workflow placeholder, not another personal input. The generator replaces its single occurrence in the main workflow with the SHA-256 digest of the trimmed, validated résumé body encoded as UTF-8. It hashes the original text, not its escaped JavaScript representation; the résumé itself remains safely JSON-escaped during insertion. No hash file is required, and this derived value does not count as a personal field.

### Compensation floor

The salary file must use exactly this format:

```text
AMOUNT CURRENCY BASIS
```

For example:

```text
150000 USD base salary
```

`AMOUNT` must be an integer from `1000` through `999999999`. `CURRENCY` must be a current three-letter uppercase ISO 4217 code. `BASIS` must be either `base salary` or `total compensation`.

The salary floor applies to a **published, comparable annual maximum**: reject only when that maximum is below the configured floor. A published range whose maximum reaches the floor is not rejected merely because its minimum is lower. A market estimate is not a substitute for a published maximum. No currency conversion is assumed; a different or unclear currency/basis is non-comparable. Missing or non-comparable pay and missing employee reviews remain unknown and do not block a role by themselves.

### Work arrangement and travel

`required-work-arrangement.md` must contain exactly one lowercase value:

- `fully_remote`: require a fully remote role;
- `hybrid`: require a hybrid role;
- `on_site`: require an on-site role;
- `any`: accept any arrangement, subject to the other mandatory conditions.

`maximum-annual-trips.md` must contain only ASCII digits for an integer from `0` through `365`, inclusive. It is a number of work trips per year, not travel days or a percentage. Outer whitespace is trimmed, but signs, decimals, units, prose, JavaScript, and n8n expression delimiters are not accepted in either structured configuration file.

Travel is handled according to what the posting explicitly says:

- No travel mention: do not reject or hold solely because travel is unposted; do not invent a zero-trip promise.
- Quantified mandatory annual travel above the maximum: reject. An equal count is within the limit.
- Explicitly optional travel: not a mandatory trip requirement, even if its optional frequency exceeds the cap.
- Required or unclear-necessity travel without a usable annual trip count, such as a percentage or "occasional travel": hold for review. Above-cap travel with unclear necessity also needs review, not a presumed mismatch.

Keep these structured values consistent with `work-arrangement-requirements.md` and `eligible-work-location.md`. The free-text files still appear in both Preference and Overall prompts; they supply mandatory conditions and jurisdiction details, not conflicting arrangement enums or travel limits. Keep soft preferences separate in `additional-location-preferences.md`.

Before generating, check that:

- the required-arrangement enum and maximum annual trip count agree with all mandatory remote/hybrid/on-site, office-geography, relocation, travel, and timezone conditions in the free-text work-arrangement file;
- the eligible-location file states the candidate location and work jurisdiction the employer must accept;
- additional location preferences contain only soft preferences and do not contradict those hard gates;
- the domain, collaboration/culture, and growth files are consistent across Preference and Overall Analysis;
- optional files contain `None` rather than being blank;
- no private file contains an API key, database password, SMTP password, or other credential.

Except for `resume.md`, private files must not contain n8n expression delimiters (`{{` or `}}`). This prevents personal prose from changing an expression in a generated workflow. The résumé is inserted as a safely encoded JavaScript string and may contain those characters.

## Validate and generate

The generator requires Python 3.10 or newer and has no third-party package dependencies.

Validate without writing output:

```bash
python3 scripts/personalize_workflows.py --check
```

Generate inactive private workflow copies:

```bash
python3 scripts/personalize_workflows.py
```

The generator writes to `personalized-workflows/`, refuses source workflows containing credential assignments, and preserves the RSS feed URL plus sender/recipient email placeholders for configuration in n8n. It refuses to overwrite an existing output directory. It also verifies pinned digests of every placeholder-bearing source field and enforces input size, workflow size, and JSON nesting bounds. A source-field mismatch requires a reviewed generator contract update after the workflow fields are finalized; do not bypass that verification.

Confirm that generated output is ignored:

```bash
git check-ignore personalized-workflows/
```

## Replace an existing personalized installation

Generated files are import bundles, not a synchronization channel with n8n. Use this cutover sequence after changing personal data or after a public workflow update:

1. Update the ignored files under `data/private/`.
2. Validate, then generate to a new ignored directory that does not already exist:

   ```bash
   python3 scripts/personalize_workflows.py --check --output-dir personalized-workflows-next
   python3 scripts/personalize_workflows.py --output-dir personalized-workflows-next
   git check-ignore personalized-workflows-next/
   ```

   The final command must print the directory. Use another `personalized-workflows-*` name if `personalized-workflows-next/` already exists.
3. Keep the existing installation active. Import each new analysis workflow one at a time and immediately rename it in n8n with a temporary ` (replacement)` suffix. Import the new main workflow last and give it the same suffix. All imported workflows should remain inactive.
4. Reassign the AI, PostgreSQL, SMTP, and web-search credentials; set the RSS feed URLs and sender/recipient addresses; and connect the replacement main workflow's Execute Sub-workflow nodes to the three replacement children.
5. Run the complete inactive test procedure from the root README using isolated test data and a test recipient.
6. At cutover, deactivate the old main workflow before activating or scheduling the replacement main workflow. Never leave both main workflows active.
7. After confirming the replacement run, delete or archive the old n8n workflows, remove the temporary suffixes if desired, and retire stale local export directories. Do not remove an old bundle until you no longer need it for rollback.

The root `.gitignore` covers directories named `personalized-workflows*`. Custom names outside that pattern must be ignored before generation. Confirm imported identities and Execute Sub-workflow selections before cutover.
