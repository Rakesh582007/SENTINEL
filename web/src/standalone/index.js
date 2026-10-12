// Standalone build entry: decode the bundled sample, start the in-browser
// backend and point the API client at it. Only loaded when __STANDALONE__.
import { setTransport } from '../api/client.js'
import { Engine, decodeSample } from './engine.js'
import sampleB64 from './sample-records.json.gz'
import { makeTransport } from './transport.js'

async function gunzipBase64(b64) {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))
  return new Response(stream).text()
}

export async function startStandalone() {
  const doc = JSON.parse(await gunzipBase64(sampleB64))
  const engine = new Engine(decodeSample(doc), doc.files)
  setTransport(makeTransport(engine))
  window.__standalone = {
    engine,
    coverAntenna: (seconds = 25) => engine.box.cover(seconds),
  }
  return engine
}
