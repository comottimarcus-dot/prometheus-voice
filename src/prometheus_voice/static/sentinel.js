const button = document.getElementById('sentinel-refresh');
const status = document.getElementById('sentinel-status');
const results = document.getElementById('sentinel-results');
const airButton = document.getElementById('sentinel-air-refresh');
let busy = false;
export async function readSentinel({ signal } = {}) {
  if (busy || signal?.aborted) throw new Error('Sentinel unavailable');
  busy = true; button.disabled = true; results.replaceChildren();
  status.textContent = 'Reading Sentinel through X6…';
  try {
    const response = await fetch('/api/x6/sentinel', { cache: 'no-store', redirect: 'error',
      signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(8000)]) : AbortSignal.timeout(8000) });
    const data = await response.json();
    if (!response.ok) throw new Error('Unavailable');
    const line = document.createElement('p');
    const motion = data.motion === 'waiting'
      ? 'Sentinel is waiting for a second distinct weather sample before it can assess movement.'
      : data.motion === 'no_echo' ? 'There is insufficient precipitation echo to calculate movement.'
      : data.motion === 'stationary' ? 'The precipitation pattern shows no significant centroid movement between the samples.'
      : `The precipitation pattern has an apparent bearing of ${data.bearing_deg} degrees.`;
    const spoken_summary = `${data.echoes} of ${data.cells} grid cells report precipitation, with a maximum of ${data.max_precipitation_mm} millimeters. ${motion}`;
    line.textContent = spoken_summary;
    results.append(line);
    status.textContent = `Source time: ${data.source_updated_at}. Open-Meteo data processed by Sentinel NM0. LAN telemetry; identity not authenticated.`;
    return { ...data, status: 'READ', spoken_summary, independently_verified: false };
  } catch {
    results.replaceChildren();
    status.textContent = 'Sentinel telemetry is unavailable or outdated. No weather conclusion is available.';
    throw new Error('Sentinel unavailable');
  } finally { busy = false; button.disabled = false; }
}
button.addEventListener('click', () => { readSentinel().catch(() => {}); });

export async function readSentinelAir({ signal } = {}) {
  if (busy || signal?.aborted) throw new Error('Sentinel AIR unavailable');
  busy = true; airButton.disabled = true; results.replaceChildren();
  status.textContent = 'Reading Sentinel AIR through X6…';
  try {
    const response = await fetch('/api/x6/sentinel-air', { cache: 'no-store', redirect: 'error',
      signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(8000)]) : AbortSignal.timeout(8000) });
    const data = await response.json();
    if (!response.ok) throw new Error('Unavailable');
    const spoken_summary = `Sentinel is displaying ${data.targets} aircraft targets within 25 nautical miles of its configured center in São Paulo.${data.limit_reached ? ' The display limit of 40 has been reached, so more aircraft may be present.' : ''} This is a filtered ADS-B display count.`;
    const line = document.createElement('p'); line.textContent = spoken_summary; results.append(line);
    status.textContent = `Feed fetched about ${Math.ceil(data.fetch_age_seconds)} seconds ago. Aircraft observation times are not checked. LAN telemetry; identity not authenticated.`;
    return { ...data, status: 'READ', spoken_summary, independently_verified: false };
  } catch {
    results.replaceChildren();
    status.textContent = 'Sentinel AIR is unavailable or outdated. No aircraft count is available.';
    throw new Error('Sentinel AIR unavailable');
  } finally { busy = false; airButton.disabled = false; }
}
airButton.addEventListener('click', () => { readSentinelAir().catch(() => {}); });
