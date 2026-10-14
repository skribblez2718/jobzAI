'use strict';

// Shared, dependency-free policy embedded verbatim into the exported Code nodes.
// Treat model output as data. Source-excerpt checks establish provenance, not semantic truth.
const FIT_DIMENSIONS = ['employee_satisfaction', 'salary_competitiveness', 'remote_work_flexibility', 'skills_alignment', 'cultural_fit'];
const FIT_WEIGHTS = Object.freeze({skills_alignment: 60, salary_competitiveness: 15, remote_work_flexibility: 10, cultural_fit: 10, employee_satisfaction: 5});
function fitObject(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
function fitExact(value, keys, label) {
  if (!fitObject(value) || Object.keys(value).length !== keys.length || keys.some(key => !Object.prototype.hasOwnProperty.call(value, key))) throw new Error(`${label}: invalid fields.`);
}
function fitText(value, max, label) {
  if (typeof value !== 'string' || !value.trim() || value.length > max) throw new Error(`${label}: invalid text.`);
}
function fitEnum(value, allowed, label) { if (!allowed.includes(value)) throw new Error(`${label}: invalid enum.`); }
function fitNumber(value, min, max, label, integer = false) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max || (integer && !Number.isInteger(value))) throw new Error(`${label}: invalid number.`);
}
function fitReadPolicy(envelope) {
  const p = envelope.policy;
  fitExact(p, ['version','target_amount','target_currency','target_basis','required_work_arrangement','max_annual_trips','minimum_skill_rating','score_threshold','resume_sha256'], 'policy');
  fitText(p.version, 80, 'policy.version');
  fitNumber(p.target_amount, 1000, 999999999, 'policy.target_amount', true);
  if (typeof p.target_currency !== 'string' || !/^[A-Z]{3}$/.test(p.target_currency)) throw new Error('Invalid target currency.');
  fitEnum(p.target_basis, ['base','total_compensation'], 'policy.target_basis');
  fitEnum(p.required_work_arrangement, ['fully_remote','hybrid','on_site','any'], 'policy.required_work_arrangement');
  fitNumber(p.max_annual_trips, 0, 365, 'policy.max_annual_trips', true);
  fitNumber(p.minimum_skill_rating, 1, 5, 'policy.minimum_skill_rating', true);
  fitNumber(p.score_threshold, 1, 5, 'policy.score_threshold');
  if (typeof p.resume_sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(p.resume_sha256)) throw new Error('Invalid resume digest.');
  return p;
}
function fitNormalize(value) { return String(value || '').replace(/\s+/g, ' ').trim(); }
// Keep only bounded fields that are supplied verbatim to the model and evidence validator.
// Oversized research text is omitted, not silently treated as a complete source.
function fitNormalizeResearch(source) {
  source = source && typeof source === 'object' && !Array.isArray(source) ? source : {};
  const rawAnswer = typeof source.answer === 'string' ? source.answer : '';
  const results = [];
  let limited = rawAnswer.length > 8000;
  for (const row of (Array.isArray(source.results) ? source.results : []).slice(0, 5)) {
    if (!row || typeof row !== 'object' || Array.isArray(row)) { limited = true; continue; }
    const url = typeof row.url === 'string' ? row.url.trim() : '';
    const authority = url.split('/')[2] || '';
    if (!/^https?:\/\//i.test(url) || url.length > 2048 || /[\x00-\x20\x7f]/.test(url) || !authority || authority.includes('@')) { limited = true; continue; }
    const title = typeof row.title === 'string' ? row.title : '';
    const content = typeof row.content === 'string' ? row.content : '';
    const omitted = content.length > 20000;
    limited ||= omitted || title.length > 500;
    results.push({url, title:title.slice(0, 500), content:omitted ? '' : content, content_omitted:omitted, title_truncated:title.length > 500, published_date:typeof row.published_date === 'string' ? row.published_date.slice(0, 50) : ''});
  }
  return {answer:rawAnswer.length > 8000 ? '' : rawAnswer, answer_omitted:rawAnswer.length > 8000, results, limited_data:limited, error:source.error ? 'Research unavailable.' : null};
}

function fitPostingText(envelope) { return String(envelope.job?.content || '').trim() || String(envelope.job?.contentSnippet || '').trim(); }
function fitSourceMap(envelope) {
  const map = new Map();
  const url = String(envelope.job?.link || envelope.job?.job_url || '').replace(/\/$/, '');
  if (url) map.set(url, [envelope.job?.title, envelope.job?.location, fitPostingText(envelope)].filter(Boolean).map(fitNormalize));
  for (const source of (envelope.research?.results || []).slice(0, 5)) {
    if (typeof source.url === 'string' && typeof source.content === 'string') {
      const key = source.url.replace(/\/$/, '');
      map.set(key, [...(map.get(key) || []), ...[source.title,source.content].filter(Boolean).map(fitNormalize)]);
    }
  }
  return map;
}
function fitEvidence(records, envelope, label, required = true) {
  if (!Array.isArray(records) || records.length > 5 || (required && records.length === 0)) throw new Error(`${label}: missing or excessive source evidence.`);
  const sources = fitSourceMap(envelope);
  for (const [index, record] of records.entries()) {
    const field = `${label}[${index}]`;
    fitExact(record, ['source_url','quote'], field);
    fitText(record.source_url, 2048, `${field}.source_url`);
    fitText(record.quote, 1500, `${field}.quote`);
    const source = sources.get(record.source_url.replace(/\/$/, ''));
    if (!source) throw new Error(`${field}: excerpt source URL was not supplied; copy its supplied URL exactly.`);
    if (!source.some(chunk => chunk.includes(fitNormalize(record.quote)))) throw new Error(`${field}: excerpt is not present in the supplied source; copy one contiguous passage verbatim, without joining fields or bullets.`);
  }
}
function fitEligibility(preferences, policy) {
  const e = preferences.eligibility;
  const reasons = [], holds = [];
  if (e.work_arrangement !== 'unknown' && policy.required_work_arrangement !== 'any' && e.work_arrangement !== policy.required_work_arrangement) reasons.push('work_arrangement_mismatch');
  else if (e.arrangement_status === 'failed') reasons.push('work_arrangement_failed');
  else if (e.arrangement_status !== 'confirmed' || (e.work_arrangement === 'unknown' && policy.required_work_arrangement !== 'any')) holds.push('work_arrangement_unverified');
  if (e.location_status === 'failed') reasons.push('work_location_ineligible');
  else if (e.location_status !== 'confirmed') holds.push('work_location_unverified');
  const t = preferences.travel;
  if (t.status === 'quantified' && t.annual_trips_max > policy.max_annual_trips && t.mandatory === true) reasons.push('travel_exceeds_limit');
  if (t.status === 'quantified' && t.annual_trips_max > policy.max_annual_trips && t.mandatory === null) holds.push('travel_necessity_unverified');
  if (t.status === 'unquantified' && t.mandatory !== false) holds.push('travel_frequency_unverified');
  return {state: reasons.length ? 'failed' : holds.length ? 'unverified' : 'confirmed', reasons, holds};
}
function fitCompensation(preferences, policy) {
  const c = preferences.compensation;
  if (c.status !== 'known') return {rating: null, maximum: null, below_target: false};
  const comparable = c.ranges.filter(r => r.currency === policy.target_currency && r.basis === policy.target_basis && r.period === 'annual' && r.applicability === 'applicable');
  if (!comparable.length) return {rating: null, maximum: null, below_target: false};
  const signatures = new Set(comparable.map(r => JSON.stringify([r.minimum,r.maximum])));
  let r = comparable[0];
  if (signatures.size !== 1) {
    // A complete range may corroborate matching one-sided statements in the same
    // geography. Distinct complete ranges (even overlapping) are not merged.
    const complete = comparable.filter(row => row.minimum !== null && row.maximum !== null);
    const completeSignatures = new Set(complete.map(row => JSON.stringify([row.minimum,row.maximum])));
    const anchor = complete[0];
    const compatible = anchor && completeSignatures.size === 1 && comparable.every(row =>
      fitNormalize(row.location_scope).toLowerCase() === fitNormalize(anchor.location_scope).toLowerCase() &&
      (row.minimum === null || row.minimum === anchor.minimum) &&
      (row.maximum === null || row.maximum === anchor.maximum));
    if (!compatible) return {rating:null, maximum:null, below_target:false, conflicting:true};
    r = anchor;
  }
  if (r.maximum !== null && r.maximum < policy.target_amount) return {rating: 1, maximum: r.maximum, below_target: true};
  if (r.minimum !== null && r.minimum >= policy.target_amount) return {rating: 5, maximum: r.maximum, below_target: false};
  if (r.maximum !== null && r.maximum >= policy.target_amount) return {rating: 4, maximum: r.maximum, below_target: false};
  return {rating: null, maximum: r.maximum, below_target: false};
}
// Call only after fitValidateFacts: uncertainty cannot bypass source/type checks.
function fitNormalizeCompensation(compensation, policy) {
  if (!fitCompensation({compensation}, policy).conflicting) return compensation;
  return {...compensation, status:'conflicting', note:'Unresolved applicable comparable pay ranges; no salary rating or salary veto. ' + compensation.note.slice(0, 700)};
}
function fitValidateFacts(preferences, envelope) {
  const p = fitReadPolicy(envelope);
  const e = preferences.eligibility;
  fitExact(e, ['work_arrangement','arrangement_status','location_status','evidence'], 'eligibility');
  fitEnum(e.work_arrangement, ['fully_remote','hybrid','on_site','unknown'], 'eligibility.work_arrangement');
  for (const key of ['arrangement_status','location_status']) fitEnum(e[key], ['confirmed','failed','unverified'], `eligibility.${key}`);
  fitEvidence(e.evidence, envelope, 'eligibility.evidence', e.arrangement_status !== 'unverified' || e.location_status !== 'unverified');
  if (e.arrangement_status === 'confirmed' && e.work_arrangement === 'unknown' && p.required_work_arrangement !== 'any') throw new Error('Unknown work arrangement cannot be confirmed.');
  const t = preferences.travel;
  fitExact(t, ['status','annual_trips_max','mandatory','evidence'], 'travel');
  fitEnum(t.status, ['not_stated','quantified','unquantified'], 'travel.status');
  if (t.mandatory !== null && typeof t.mandatory !== 'boolean') throw new Error('Travel mandatory must be boolean or null.');
  if (t.status === 'not_stated' && t.mandatory !== null) throw new Error('Unposted travel cannot invent mandatory status.');
  if (t.status === 'quantified') fitNumber(t.annual_trips_max, 0, 1000, 'travel.annual_trips_max', true);
  else if (t.annual_trips_max !== null) throw new Error('Unquantified/unposted travel must have null annual_trips_max.');
  fitEvidence(t.evidence, envelope, 'travel.evidence', t.status !== 'not_stated');
  if (t.status === 'not_stated' && t.evidence.length) throw new Error('Unposted travel must not invent travel evidence.');
  const c = preferences.compensation;
  fitExact(c, ['status','ranges','note'], 'compensation');
  fitEnum(c.status, ['known','absent','unverified','conflicting'], 'compensation.status');
  fitText(c.note, 800, 'compensation.note');
  if (!Array.isArray(c.ranges) || c.ranges.length > 12 || (c.status === 'known' && !c.ranges.length)) throw new Error('Invalid compensation ranges.');
  if (c.status === 'absent' && c.ranges.length) throw new Error('Absent compensation cannot include ranges.');
  for (const r of c.ranges) {
    fitExact(r, ['currency','basis','period','minimum','maximum','location_scope','applicability','evidence'], 'compensation.range');
    if (typeof r.currency !== 'string' || !/^(?:[A-Z]{3}|unknown)$/.test(r.currency)) throw new Error('Invalid published currency.');
    fitEnum(r.basis, ['base','total_compensation','ote','unknown'], 'compensation.basis');
    fitEnum(r.period, ['annual','monthly','hourly','unknown'], 'compensation.period');
    fitEnum(r.applicability, ['applicable','not_applicable','unverified'], 'compensation.applicability');
    fitText(r.location_scope, 400, 'compensation.location_scope');
    for (const key of ['minimum','maximum']) if (r[key] !== null) fitNumber(r[key], 0, 999999999, `compensation.${key}`);
    if (r.minimum === null && r.maximum === null) throw new Error('A compensation range needs a supported numeric bound.');
    if (r.minimum !== null && r.maximum !== null && r.minimum > r.maximum) throw new Error('Compensation minimum exceeds maximum.');
    fitEvidence(r.evidence, envelope, 'compensation.evidence');
  }
  const a = preferences.availability;
  fitExact(a, ['status','evidence'], 'availability');
  fitEnum(a.status, ['open','closed','unknown'], 'availability.status');
  fitEvidence(a.evidence, envelope, 'availability.evidence', a.status !== 'unknown');
  fitCompensation(preferences, p);
  return fitEligibility(preferences, p);
}
function fitValidateSkills(skills, envelope) {
  fitExact(skills, ['requirements','limited_data_reason','skill_rating','evidence_quality'], 'skills');
  fitNumber(skills.skill_rating, 1, 5, 'skills.skill_rating', true);
  fitEnum(skills.evidence_quality, ['sufficient','partial','insufficient'], 'skills.evidence_quality');
  if (skills.evidence_quality === 'sufficient') {
    if (typeof envelope.resume !== 'string' || !envelope.resume.trim() || !fitPostingText(envelope)) throw new Error('Sufficient evidence requires a supplied resume and posting.');
    if (skills.limited_data_reason !== null) throw new Error('Sufficient skill evidence requires null limited_data_reason.');
  } else fitText(skills.limited_data_reason, 500, 'limited_data_reason');
  if (!Array.isArray(skills.requirements) || skills.requirements.length > 80) throw new Error('Invalid requirements list.');
  if (!skills.requirements.length) {
    if (skills.evidence_quality !== 'insufficient' || skills.skill_rating !== 1) throw new Error('No requirements requires insufficient evidence and rating 1.');
    return;
  }
  const seen = new Set();
  for (const [index, r] of skills.requirements.entries()) {
    fitExact(r, ['requirement','priority','explicitness','outcome','central','mandatory_credential','resume_evidence','resume_evidence_quotes','posting_evidence','hard_condition'], 'requirement');
    fitText(r.requirement, 300, 'requirement');
    fitText(r.resume_evidence, 800, 'resume_evidence');
    fitText(r.posting_evidence, 1500, 'posting_evidence');
    if (!fitNormalize(fitPostingText(envelope)).includes(fitNormalize(r.posting_evidence))) throw new Error(`requirement[${index}].posting_evidence: Requirement excerpt is not present in posting; copy one contiguous passage verbatim.`);
    fitEnum(r.priority, ['MUST','NICE'], 'priority');
    fitEnum(r.explicitness, ['EXPLICIT','IMPLICIT'], 'explicitness');
    fitEnum(r.outcome, ['DIRECT','TRANSFERABLE','GAP'], 'outcome');
    if (!Array.isArray(r.resume_evidence_quotes) || r.resume_evidence_quotes.length > 3 || (r.outcome !== 'GAP' && !r.resume_evidence_quotes.length)) throw new Error('Direct/transferable matches require bounded resume excerpts.');
    for (const quote of r.resume_evidence_quotes) {
      fitText(quote, 1500, 'resume_evidence_quotes');
      if (!fitNormalize(envelope.resume).includes(fitNormalize(quote))) throw new Error(`requirement[${index}].resume_evidence_quotes: Resume excerpt is not present in the supplied resume; copy a short contiguous passage verbatim.`);
    }
    fitEnum(r.hard_condition, ['none','credential','license','clearance','strict_experience_minimum'], 'hard_condition');
    if (typeof r.central !== 'boolean' || typeof r.mandatory_credential !== 'boolean') throw new Error('Invalid requirement booleans.');
    if ((r.central || r.mandatory_credential || r.hard_condition !== 'none') && r.priority !== 'MUST') throw new Error('Central/hard conditions must be MUST.');
    if (r.hard_condition !== 'none' && (r.explicitness !== 'EXPLICIT' || r.outcome === 'TRANSFERABLE')) throw new Error('Hard conditions must be explicit and cannot be transferable.');
    if (r.mandatory_credential !== ['credential','license','clearance'].includes(r.hard_condition)) throw new Error('Credential and hard-condition fields disagree.');
    const key = fitNormalize(r.requirement).toLowerCase();
    if (seen.has(key)) throw new Error('Duplicate requirement.');
    seen.add(key);
  }
  const expected = fitSkillRating(skills.requirements);
  if (skills.skill_rating !== expected) throw new Error(`Skill rating must be ${expected} from coverage and caps.`);
}
function fitSkillRating(requirements) {
  if (!Array.isArray(requirements) || requirements.length > 80 || requirements.some(r => !fitObject(r))) throw new Error('Invalid requirements list.');
  if (!requirements.length) return 1;
  const total = requirements.reduce((sum, r) => sum + (r.priority === 'MUST' ? 2 : 1), 0);
  const earned = requirements.reduce((sum, r) => sum + (r.priority === 'MUST' ? 2 : 1) * (r.outcome === 'DIRECT' ? 1 : r.outcome === 'TRANSFERABLE' ? .5 : 0), 0);
  const coverage = earned / total;
  const baseline = coverage >= .8 ? 5 : coverage >= .6 ? 4 : coverage >= .4 ? 3 : coverage >= .2 ? 2 : 1;
  const gaps = requirements.filter(r => r.central && r.outcome === 'GAP').length;
  const credentialGap = requirements.some(r => r.mandatory_credential && r.outcome === 'GAP');
  return Math.min(baseline, credentialGap || gaps >= 2 ? 2 : gaps === 1 ? 3 : 5);
}
function fitBuildSkills(data, envelope) {
  fitExact(data, ['requirements','limited_data_reason','evidence_quality'], 'skill model output');
  const skills = {...data, skill_rating:fitSkillRating(data.requirements)};
  fitValidateSkills(skills, envelope);
  return skills;
}
function fitSelection(envelope, dimensions) {
  const p = fitReadPolicy(envelope), pref = envelope.results?.preferences, skills = envelope.results?.skills;
  if (!pref || !skills) throw new Error('Missing validated preference/skill results.');
  const eligibility = fitValidateFacts(pref, envelope);
  fitValidateSkills({requirements: skills.requirements, limited_data_reason: skills.limited_data_reason, skill_rating: skills.skill_rating, evidence_quality: skills.evidence_quality}, envelope);
  const reasons = [...eligibility.reasons], holds = [...eligibility.holds];
  if (skills.evidence_quality !== 'sufficient') holds.push('qualification_evidence_incomplete');
  if (skills.evidence_quality === 'sufficient' && skills.skill_rating < p.minimum_skill_rating) reasons.push('skill_floor');
  if (skills.evidence_quality === 'sufficient' && skills.requirements.some(r => r.hard_condition !== 'none' && r.outcome === 'GAP')) reasons.push('mandatory_qualification_unmet');
  const compensation = fitCompensation(pref, p);
  if (compensation.below_target) reasons.push('salary_below_target');
  if (pref.availability.status === 'closed') reasons.push('posting_closed');
  const included = FIT_DIMENSIONS.filter(key => dimensions[key] !== null);
  const weightTotal = included.reduce((sum, key) => sum + FIT_WEIGHTS[key], 0);
  const score = weightTotal ? Math.round(included.reduce((sum, key) => sum + dimensions[key] * FIT_WEIGHTS[key], 0) / weightTotal * 10) / 10 : 0;
  if (!reasons.length && !holds.length && score < p.score_threshold) reasons.push('ranking_threshold');
  const state = reasons.length ? 'rejected' : holds.length ? 'held' : 'selected';
  return {state, determination: state === 'selected' ? 'yes' : 'no', score, reason_codes: reasons, review_codes: holds, compensation, included, excluded: FIT_DIMENSIONS.filter(key => dimensions[key] === null), weights_used: Object.fromEntries(included.map(key => [key, FIT_WEIGHTS[key] / weightTotal]))};
}
function fitValidateOverall(data, envelope) {
  fitExact(data, ['determination',...FIT_DIMENSIONS,'explanation'], 'overall');
  fitEnum(data.determination, ['yes','no'], 'determination');
  fitText(data.explanation, 280, 'explanation');
  if (/[\r\n]/.test(data.explanation)) throw new Error('Explanation must be a single line.');
  for (const key of FIT_DIMENSIONS) if (data[key] !== null) fitNumber(data[key], 1, 5, key, true);
  if (data.skills_alignment !== envelope.results?.skills?.skill_rating) throw new Error('Skills alignment must copy validated skill rating.');
  const pref = envelope.results.preferences, p = fitReadPolicy(envelope);
  const eligibility = fitValidateFacts(pref, envelope);
  if (eligibility.state !== 'confirmed' && data.remote_work_flexibility !== null) throw new Error('Unconfirmed eligibility requires null remote rating.');
  if (eligibility.state === 'confirmed' && ![3,4,5].includes(data.remote_work_flexibility)) throw new Error('Confirmed eligibility requires remote rating 3-5.');
  if (data.salary_competitiveness !== fitCompensation(pref, p).rating) throw new Error('Salary rating disagrees with comparable published pay.');
  const entries = [...pref.preference_matches,...pref.preference_misses];
  if (data.employee_satisfaction !== null && !entries.some(x => x.startsWith('[SATISFACTION]')) && !pref.red_flags.some(x => x.category === 'satisfaction')) throw new Error('Unsupported employee-satisfaction score.');
  if (data.cultural_fit !== null && !entries.some(x => /^\[(DOMAIN|DREAM_ROLE|COLLABORATION|GROWTH|CULTURE)\]/.test(x))) throw new Error('Unsupported cultural/work-content score.');
  const selection = fitSelection(envelope, data);
  if (data.determination !== selection.determination) throw new Error(`Overall determination must be ${selection.determination}.`);
  return selection;
}

function fitOverallContext(envelope) {
  const pref = envelope.results?.preferences, skills = envelope.results?.skills;
  if (!pref || !skills) throw new Error('Missing validated preference/skill results.');
  const eligibility = fitValidateFacts(pref, envelope);
  fitValidateSkills({requirements:skills.requirements, limited_data_reason:skills.limited_data_reason, skill_rating:skills.skill_rating, evidence_quality:skills.evidence_quality}, envelope);
  if (![pref.preference_matches,pref.preference_misses,pref.red_flags].every(Array.isArray) || [...pref.preference_matches,...pref.preference_misses].some(x => typeof x !== 'string') || pref.red_flags.some(x => !fitObject(x))) throw new Error('Invalid validated preference evidence.');
  const entries = [...pref.preference_matches,...pref.preference_misses];
  const selection = fitSelection(envelope, {employee_satisfaction:null,salary_competitiveness:null,remote_work_flexibility:null,skills_alignment:skills.skill_rating,cultural_fit:null});
  // Ranking is not known until the subjective dimensions are supplied.
  return {eligibility_state:eligibility.state, reason_codes:selection.reason_codes.filter(x => x !== 'ranking_threshold'), review_codes:selection.review_codes,
    salary_competitiveness:selection.compensation.rating, skills_alignment:skills.skill_rating,
    employee_satisfaction_supported:entries.some(x => x.startsWith('[SATISFACTION]')) || pref.red_flags.some(x => x.category === 'satisfaction'),
    cultural_fit_supported:entries.some(x => /^\[(DOMAIN|DREAM_ROLE|COLLABORATION|GROWTH|CULTURE)\]/.test(x))};
}
function fitBuildOverall(data, envelope) {
  const subjective = ['employee_satisfaction','remote_work_flexibility','cultural_fit'];
  fitExact(data, subjective, 'overall model output');
  for (const key of subjective) if (data[key] !== null) fitNumber(data[key], 1, 5, key, true);
  const context = fitOverallContext(envelope);
  const result = {determination:'no', employee_satisfaction:context.employee_satisfaction_supported ? data.employee_satisfaction : null,
    salary_competitiveness:context.salary_competitiveness,
    remote_work_flexibility:context.eligibility_state === 'confirmed' ? data.remote_work_flexibility : null,
    skills_alignment:context.skills_alignment, cultural_fit:context.cultural_fit_supported ? data.cultural_fit : null, explanation:''};
  const selection = fitSelection(envelope, result);
  result.determination = selection.determination;
  const descriptions = {work_arrangement_mismatch:'required work arrangement not met',work_arrangement_failed:'work arrangement failed',work_location_ineligible:'work location ineligible',travel_exceeds_limit:'mandatory travel exceeds cap',skill_floor:'skills below required floor',mandatory_qualification_unmet:'mandatory qualification not evidenced',salary_below_target:'published comparable pay below target',posting_closed:'posting explicitly closed',ranking_threshold:'fit score below threshold',work_arrangement_unverified:'work arrangement unverified',work_location_unverified:'work location unverified',travel_necessity_unverified:'travel necessity unverified',travel_frequency_unverified:'travel frequency unverified',qualification_evidence_incomplete:'qualification evidence incomplete'};
  const conditions = selection.state === 'rejected' ? selection.reason_codes : selection.review_codes;
  const lead = selection.state === 'selected' ? `Eligible; skills ${result.skills_alignment}/5 meet floor` :
    `${selection.state === 'held' ? 'Verify' : 'Not selected'}: ${conditions.slice(0,2).map(x => descriptions[x]).join('; ')}`;
  const pay = selection.compensation.below_target ? 'Pay below target' : result.salary_competitiveness === null ? 'Pay unknown/noncomparable' : 'Published pay reaches target; offer not guaranteed';
  result.explanation = `${lead} • ${pay} • Fit ${selection.score}/5`;
  fitValidateOverall(result, envelope);
  return result;
}

// Node.js test interface; omitted when embedded in n8n Code nodes.
module.exports = { fitNormalizeResearch,FIT_DIMENSIONS, FIT_WEIGHTS, fitReadPolicy, fitValidateFacts, fitValidateSkills, fitSkillRating, fitBuildSkills, fitEligibility, fitCompensation, fitNormalizeCompensation, fitSelection, fitValidateOverall, fitOverallContext, fitBuildOverall};
