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
| `work-arrangement-requirements.md` | `[YOUR_WORK_ARRANGEMENT_REQUIREMENTS]` | Hard eligibility gate: required remote, hybrid, or on-site arrangement plus any mandatory office geography, relocation, travel, or timezone conditions |
| `eligible-work-location.md` | `[YOUR_ELIGIBLE_WORK_LOCATION]` | Hard eligibility gate: candidate location and work jurisdiction in which the role must permit employment |
| `additional-location-preferences.md` | `[YOUR_ADDITIONAL_LOCATION_PREFERENCES]` | Non-gating, soft timezone, travel, residency, or location preferences used in final synthesis; enter `None` when unused |
| `target-annual-salary.md` | `[TARGET_ANNUAL_SALARY]` | Comparable annual compensation target used by Preference and Overall Analysis |

The salary file must use exactly this format:

```text
AMOUNT CURRENCY BASIS
```

For example:

```text
150000 USD base salary
```

`AMOUNT` must be an integer from `1000` through `999999999`. `CURRENCY` must be a current three-letter uppercase ISO 4217 code. `BASIS` must be either `base salary` or `total compensation`. The prompts do not assume currency conversion and treat a posting with a different or unclear currency/basis as non-comparable.

Before generating, check that:

- the work-arrangement file contains all mandatory remote/hybrid/on-site, office-geography, relocation, travel, and timezone conditions;
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

The generator writes to `personalized-workflows/`, refuses source workflows containing credential assignments, and preserves the RSS feed URL plus sender/recipient email placeholders for configuration in n8n. It refuses to overwrite an existing output directory.

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
