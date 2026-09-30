const get = id => document.getElementById(id);
const form = get('governed-form'), run = get('execute-plan');
const message = get('governed-message'), details = get('plan-details'), output = get('execution-result');
let planId = null, busy = false, expiryTimer = null;
let voicePending = null;
function progress(text) { get('action-progress').textContent = text; }

export function requestVoiceCalculation(parameters, { signal }) {
  if (busy || voicePending || signal.aborted) return Promise.reject(new Error('Review unavailable'));
  invalidate(); details.replaceChildren(); output.replaceChildren();
  get('operand-a').value = String(parameters.a);
  get('operand-b').value = String(parameters.b);
  get('operator').value = parameters.operator;
  message.textContent = 'Voice proposal: verify or correct these numbers, click Review plan, then Execute local calculation. Nothing has executed yet. Review expires in 45 seconds.';
  progress('1 / 3 · Review your spoken numbers');
  form.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
  return new Promise((resolve, reject) => {
    const cancel = () => {
      invalidate();
      progress(voicePending?.submitted ? 'Outcome unconfirmed · Check the result below' : 'Review ended · Nothing submitted');
      message.textContent = 'Voice review cancelled or timed out. Any calculation already submitted may still complete; inspect its outcome below.';
      if (signal.aborted) finishVoice(null, true);
      else finishVoice({ status: voicePending?.submitted ? 'UNKNOWN' : 'NOT_EXECUTED',
        reason_code: voicePending?.submitted ? 'OUTCOME_NOT_CONFIRMED' : 'REVIEW_EXPIRED',
        instruction: 'Explain the review or delivery timeout accurately. Do not claim that arithmetic failed or repeat the action.' });
    };
    voicePending = { resolve, reject, cancel, signal, timer: setTimeout(cancel, 45000), parameters: null, submitted: false };
    signal.addEventListener('abort', cancel, { once: true });
    lock(false);
  });
}

function finishVoice(result, failed = false) {
  if (!voicePending) return;
  const pending = voicePending; voicePending = null;
  clearTimeout(pending.timer);
  pending.signal.removeEventListener('abort', pending.cancel);
  if (failed) pending.reject(new Error('No confirmed voice execution'));
  else pending.resolve(result);
  lock(busy);
}

async function post(path, payload) {
  const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload), cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(10000) });
  const result = await response.json();
  if (!response.ok) throw new Error('Request could not be completed. Review a fresh plan and try again.');
  return result;
}
function row(label, value) {
  const line = document.createElement('p');
  const title = document.createElement('strong'); title.textContent = `${label}: `;
  line.append(title, document.createTextNode(String(value))); return line;
}
function lock(value) {
  busy = value;
  form.querySelectorAll('button, input, select').forEach(item => { item.disabled = value; });
  get('preview-confirm').disabled = value || !!voicePending; get('preview-deny').disabled = value || !!voicePending;
}
function invalidate() {
  planId = null; run.disabled = true; clearTimeout(expiryTimer);
}
form.addEventListener('input', () => {
  invalidate(); progress('1 / 3 · Numbers changed — review again'); message.textContent = 'Inputs changed. Review a new plan before execution.';
});
async function prepare(operation, parameters) {
  if (busy) return;
  const reviewing = voicePending;
  invalidate(); lock(true); details.replaceChildren(); output.replaceChildren();
  progress('1 / 3 · Checking policy and executor');
  message.textContent = 'Evaluating policy and selecting an executor…';
  try {
    const data = await post('/api/governed/plan', { operation, parameters });
    if (reviewing && reviewing !== voicePending) return;
    const plan = data.plan, policy = plan.selection.policy;
    details.append(row('Objective', plan.objective), row('Policy', `${policy.decision} · ${policy.risk} risk`),
      row('Reason', policy.explanation), row('Plan', plan.status),
      row('Executor', plan.selection.proposed_executor_id || 'None'),
      row('Mode', plan.steps[0]?.mode || 'No execution proposed'));
    for (const candidate of plan.selection.assessments) {
      details.append(row(candidate.executor_id, `${candidate.mode} · ${candidate.reasons.join(', ')}`));
    }
    if (plan.steps[0]) details.append(row('Success criteria', plan.steps[0].success_criteria.join(', ')));
    if (data.can_execute) {
      if (reviewing) reviewing.parameters = { ...parameters };
      planId = data.plan_id; run.disabled = false;
      progress('2 / 3 · Plan ready — you choose when to execute');
      message.textContent = 'Plan ready. Review the details, then execute within 30 seconds.';
      expiryTimer = setTimeout(() => {
        invalidate(); if (!busy) { progress('1 / 3 · Plan expired — review again'); message.textContent = 'Plan expired. Review a new plan.'; }
      }, Math.max(0, Date.parse(plan.expires_at) - Date.now()));
    } else {
      progress(policy.decision === 'CONFIRM' ? 'Preview only · Confirmation required' : 'Blocked · No execution permitted');
      message.textContent = policy.decision === 'CONFIRM'
        ? 'Human confirmation is required. This simulation is preview-only; approval and simulated execution are not connected yet.'
        : 'No action will be executed for this plan.';
    }
  } catch (error) { progress('Plan unavailable · Review again'); message.textContent = error.message; }
  finally { lock(false); }
}
form.addEventListener('submit', event => {
  event.preventDefault();
  const a = Number(get('operand-a').value), b = Number(get('operand-b').value);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return;
  prepare('math.calculate', { operator: get('operator').value, a, b });
});
get('preview-confirm').addEventListener('click', () => prepare('demo.simulate', { scenario: 'executor_fallback' }));
get('preview-deny').addEventListener('click', () => prepare('system.delete', {}));
run.addEventListener('click', async () => {
  if (busy || !planId) return;
  const selected = planId;
  const reviewing = voicePending;
  invalidate(); lock(true); message.textContent = 'Revalidating, calculating, and recording evidence…';
  progress('3 / 3 · Running locally and checking evidence');
  if (reviewing) reviewing.submitted = true;
  try {
    const data = await post('/api/governed/execute', { plan_id: selected });
    progress(data.status === 'EXECUTED'
      ? (data.evidence.status === 'VERIFIED' ? 'Complete · Result ready, evidence verified' : 'Result ready · Evidence unverified')
      : 'Not executed · Inspect the outcome below');
    output.replaceChildren(row('Execution', data.status), row('Reason', data.reason_code),
      row('Result', data.value ?? 'No result'), row('Executor', data.executor || 'None'),
      row('Evidence', data.evidence.status), row('Trace', data.trace_id));
    if (data.evidence.status === 'VERIFIED') {
      output.append(row('Evidence record', data.evidence.sequence), row('Receipt hash', data.evidence.head_hash));
    }
    message.textContent = data.evidence.status === 'VERIFIED'
      ? 'Execution outcome recorded and evidence chain verified.'
      : 'Execution returned, but evidence could not be verified. Do not rerun to repair evidence.';
    if (reviewing && reviewing === voicePending) {
      finishVoice({ status: data.status, value: data.value, operands: reviewing.parameters,
        executor: data.executor, mode: data.mode, evidence: data.evidence.status });
    }
  } catch {
    progress('Outcome unconfirmed · Retrieve the existing result');
    message.textContent = 'No response received. The calculation may have completed. Retry retrieval uses the same plan and will not repeat execution.';
    planId = selected; run.disabled = false;
  } finally { lock(false); }
});
