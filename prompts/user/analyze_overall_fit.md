Evaluate final job fit using the validated upstream evidence and the deterministic gates and weighted scoring rules in the system instructions.

<record_metadata>
{{ JSON.stringify({ job_id: String($json.job?.job_id || '') }, null, 2) }}
</record_metadata>

<candidate_priorities>
- [YOUR_TEAM_AND_CULTURE_PRIORITIES]
- [YOUR_GROWTH_AND_CHALLENGE_PRIORITIES]
- [YOUR_DOMAIN_PRIORITIES]
- [YOUR_ADDITIONAL_LOCATION_PREFERENCES]
</candidate_priorities>

<preference_analysis>
{{ JSON.stringify($json.results?.preferences || {}, null, 2) }}
</preference_analysis>

<skill_analysis>
{{ JSON.stringify($json.results?.skills || {}, null, 2) }}
</skill_analysis>

Apply every veto and minimum-evidence gate before scoring. Return only the analytical fields required by the connected parser. The canonical job_id is attached after validation.
