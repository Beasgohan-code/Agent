// Public TypeTube client only. No inherited provider keys or arbitrary endpoints.
import { createClient } from 'typetube';
let client;
try {
  let input = '';
  for await (const chunk of process.stdin) {
    input += chunk;
    if (input.length > 8192) throw new Error('input too large');
  }
  client = createClient({ timeoutMs: 15000 });
  const track = await client.resolve(JSON.parse(input).url);
  const audio = track.bestAudio;
  if (!track.success || !audio || typeof audio.url !== 'string' || audio.url.length > 8192) throw new Error('no audio');
  process.stdout.write(JSON.stringify({url: audio.url, title: String(track.title || 'YouTube audio').slice(0, 160), mime: String(audio.mimeType || '').slice(0, 128)}));
} catch {
  process.stderr.write('TypeTube resolution unavailable\n');
  process.exitCode = 1;
} finally { client?.close(); }
