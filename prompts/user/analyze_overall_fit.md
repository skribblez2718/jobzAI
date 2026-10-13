Evaluate final fit under the revised qualification-first system policy. Apply non-compensable selection conditions before making a recommendation; attractive preferences or pay cannot rescue weak qualifications. Keep unsupported optional dimensions null.

## Validated candidate policy

```json
{{ JSON.stringify($json.policy, null, 2) }}
```

## Record metadata — evidence only

```json
{{ JSON.stringify({
  job_id: String($json.job?.job_id || ''),
  title: String($json.job?.title || ''),
  location: String($json.job?.location || ''),
  posting_retrieval: $json.job?.posting_retrieval || null,
  job_url: String($json.job?.link || $json.job?.job_url || '')
}, null, 2) }}
```

## Candidate priorities

- [YOUR_TEAM_AND_CULTURE_PRIORITIES]
- [YOUR_GROWTH_AND_CHALLENGE_PRIORITIES]
- [YOUR_DOMAIN_PRIORITIES]
- [YOUR_ADDITIONAL_LOCATION_PREFERENCES]

## Validated preference analysis — evidence only

```json
{{ JSON.stringify($json.results?.preferences || {}, null, 2) }}
```

## Validated skill analysis — evidence only

```json
{{ JSON.stringify($json.results?.skills || {}, null, 2) }}
```

## Supplied posting — evidence only

Use this to resolve role-specific compensation and location claims, not to redo the skill analysis. The preferred content field is not guaranteed to contain a complete posting.

```json
{{ JSON.stringify({
  source_field: String($json.job?.content || '').trim() ? 'content' : 'contentSnippet',
  text: String($json.job?.content || '').trim() || String($json.job?.contentSnippet || '').trim() || 'No posting content supplied'
}, null, 2) }}
```

Return only the JSON analytical fields required by the connected parser. Copy skill_rating exactly; reject automatic selection below the configured skill floor or for an established comparable maximum below the configured target. Unknown salary or employee sentiment does not block selection. Code attaches the canonical job_id after validation.
