// Headless replication of Obsidian Omnisearch v1.29.3's search pipeline.
//
// Setup (one-time):
//   git clone --depth 1 https://github.com/scambier/obsidian-omnisearch \
//       benchmarks/work/omnisearch-src
//   cd benchmarks && npm init -y && npm i minisearch
// Run:
//   cd benchmarks && node run_omnisearch.mjs
//
import MiniSearch from 'minisearch'
import { readFileSync, readdirSync, statSync } from 'fs'
import { join, basename, dirname, relative } from 'path'

// Load the EXACT separator regex from Omnisearch's own source — no
// hand-transcription drift.
const GLOBALS_SRC = readFileSync(
  new URL('./work/omnisearch-src/src/globals.ts', import.meta.url), 'utf-8')
const sepMatch = GLOBALS_SRC.match(/export const SEPARATORS =\s*(\/\[[\s\S]*?\]\/)/)
if (!sepMatch) throw new Error('SEPARATORS not found in omnisearch globals.ts')
const SEPARATORS = eval(sepMatch[1]).toString().slice(1, -1)
const SPACE_OR_PUNCTUATION = new RegExp(`${SEPARATORS}+`, 'u')
const BRACKETS_AND_SPACE = /[|\[\]\(\)<>\{\} \t\n\r]/u

function splitHyphens(text) {
  if (!text.includes('-')) return []
  return text.split('-').filter(t => t)
}
function splitCamelCase(text) {
  if (!/[a-z][A-Z]/.test(text)) return []
  return text.replace(/([a-z](?=[A-Z]))/g, '$1 ').split(' ').filter(t => t)
}
function tokenizeWords(text) { return text.split(BRACKETS_AND_SPACE) }
function tokenizeTokens(text) { return text.split(SPACE_OR_PUNCTUATION) }

function tokenizeForIndexing(text) {
  const words = tokenizeWords(text)
  let tokens = tokenizeTokens(text)
  tokens = [...tokens.flatMap(t => [t, ...splitHyphens(t), ...splitCamelCase(t)]), ...words]
  return tokens.filter(Boolean)
}
function tokenizeForSearch(text) {
  const tokens = tokenizeTokens(text).filter(Boolean)
  return {
    combineWith: 'OR',
    queries: [
      { combineWith: 'AND', queries: tokens },
      { combineWith: 'AND', queries: tokenizeWords(text).filter(Boolean) },
      { combineWith: 'AND', queries: tokens.flatMap(splitHyphens) },
      { combineWith: 'AND', queries: tokens.flatMap(splitCamelCase) },
    ],
  }
}

function* mdFiles(dir) {
  for (const e of readdirSync(dir)) {
    const p = join(dir, e)
    const st = statSync(p)
    if (st.isDirectory()) yield* mdFiles(p)
    else if (e.endsWith('.md')) yield p
  }
}

function parseNote(path, vaultRoot) {
  const raw = readFileSync(path, 'utf-8')
  let content = raw, aliases = '', tags = []
  const fm = raw.match(/^---\n([\s\S]*?)\n---\n?/)
  if (fm) {
    content = raw.slice(fm[0].length)
    const am = fm[1].match(/aliases:\s*\[([^\]]*)\]/)
    if (am) aliases = am[1].replace(/["']/g, ' ')
    const tm = fm[1].match(/tags:\s*\[([^\]]*)\]/)
    if (tm) tags = tm[1].split(',').map(s => s.trim())
  }
  const h = { 1: [], 2: [], 3: [] }
  for (const m of content.matchAll(/^(#{1,3})\s+(.+)$/gm)) h[m[1].length].push(m[2])
  return {
    path: relative(vaultRoot, path),
    basename: basename(path, '.md'),
    directory: dirname(relative(vaultRoot, path)),
    aliases,
    content,
    headings1: h[1].join(' '), headings2: h[2].join(' '), headings3: h[3].join(' '),
    tags: tags.join(' '),
    displayTitle: '',
    unmarkedTags: tags.map(t => t.replace(/^#/, '')).join(' '),
  }
}

function buildIndex(vault) {
  const ms = new MiniSearch({
    tokenize: tokenizeForIndexing,
    processTerm: t => t.toLowerCase(),
    idField: 'path',
    fields: ['basename', 'directory', 'aliases', 'content',
             'headings1', 'headings2', 'headings3', 'tags',
             'displayTitle', 'unmarkedTags'],
    storeFields: ['basename'],
  })
  const docs = [...mdFiles(vault)].map(p => parseNote(p, vault))
  ms.addAll(docs)
  return ms
}

const FUZZINESS = 0.1 // default setting '1'
function search(ms, query, k = 8) {
  const res = ms.search(tokenizeForSearch(query), {
    prefix: term => term.length >= 3,
    fuzzy: term => (term.length <= 3 ? 0 : term.length <= 5 ? FUZZINESS / 2 : FUZZINESS),
    boost: {
      basename: 10, aliases: 10, displayTitle: 10, directory: 7,
      headings1: 6, headings2: 5, headings3: 4, tags: 2, unmarkedTags: 2,
    },
    tokenize: t => [t],
  })
  return res.slice(0, k).map(r => r.basename)
}

function evalSet(ms, questions, getQ) {
  let full = 0, r1 = 0, n = 0
  const lat = []
  const byHops = { 1: [0, 0], 2: [0, 0] }
  for (const q of questions) {
    const text = getQ(q)
    if (!text) continue
    n++
    const t0 = performance.now()
    const titles = search(ms, text, 8)
    lat.push(performance.now() - t0)
    const gold = q.gold_notes
    const ok = gold.every(g => titles.includes(g))
    full += ok
    r1 += gold.includes(titles[0])
    const hops = gold.length > 1 ? 2 : 1
    byHops[hops][0] += ok; byHops[hops][1]++
  }
  lat.sort((a, b) => a - b)
  return {
    n, full_support: +(full / n).toFixed(3), recall1: +(r1 / n).toFixed(3),
    hops1: byHops[1][1] ? +(byHops[1][0] / byHops[1][1]).toFixed(3) : null,
    hops2: byHops[2][1] ? +(byHops[2][0] / byHops[2][1]).toFixed(3) : null,
    p50_ms: +lat[Math.floor(lat.length / 2)].toFixed(2),
  }
}

const REPO = new URL('..', import.meta.url).pathname.replace(/\/$/, '')
const out = {}

// multihop + robustness variants
{
  const vault = `${REPO}/benchmarks/data/multihop/vault`
  const ms = buildIndex(vault)
  const qs = JSON.parse(readFileSync(`${REPO}/benchmarks/data/multihop/questions.json`))
  out.multihop = evalSet(ms, qs, q => q.q)
  const variants = JSON.parse(readFileSync(`${REPO}/benchmarks/data/multihop/robust_queries.json`))
  const gold = Object.fromEntries(qs.map(q => [q.q, q.gold_notes]))
  for (const key of ['paraphrase', 'korean', 'keyword', 'typo']) {
    const vq = Object.entries(variants)
      .filter(([orig, v]) => v && typeof v === 'object' && v[key] && gold[orig])
      .map(([orig, v]) => ({ q: v[key], gold_notes: gold[orig] }))
    out[`robust_${key}`] = evalSet(ms, vq, q => q.q)
  }
}
// KorMapleQA (doc-level: gold doc in top-8; twohop = both docs)
if (process.argv.includes('--kormapleqa')) {
  const vault = `${REPO}/benchmarks/data/maple_real/vault`
  const ms = buildIndex(vault)
  const lines = readFileSync(`${REPO}/benchmarks/data/kormapleqa/questions.jsonl`, 'utf-8')
    .split('\n').filter(Boolean).map(JSON.parse)
  const byType = {}
  for (const q of lines) {
    if (q.answerable === false) continue
    ;(byType[q.type] ||= []).push(q)
  }
  const res = {}
  for (const [t, qs] of Object.entries(byType)) {
    res[t] = evalSet(ms, qs, q => q.q)
  }
  res.all = evalSet(ms, lines.filter(q => q.answerable !== false), q => q.q)
  console.log(JSON.stringify(res, null, 2))
  process.exit(0)
}

// Korean corpora
for (const name of ['maple', 'law', 'kepano']) {
  const vault = `${REPO}/benchmarks/data/${name}/vault`
  const ms = buildIndex(vault)
  const qs = JSON.parse(readFileSync(`${REPO}/benchmarks/data/${name}/questions.json`))
  out[name] = evalSet(ms, qs, q => q.q)
}

console.log(JSON.stringify(out, null, 2))
