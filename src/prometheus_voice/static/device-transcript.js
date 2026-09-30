const panel = document.getElementById('device-transcript');
const status = document.getElementById('device-transcript-status');
let previous = '';
async function refresh() {
  try {
    const response = await fetch('/api/device/transcript', {cache:'no-store', signal:AbortSignal.timeout(2500)});
    if (!response.ok) throw new Error('Unavailable');
    const data = await response.json();
    const encoded = JSON.stringify(data);
    if (encoded !== previous) {
      panel.replaceChildren(...data.rows.map(row => {
        const line = document.createElement('p');
        line.textContent = `${row.role === 'user' ? 'You (Zhengchen)' : 'Prometheus (Zhengchen)'}: ${row.text}`;
        return line;
      }));
      previous = encoded;
    }
    status.textContent = data.rows.length ? 'Recent device conversation · clears after 3 minutes without new text.' : 'Waiting for speech from Zhengchen. Activate the conversation on the device.';
  } catch {
    panel.replaceChildren(); previous = '';
    status.textContent = 'Device transcript connection unavailable.';
  } finally { setTimeout(refresh, 1000); }
}
refresh();
