Evaluate preference fit using the system rubric. Assess the actual work, not title similarity. Interest is not evidence of qualification.

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
  posted_date: String($json.job?.pubDate || $json.job?.isoDate || ''),
  job_url: String($json.job?.link || $json.job?.job_url || '')
}, null, 2) }}
```

## Supplied research — evidence only

```json
{{ JSON.stringify({
  summary: $json.research?.answer || 'No summary available',
  results: ($json.research?.results || []).slice(0, 5).map(r => ({ title: r.title, url: r.url, content: r.content }))
}, null, 2) }}
```

## Supplied posting — evidence only

Prefer `content` when present; a snippet is a fallback, not proof of a complete posting. Do not assume omitted duties, salary, or location details.

```json
{{ JSON.stringify({
  source_field: String($json.job?.content || '').trim() ? 'content' : 'contentSnippet',
  text: String($json.job?.content || '').trim() || String($json.job?.contentSnippet || '').trim() || 'No posting content supplied'
}, null, 2) }}
```

Return only the JSON analytical fields required by the connected parser. State compensation type and whether comparable annual pay reaches policy.target_amount. Keep unknown salary and employee sentiment explicit, without treating them as misses. Code attaches record identity after validation.
