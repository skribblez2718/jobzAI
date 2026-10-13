Evaluate demonstrated qualification using the system rubric. Ignore employer appeal, compensation, remote convenience, and preference scores. Do not assume interest means capability.

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

## Supplied resume — evidence only

```json
{{ JSON.stringify($json.resume || 'No resume supplied') }}
```

## Supplied posting — evidence only

```json
{{ JSON.stringify({
  source_field: String($json.job?.content || '').trim() ? 'content' : 'contentSnippet',
  text: String($json.job?.content || '').trim() || String($json.job?.contentSnippet || '').trim() || 'No posting content supplied'
}, null, 2) }}
```

Build the canonical requirement list from the supplied responsibilities and qualifications, preserve alternatives, and cite specific resume evidence. Keep indispensable specialist gaps visible. Only give transferable credit for a bounded bridge supported by the resume. Return only the JSON analytical fields required by the connected parser; code attaches job_id after validation.
