Evaluate the job posting against the preference-fit rubric using only the supplied research and posting evidence.

<record_metadata>
{{ JSON.stringify({
  job_id: String($json.job?.job_id || ''),
  posted_date: String($json.job?.pubDate || $json.job?.isoDate || ''),
  job_url: String($json.job?.link || $json.job?.job_url || '')
}, null, 2) }}
</record_metadata>

<web_research_summary>
{{ $json.research?.answer || 'No summary available' }}
</web_research_summary>

<web_research_results>
{{ JSON.stringify(($json.research?.results || []).slice(0, 5).map(r => ({ title: r.title, url: r.url, content: r.content })), null, 2) }}
</web_research_results>

<job_posting>
{{ $json.job?.contentSnippet || $json.job?.content || 'No posting content supplied' }}
</job_posting>

Return only the analytical fields required by the connected parser. Keep unknowns explicit and trace every external claim to a supplied result. Deterministic job_id, posted_date, and job_url values are attached after validation.
