const button = document.getElementById('x6-refresh');
const status = document.getElementById('x6-status');
const results = document.getElementById('x6-results');
let busy = false;
export async function readX6Capabilities({ signal } = {}) {
  if (busy || signal?.aborted) throw new Error('Query unavailable');
  busy = true;
  button.disabled = true;
  results.replaceChildren();
  status.textContent = 'Reading the X6 capability registry…';
  try {
    const response = await fetch('/api/x6/capabilities', {
      cache: 'no-store', redirect: 'error', signal: signal
        ? AbortSignal.any([signal, AbortSignal.timeout(8000)]) : AbortSignal.timeout(8000),
    });
    const data = await response.json();
    if (!response.ok) {
      status.textContent = data.error === 'X6_NOT_ENABLED'
        ? 'Core connection is not activated yet. No capabilities have been checked.'
        : 'X6 did not return a valid snapshot. Current capabilities are unknown.';
      throw new Error('Query unavailable');
    }
    for (const entry of data.capabilities) {
      const line = document.createElement('p');
      line.textContent = `${entry.name} · ${entry.registered_provider_count} registered provider(s) · availability unknown`;
      results.append(line);
    }
    status.textContent = `Registry read at ${new Date().toLocaleTimeString()}. ${data.capabilities.length} capabilities. Health not checked; no execution authorized.`;
    return { status: 'READ', capability_count: data.capabilities.length,
      registered_provider_count: data.capabilities.reduce((n, c) => n + c.registered_provider_count, 0),
      capability_names: data.capabilities.slice(0, 32).map(c => c.name),
      names_truncated: data.capabilities.length > 32,
      availability: 'unknown', health_checked: false, execution_authorized: false };
  } catch {
    results.replaceChildren();
    status.textContent = 'Query unavailable. Current capabilities are unknown.';
    throw new Error('Query unavailable');
  } finally { busy = false; button.disabled = false; }
}
button.addEventListener('click', () => { readX6Capabilities().catch(() => {}); });
