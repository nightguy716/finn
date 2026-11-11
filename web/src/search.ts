import aliasFile from './data/aliases.json' with { type: 'json' }
import equityFile from './data/equities.json' with { type: 'json' }

type EquityFile = {
  companies: [string, string][]
}

export type Suggestion = {
  symbol: string
  name: string
  score: number
}

export type CompanySearch = {
  matches: Suggestion[]
  closest: Suggestion[]
  clear: Suggestion | null
}

const DROP = new Set([
  'ltd',
  'limited',
  'co',
  'company',
  'corp',
  'corporation',
  'inc',
  'plc',
  'pvt',
  'private',
  'the',
  'and',
  'of',
])

type Row = {
  symbol: string
  name: string
  tokens: string[]
}

const companies: Row[] = (equityFile as unknown as EquityFile).companies.map(([symbol, name]) => ({
  symbol,
  name,
  tokens: words(name),
}))

const bySymbol = new Map(companies.map((row) => [row.symbol, row]))

const aliases: { tokens: string[]; symbol: string }[] = Object.entries(aliasFile as Record<string, string>)
  .map(([phrase, symbol]) => ({ tokens: words(phrase), symbol }))
  .filter((row) => row.tokens.length > 0 && bySymbol.has(row.symbol))

export function isListedSymbol(symbol: string): boolean {
  return bySymbol.has(symbol.trim().toUpperCase())
}

export function companyBySymbol(symbol: string): Suggestion | null {
  const row = bySymbol.get(symbol.trim().toUpperCase())
  return row ? { symbol: row.symbol, name: row.name, score: 1000 } : null
}

/** Suggestions for what the user has typed. No network. */
export function searchCompanies(raw: string): CompanySearch {
  const query = raw.trim()
  if (!query) return { matches: [], closest: [], clear: null }
  const queryTokens = words(query)
  const querySymbol = symbolQuery(query)
  const alias = aliasFor(queryTokens)
  const scored: (Suggestion & { tokens: number })[] = []
  for (const row of companies) {
    let score = scoreRow(queryTokens, querySymbol, row)
    if (alias === row.symbol) score = Math.max(score, 2000)
    if (score >= 180) scored.push({ symbol: row.symbol, name: row.name, score, tokens: row.tokens.length })
  }
  scored.sort((a, b) => b.score - a.score || a.tokens - b.tokens || a.symbol.localeCompare(b.symbol))
  const matches = scored.slice(0, 6).map(({ symbol, name, score }) => ({ symbol, name, score }))
  if (matches.length) return { matches, closest: [], clear: clearMatch(matches, alias) }
  return { matches: [], closest: nearest(query, 3), clear: null }
}

function clearMatch(matches: Suggestion[], alias: string | null): Suggestion | null {
  const top = matches[0]
  if (!top) return null
  if (alias && top.symbol === alias) return top
  if (top.score >= 1000) return top
  const second = matches[1]
  const strong = top.score >= 500 && (!second || second.score < 500 || top.score - second.score >= 150)
  return strong ? top : null
}

function aliasFor(queryTokens: string[]): string | null {
  if (!queryTokens.length) return null
  for (const alias of aliases) {
    if (alias.tokens.length !== queryTokens.length) continue
    const close = alias.tokens.every((token, index) => tokenScore(queryTokens[index], token) >= 70)
    if (close) return alias.symbol
  }
  return null
}

function scoreRow(queryTokens: string[], querySymbol: string, row: Row): number {
  if (querySymbol && querySymbol === row.symbol) return 1000
  const prefix =
    querySymbol.length >= 2 && row.symbol.startsWith(querySymbol)
      ? 720 + Math.round((querySymbol.length / row.symbol.length) * 40)
      : 0
  return Math.max(prefix, nameScore(queryTokens, row))
}

function nameScore(queryTokens: string[], row: Row): number {
  queryTokens = queryTokens.filter((token) => token.length >= 2)
  if (!queryTokens.length) return 0
  let matched = 0
  let total = 0
  const compact = row.symbol.toLowerCase().replace(/[^a-z0-9]/g, '')
  for (const token of queryTokens) {
    let best = 0
    for (const nameToken of row.tokens) best = Math.max(best, tokenScore(token, nameToken))
    if (token.length >= 4 && compact.startsWith(token)) best = Math.max(best, 90)
    if (best > 0) {
      matched += 1
      total += best
    }
  }
  if (!matched) return 0
  if (matched === queryTokens.length) return 860 + total / queryTokens.length
  return 180 + total / queryTokens.length
}

function nearest(query: string, limit: number): Suggestion[] {
  const needle = words(query).join('').slice(0, 16)
  if (needle.length < 2) return []
  return companies
    .map((row) => {
      const symbol = row.symbol.toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 16)
      let gap = distance(needle, symbol)
      for (const token of row.tokens) gap = Math.min(gap, distance(needle, token.slice(0, 16)))
      return { row, gap }
    })
    .sort((a, b) => a.gap - b.gap || a.row.symbol.localeCompare(b.row.symbol))
    .slice(0, limit)
    .map((item) => ({ symbol: item.row.symbol, name: item.row.name, score: item.gap }))
}

function words(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .split(/\s+/)
    .filter((token) => token && !DROP.has(token))
}

function symbolQuery(text: string): string {
  const compact = text.trim().toUpperCase().replace(/\s+/g, '')
  return /^[A-Z0-9&-]{1,20}$/.test(compact) ? compact : ''
}

function tokenScore(query: string, name: string): number {
  if (!query || !name) return 0
  if (query === name) return 100
  if (query.length >= 3 && name.startsWith(query)) return 86
  if (name.length >= 4 && query.startsWith(name)) return 80
  const limit = query.length >= 8 ? 2 : 1
  if (query.length < 4) return 0
  const gap = distance(query, name)
  if (gap > limit) return 0
  return 78 - gap * 8
}

function distance(a: string, b: string): number {
  if (a === b) return 0
  let prev = Array.from({ length: b.length + 1 }, (_, index) => index)
  for (let i = 1; i <= a.length; i += 1) {
    const next = [i]
    for (let j = 1; j <= b.length; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1
      next.push(Math.min(next[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost))
    }
    prev = next
  }
  return prev[b.length]
}
