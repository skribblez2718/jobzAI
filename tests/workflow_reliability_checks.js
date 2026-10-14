'use strict';

// Executable regression fixtures, not live-provider or n8n-runtime verification.
module.exports = function reliabilityChecks(t) {
  const {assert,check,policy,fixture,quote,pay,rawOverall,rawPreferences,rawSkills,flows,find,main,run,shared} = t;
  const flowFor = stage => flows[`Job Searcher - ${stage} Analysis.json`];
  const validate = (stage, data, e) => run(find(flowFor(stage),`Validate ${stage} Analysis`).parameters.jsCode,data,e);
  const addRange = (e, minimum, maximum, scope = 'US') => {
    const text = `Additional annual USD base statement for ${scope}: ${minimum} to ${maximum}.`;
    e.job.content += ` ${text}`;
    const reference = e.results.preferences.compensation.ranges[0];
    e.results.preferences.compensation.ranges.push({...reference,minimum,maximum,location_scope:scope,evidence:quote(text)});
  };

  check('matching lower-bound statement corroborates full range', () => {
    const e=fixture();pay(e,150000,200000);addRange(e,150000,null);
    policy.fitValidateFacts(e.results.preferences,e);
    assert.equal(policy.fitCompensation(e.results.preferences,e.policy).rating,5);
    assert.equal(policy.fitNormalizeCompensation(e.results.preferences.compensation,e.policy).status,'known');
  });
  check('matching upper bound corroborates full range in either order', () => {
    const e=fixture();pay(e,100000,200000);addRange(e,null,200000,' us ');
    e.results.preferences.compensation.ranges.reverse();
    assert.deepEqual(policy.fitCompensation(e.results.preferences,e.policy),{rating:4,maximum:200000,below_target:false});
  });
  check('corroborating evidence cannot erase a below-target ceiling', () => {
    const e=fixture();pay(e,100000,120000);addRange(e,100000,null);
    assert.equal(policy.fitBuildOverall(rawOverall(e),e).determination,'no');
    assert.equal(policy.fitCompensation(e.results.preferences,e.policy).below_target,true);
  });
  check('duplicate ranges remain comparable', () => {
    const e=fixture();pay(e,150000,200000);addRange(e,150000,200000);
    assert.equal(policy.fitCompensation(e.results.preferences,e.policy).rating,5);
  });
  for (const [name,min,max,scope] of [
    ['different overlapping full ranges',120000,220000,'US'],
    ['different disjoint full ranges',210000,250000,'US'],
    ['nonmatching partial bound',110000,null,'US'],
    ['partial evidence from another geography',100000,null,'New York'],
  ]) check(`${name} remain conflicting and nonblocking`, () => {
    const e=fixture();pay(e,100000,200000);addRange(e,min,max,scope);
    const result=validate('Preference',rawPreferences(e),e);
    assert.equal(result.compensation.status,'conflicting');
    assert(result.potential_preference_matches.some(x=>x.startsWith('[SALARY] Limited data available:')));
    assert(![...result.preference_matches,...result.preference_misses].some(x=>x.startsWith('[SALARY]')));
    assert.match(result.salary,/Conflicting/);
    e.results.preferences=result;
    assert.equal(policy.fitCompensation(result,e.policy).rating,null);
    assert.equal(policy.fitBuildOverall(rawOverall(e),e).determination,'yes');
  });
  check('two one-sided statements are not speculatively joined', () => {
    const e=fixture();pay(e,150000,null);addRange(e,null,200000);
    assert.equal(policy.fitNormalizeCompensation(e.results.preferences.compensation,e.policy).status,'conflicting');
  });
  check('another region higher pay cannot rescue applicable low ceiling', () => {
    const e=fixture();pay(e,100000,120000);addRange(e,200000,250000,'Elsewhere');
    e.results.preferences.compensation.ranges[1].applicability='not_applicable';
    const result=policy.fitBuildOverall(rawOverall(e),e);
    assert.equal(result.salary_competitiveness,1);
    assert.equal(result.determination,'no');
  });
  check('conflict handling cannot bypass exact source verification', () => {
    const e=fixture();pay(e,100000,200000);addRange(e,110000,220000);
    e.results.preferences.compensation.ranges[1].evidence[0].quote='Invented salary statement.';
    assert.throws(()=>validate('Preference',rawPreferences(e),e),/compensation.evidence\[0\].*excerpt/);
  });
  check('unverified and conflicting statuses are never upgraded', () => {
    const e=fixture();pay(e,100000,120000);
    for(const status of ['unverified','conflicting']) {
      e.results.preferences.compensation.status=status;
      assert.equal(policy.fitNormalizeCompensation(e.results.preferences.compensation,e.policy).status,status);
      assert.equal(policy.fitBuildOverall(rawOverall(e),e).salary_competitiveness,null);
    }
  });
  check('raw skill output contains no model arithmetic', () => {
    const e=fixture();const result=validate('Skill',rawSkills(e),e);
    assert.equal(result.skill_rating,4);
    assert.deepEqual(result.requirements,e.results.skills.requirements);
    assert.throws(()=>validate('Skill',{...rawSkills(e),skill_rating:5},e),/invalid fields/);
  });
  check('derived skill rating retains central and credential caps', () => {
    const e=fixture();e.results.skills.requirements[3].central=true;
    assert.equal(validate('Skill',rawSkills(e),e).skill_rating,3);
    e.job.content+=' Required credential Z.';
    e.results.skills.requirements[3].posting_evidence='Required credential Z.';
    e.results.skills.requirements[3].hard_condition='credential';
    e.results.skills.requirements[3].mandatory_credential=true;
    assert.equal(validate('Skill',rawSkills(e),e).skill_rating,2);
  });
  check('raw skill builder still rejects fabricated posting and resume quotes', () => {
    for(const field of ['posting_evidence','resume_evidence_quotes']) {
      const e=fixture();e.results.skills.requirements[0][field]=field==='posting_evidence'?'Invented competency.':['Invented competency.'];
      assert.throws(()=>validate('Skill',rawSkills(e),e),/excerpt/);
    }
  });
  check('preference grade is derived, not accepted from a model', () => {
    const e=fixture();assert.equal(validate('Preference',rawPreferences(e),e).preferences_rating,2);
    assert.throws(()=>validate('Preference',e.results.preferences,e),/Unexpected keys: preferences_rating/);
  });
  check('interest evidence survives unresolved eligibility without overriding hold', () => {
    const e=fixture();e.results.preferences.eligibility.location_status='unverified';
    e.results.preferences.preference_matches.shift();
    e.results.preferences.potential_preference_matches.push('[ELIGIBILITY] Unverified: Candidate jurisdiction not established.');
    const pref=validate('Preference',rawPreferences(e),e);
    assert.equal(pref.preferences_rating,0);
    assert(pref.preference_matches.some(x=>x.startsWith('[DOMAIN]')));
    e.results.preferences=pref;
    const result=validate('Overall',rawOverall(e),e);
    assert.equal(result.determination,'no');
    assert.equal(result.remote_work_flexibility,null);
    assert.equal(result.cultural_fit,4);
    assert.match(result.explanation,/^Verify: work location unverified/);
  });
  check('unsupported optional scores are excluded rather than invented or blocking', () => {
    const e=fixture();e.results.preferences.preference_matches=e.results.preferences.preference_matches.slice(0,1);
    e.results.preferences.potential_preference_matches.push('[DOMAIN] Limited data available: Possible interest.');
    const result=validate('Overall',{employee_satisfaction:5,remote_work_flexibility:5,cultural_fit:5},e);
    assert.equal(result.employee_satisfaction,null);
    assert.equal(result.cultural_fit,null);
    assert.equal(result.determination,'yes');
    assert.equal(policy.fitOverallContext(e).cultural_fit_supported,false);
  });
  check('satisfaction needs its own accepted evidence, not general health', () => {
    const e=fixture();e.results.preferences.preference_matches.push('[HEALTH] Posting: Employer reports growth.');
    const data={...rawOverall(e),employee_satisfaction:4};
    assert.equal(validate('Overall',data,e).employee_satisfaction,null);
    e.results.preferences.preference_matches.push('[SATISFACTION] Supplied employee account describes positive conditions.');
    assert.equal(validate('Overall',data,e).employee_satisfaction,4);
  });
  check('overall salary, skills, determination and explanation are code-owned', () => {
    const e=fixture();pay(e,100000,120000);
    const result=validate('Overall',rawOverall(e),e);
    assert.equal(result.salary_competitiveness,1);
    assert.equal(result.skills_alignment,4);
    assert.equal(result.determination,'no');
    assert.match(result.explanation,/^Not selected: published comparable pay below target/);
    for(const [key,value] of [['salary_competitiveness',5],['skills_alignment',5],['determination','yes'],['explanation','Apply now.']]) {
      assert.throws(()=>validate('Overall',{...rawOverall(e),[key]:value},e),/invalid fields/);
    }
    assert.deepEqual(Object.keys(result).sort(),['determination',...policy.FIT_DIMENSIONS,'explanation'].sort());
  });
  check('derived decision cannot ignore a known strict qualification gap', () => {
    const e=fixture();e.results.skills.requirements[3].hard_condition='strict_experience_minimum';
    const result=validate('Overall',rawOverall(e),e);
    assert.equal(result.determination,'no');
    assert.match(result.explanation,/mandatory qualification not evidenced/);
  });
  check('malformed subjective values cannot hide behind missing evidence', () => {
    const e=fixture();
    for(const value of ['5',0,6,NaN,{},undefined]) assert.throws(()=>validate('Overall',{...rawOverall(e),employee_satisfaction:value},e),/invalid number/);
    for(const value of [null,1,2]) assert.throws(()=>validate('Overall',{...rawOverall(e),remote_work_flexibility:value},e),/remote rating 3-5/);
  });
  check('overall builder never repairs tampered validated skill facts', () => {
    const e=fixture();e.results.skills.skill_rating=5;
    assert.throws(()=>validate('Overall',rawOverall(e),e),/Skill rating must be 4/);
  });
  check('code-owned overall context is embedded consistently', () => {
    const e=fixture();const code=find(flowFor('Overall'),'Prepare Overall Context').parameters.jsCode;
    assert(code.startsWith(shared));
    assert.deepEqual(run(code,e,e).overall_context,policy.fitOverallContext(e));
    const repair=find(flowFor('Overall'),'Prepare Overall Correction');
    assert(repair.parameters.jsCode.startsWith(shared));
  });
  check('parser contracts contain only model-owned fields', () => {
    for(const [stage,count,forbidden] of [['Preference',14,['preferences_rating']],['Skill',3,['skill_rating']],['Overall',3,['determination','skills_alignment','salary_competitiveness','explanation']]]) {
      const schema=JSON.parse(find(flowFor(stage),`${stage} Structured Output Parser`).parameters.inputSchema);
      assert.equal(schema.required.length,count);
      assert.equal(Object.keys(schema.properties).length,count);
      for(const field of forbidden) assert(!schema.required.includes(field));
      assert.equal(schema.additionalProperties,false);
    }
  });

  // Walk the exported main-output graph with actual local Code nodes. Model/parser
  // results are deliberately mocked; this does not claim real n8n execution.
  function executeChild(stage,envelope,responses) {
    const flow=flowFor(stage), counts={}, contexts=[], outputs={};
    let current='When Executed by Another Workflow', input=envelope, attempts=0;
    for(let steps=0;steps<30;steps++) {
      const node=find(flow,current);assert(node,`Missing node ${current}`);
      const index=counts[current] || 0;counts[current]=index+1;
      let output=0;
      try {
        if(current===`${stage} Analysis Chain`) {
          contexts.push(input.repair_context || null);
          const response=responses[attempts++];
          assert.notEqual(response,undefined,'Unexpected extra chain attempt');
          if(response instanceof Error) throw response;
          input={output:structuredClone(response)};
        } else if(node.parameters.jsCode) input=run(node.parameters.jsCode,input,envelope,outputs,index);
      } catch(error) {
        if(node.onError!=='continueErrorOutput') throw error;
        input={error:{message:error.message}};output=1;
      }
      outputs[current]=input;
      const next=flow.connections[current]?.main?.[output] || [];
      if(!next.length) return {result:input,attempts,contexts,counts};
      assert.equal(next.length,1,'Ambiguous executable path');
      current=next[0].node;
    }
    throw new Error('Unbounded child workflow graph');
  }
  for(const stage of ['Preference','Skill','Overall']) {
    const raw=e=>stage==='Preference'?rawPreferences(e):stage==='Skill'?rawSkills(e):rawOverall(e);
    check(`${stage} success needs no correction`, () => {
      const e=fixture();const result=executeChild(stage,e,[raw(e)]);
      assert.equal(result.attempts,1);
      assert.equal(result.contexts[0],null);
      assert(result.result.results[stage==='Preference'?'preferences':stage==='Skill'?'skills':'overall']);
    });
    check(`${stage} simulated parser error gets one feedback-aware correction`, () => {
      const e=fixture();const result=executeChild(stage,e,[new Error('Model output does not fit required format.'),raw(e)]);
      assert.equal(result.attempts,2);
      assert.match(result.contexts[1].validation_error,/required format/);
      assert.equal(result.contexts[1].attempt,2);
    });
    check(`${stage} repeated invalid output exhausts without attachment`, () => {
      const e=fixture();assert.throws(()=>executeChild(stage,e,[{},{}]),/Correction exhausted/);
    });
    check(`${stage} graph and parent cannot blindly repeat a whole child`, () => {
      const flow=flowFor(stage),repair=`Prepare ${stage} Correction`;
      for(const name of [`${stage} Analysis Chain`,`Validate ${stage} Analysis`]) {
        assert.equal(find(flow,name).onError,'continueErrorOutput');
        assert.equal(find(flow,name).retryOnFail,false);
        assert.equal(flow.connections[name].main[1][0].node,repair);
      }
      assert.equal(flow.connections[repair].main[0][0].node,`${stage} Analysis Chain`);
      assert.equal(find(main,`Execute ${stage} Analysis`).retryOnFail,false);
      assert(find(flow,`${stage} Analysis Chain`).parameters.text.includes('$json.repair_context'));
      assert.equal(find(flow,repair).onError,'stopWorkflow');
      assert.throws(()=>run(find(flow,repair).parameters.jsCode,{error:'Still invalid',repair_context:{attempt:0}},fixture(),{},1),/Correction exhausted/);
    });
  }
  check('preference evidence failure feeds field-specific correction context', () => {
    const e=fixture(),bad=structuredClone(rawPreferences(e));
    bad.eligibility.evidence[0].quote='Invented eligibility quote.';
    const result=executeChild('Preference',e,[bad,rawPreferences(e)]);
    assert.equal(result.attempts,2);
    assert.match(result.contexts[1].validation_error,/eligibility.evidence\[0\].*excerpt/);
    assert(!result.contexts[1].validation_error.includes('Invented eligibility quote.'));
    assert(result.contexts[1].previous_output_excerpt.includes('Invented eligibility quote.'));
    assert.equal(result.result.results.preferences.preferences_rating,2);
  });
  check('skill posting quote failure feeds field-specific correction context', () => {
    const e=fixture(),bad=structuredClone(rawSkills(e));
    bad.requirements[0].posting_evidence='Invented requirement quote.';
    const result=executeChild('Skill',e,[bad,rawSkills(e)]);
    assert.equal(result.attempts,2);
    assert.match(result.contexts[1].validation_error,/requirement\[0\].posting_evidence/);
    assert(result.contexts[1].previous_output_excerpt.includes('Invented requirement quote.'));
    assert.equal(result.result.results.skills.skill_rating,4);
  });
  check('parent failure handlers preserve nested messages without object coercion', () => {
    const e=fixture();
    for(const stage of ['Preference','Skill','Overall']) {
      const code=find(main,`Handle ${stage} Analysis Failure`).parameters.jsCode;
      const result=run(code,{error:{message:'Correction exhausted',cause:{message:'Bad excerpt'}}},e);
      assert.match(result.diagnostic_error,/Correction exhausted.*Bad excerpt/);
      assert(!result.diagnostic_error.includes('[object Object]'));
      assert.equal(result.outcome_status,'failed');
      assert(!result.failure_summary.includes('3 attempts'));
      assert(!code.includes('console.error('));
    }
  });
  check('previous answers are bounded and unavailable parser output is not replaced by source data', () => {
    const e=fixture(),node=find(flowFor('Preference'),'Prepare Preference Correction');
    const available=run(node.parameters.jsCode,{error:'Bad prior answer'},e,{'Preference Analysis Chain':{output:{notes:'x'.repeat(9000)}}});
    assert.equal(available.repair_context.previous_output_excerpt.length,8000);
    assert.equal(available.repair_context.previous_output_may_be_truncated,true);
    const unavailable=run(node.parameters.jsCode,{error:'Parser failure'},e);
    assert.equal(unavailable.repair_context.previous_output_excerpt,null);
    assert(!JSON.stringify(unavailable.repair_context).includes(e.resume));
  });
  check('correction and diagnostic payloads are bounded and redact common credential forms', () => {
    const e=fixture(),secret='sk-'+'x'.repeat(24);
    const input={error:{message:'Authorization: Bearer '+secret+' '+ 'x'.repeat(10000)}};
    const node=find(flowFor('Preference'),'Prepare Preference Correction');
    const result=run(node.parameters.jsCode,input,e);
    assert(result.repair_context.validation_error.length<=1600);
    assert(!JSON.stringify(result.repair_context).includes(secret));
    const final=run(find(main,'Handle Preference Analysis Failure').parameters.jsCode,input,e);
    assert(final.diagnostic_error.length<=1600);
    assert(!final.diagnostic_error.includes(secret));
  });
};
