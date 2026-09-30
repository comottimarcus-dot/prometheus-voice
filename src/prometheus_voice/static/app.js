import { VoiceSession, TranscriptLog } from './voice-session.js';
import { VoiceAudio } from './voice-audio.js';
import { requestVoiceCalculation } from './governed.js';
import { readX6Capabilities } from './x6.js';
import { readShadowBroker } from './news.js';
import { requestCamera } from './camera.js';
import { readSentinel, readSentinelAir } from './sentinel.js';

const element = id => document.getElementById(id);
const health = element('health-status'), token = element('token-status');
const message = element('connection-message'), voice = element('voice-status');
const start = element('start-voice'), stop = element('stop-voice');
const validate = element('validate-token'), check = element('check-health');
const transcript = element('transcript');
const transcriptLog = new TranscriptLog();
let healthy = false, busy = false, generation = 0;
let healthBusy = false, validating = false;

function status(target, text, state = 'pending') {
  target.textContent = text; target.dataset.state = state;
}
function buttons() {
  start.disabled = !healthy || busy || healthBusy;
  validate.disabled = !healthy || busy || healthBusy;
  check.disabled = busy || healthBusy;
  stop.disabled = !busy;
}
async function request(path, signal) {
  const response = await fetch(path, { cache: 'no-store', credentials: 'omit',
    redirect: 'error', signal: signal || AbortSignal.timeout(25000) });
  if (!response.ok) throw new Error('Connection unavailable');
  return response.json();
}

const audio = new VoiceAudio({
  onFrame: data => session.sendAudio(data),
  onFailure: () => {
    session.stop(); audio.stop();
    message.textContent = 'Microphone stopped. Start a new session to try again.';
  },
});
const session = new VoiceSession({
  runTool: requestVoiceCalculation,
  readCapabilities: readX6Capabilities,
  readInformation: readShadowBroker,
  requestCamera,
  readSentinel,
  readSentinelAir,
  mintToken: async ({ signal }) => {
    const payload = await request('/api/voice-token', signal);
    const temporary = payload.token;
    delete payload.token;
    status(token, 'Issued for this session', 'ok');
    return temporary;
  },
  onState: ({ state, endConfirmed }) => {
    const labels = { connecting: 'Connecting…', ready: 'Listening · microphone on',
      ending: 'Ending…', ended: 'Ended · confirmed', cancelled: 'Cancelled', error: 'Session failed' };
    status(voice, labels[state] || state, state === 'ready' || state === 'ended' ? 'ok' : state === 'error' ? 'error' : 'pending');
    if (state === 'ready') message.textContent = 'Try: Calculate nineteen plus twenty-three. Review the proposed numbers in Governed action before executing. This voice session ends after 120 seconds.';
    if (['ending', 'ended', 'cancelled', 'error'].includes(state)) audio.stop();
    if (['ended', 'cancelled', 'error'].includes(state)) {
      busy = false;
      message.textContent = state === 'cancelled' ? 'Cancelled. Microphone off.'
        : endConfirmed ? 'Session ended by the server. Microphone off.'
        : 'Connection lost or timed out. Microphone off; server teardown was not confirmed.';
      buttons();
    }
  },
  onEvent: event => {
    if (event.type === 'tool_status') {
      const labels = { REVIEW_PENDING: 'Waiting for your review', RESULT_PENDING: 'Outcome ready; waiting for the agent',
        CAMERA_PENDING: 'Waiting for camera review and detection', CAMERA_SENT: 'Object predictions sent to the voice agent',
        QUERY_PENDING: 'Reading the X6 registry', QUERY_SENT: 'Registry snapshot sent to the voice agent',
        NEWS_PENDING: 'Reading ShadowBroker', NEWS_SENT: 'ShadowBroker headlines sent to the voice agent',
        SENTINEL_PENDING: 'Reading Sentinel', SENTINEL_SENT: 'Sentinel telemetry sent to the voice agent',
        RESULT_SENT: 'Execution result sent to the voice agent', ERROR_SENT: 'Unconfirmed outcome sent to the voice agent', CANCELLED: 'Voice handoff cancelled' };
      element('voice-handoff').textContent = labels[event.state] || 'No voice handoff';
    }
    if (event.type === 'audio') audio.play(event.data);
    if (event.type === 'interrupt') audio.interrupt();
    if (event.type === 'transcript') {
      const lines = transcriptLog.update(event).map(row => {
        const line = document.createElement('p');
        line.textContent = `${row.role}${row.interrupted ? ' (interrupted)' : ''}: ${row.text}`;
        return line;
      });
      transcript.replaceChildren(...lines);
    }
  },
});

start.addEventListener('click', async () => {
  if (busy || !healthy) return;
  busy = true; const attempt = ++generation; buttons();
  transcript.replaceChildren();
  transcriptLog.clear();
  element('voice-handoff').textContent = 'No voice calculation requested';
  status(voice, 'Waiting for microphone permission…');
  message.textContent = 'Allow microphone access to speak with AssemblyAI. Stop cancels this attempt.';
  try {
    if (!await audio.start() || attempt !== generation) return;
    await session.start();
  } catch {
    if (attempt !== generation) return;
    audio.stop(); busy = false; buttons();
    status(voice, 'Microphone unavailable', 'error');
    message.textContent = 'Check microphone permission and device availability, then try again.';
  }
});
function end() {
  if (validating) return;
  ++generation; audio.stop(); session.stop();
  if (!['connecting', 'ready', 'ending'].includes(session.state)) {
    busy = false; buttons(); status(voice, 'Microphone off');
  }
}
stop.addEventListener('click', end);
window.addEventListener('pagehide', end);
document.addEventListener('visibilitychange', () => { if (document.hidden && busy) end(); });

validate.addEventListener('click', async () => {
  if (busy) return;
  busy = true; validating = true; buttons(); stop.disabled = true;
  let payload;
  try {
    payload = await request('/api/voice-token');
    if (typeof payload.token !== 'string' || !payload.token) throw new Error('Invalid token');
    status(token, 'Issuance validated', 'ok');
    message.textContent = 'Credential issuance validated. No voice session was started.';
  } catch {
    status(token, 'Validation failed', 'error');
    message.textContent = 'Unable to validate the connection. Check the server and try again.';
  } finally {
    if (payload) delete payload.token;
    payload = undefined; busy = false; validating = false; buttons();
  }
});
async function checkHealth() {
  if (busy || healthBusy) return;
  healthBusy = true; buttons();
  try { healthy = (await request('/health')).status === 'ok'; }
  catch { healthy = false; }
  status(health, healthy ? 'Available' : 'Unavailable', healthy ? 'ok' : 'error');
  healthBusy = false; buttons();
}
check.addEventListener('click', checkHealth);
checkHealth();
