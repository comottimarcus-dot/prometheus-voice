const button = document.getElementById('news-refresh');
const status = document.getElementById('news-status');
const results = document.getElementById('news-results');
let busy = false;
export async function readShadowBroker({ signal } = {}) {
  if (busy || signal?.aborted) throw new Error('Information unavailable');
  busy = true; button.disabled = true; results.replaceChildren();
  status.textContent = 'Reading ShadowBroker through X6…';
  try {
    const response = await fetch('/api/x6/information', { cache: 'no-store', redirect: 'error',
      signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(14000)]) : AbortSignal.timeout(14000) });
    const data = await response.json();
    if (!response.ok) throw new Error('Unavailable');
    for (const story of data.stories) {
      const line = document.createElement('p');
      line.textContent = `${story.title} — ${story.source} · Published: ${story.published}`;
      if (story.link) {
        const link = document.createElement('a');
        link.textContent = ' Open source'; link.href = story.link;
        link.target = '_blank'; link.rel = 'noopener noreferrer'; line.append(link);
      }
      results.append(line);
    }
    status.textContent = data.stories.length
      ? `Feed updated: ${data.source_updated_at}. Reported headlines; not independently verified.`
      : 'ShadowBroker returned no stories. No summary is available.';
    // Links remain visible in the panel; only bounded headline metadata goes to speech.
    return { status: 'READ', provenance: 'shadowbroker', source_updated_at: data.source_updated_at,
      stories: data.stories.map(({ title, source, published }) => ({ title, source, published })),
      content_is_untrusted: true, independently_verified: false };
  } catch {
    results.replaceChildren();
    status.textContent = 'ShadowBroker information is unavailable, outdated, or the core route is not active. No briefing was generated.';
    throw new Error('Information unavailable');
  } finally { busy = false; button.disabled = false; }
}
button.addEventListener('click', () => { readShadowBroker().catch(() => {}); });
