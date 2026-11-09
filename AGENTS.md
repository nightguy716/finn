# FINN: Financial Investment Agent (AI Engineer Build Challenge, ENAM)

Read this file at the start of every session. It is the agreed project brief.

## Context
- Campus-recruitment assessment (IIT Delhi, AI Engineer 2027). Released 8 Nov 2026. Hard deadline 15 Nov 2026.
- Target: feature-complete by 11 Nov, polish and submit by 14 Nov.
- Grading: how I build, what I choose to build, creativity, product sense, judgment. NOT completeness or polish.
- Thin-but-working beats broad-but-broken. A demo that does not run is the worst outcome.
- Build the smallest thing that proves I can build the real thing well.
- Bar: "no AI slop". Concise, dense, interactive, beautifully designed, mobile-first.

## Product
FINN is a mobile-first investor app with two modes:
- PUSH: tells the investor what changed and why they should care.
- PULL: researches/analyses a company on demand.

Point of view: "Brief, then drill". Do not start from a blank chatbot. Start from what matters, then let the investor drill into any item with contextual questions.

## Scope (agreed): two workflows

### Push
- Prioritised digest of corporate announcements across the portfolio for a user-chosen window (default last 24h). Routine items collapsed into one row, material ones first.
- Configurable alert thresholds: volume > N x recent average, price move beyond +/-X% in a day. User sets N and X.
- Enriched card types:
  - Quarterly results: Revenue, EBITDA, PBT, PAT with QoQ and YoY. Indian results filings show current quarter, previous quarter and year-ago quarter side by side, so one filing gives both.
  - Management change: short bio of the incoming person. The disclosure usually contains a brief profile, so use that first (LinkedIn is not scrapeable).
- Every other announcement type: a one-line summary or correct priority only. Do not over-build.

### Pull
- Promise Ledger: for a ticker, last 4 quarters of management guidance (growth, margins, capex) versus what was actually delivered. Each row green/amber/red with a one-line verdict at top. Cite the source passage.
- Small financial snapshot (revenue, margins, PAT, key ratios).
- MUST work for ANY NSE ticker where data exists. Nothing hard-wired to the demo set.
- PRIMARY SOURCES ONLY: annual reports, concall transcripts, results filings. No broker notes, no news, no research reports, no reliance on the model's own outside knowledge of the company. (Push-side enrichment like a person's background is fine.)

### Deliberately out (list in the write-up)
Other six pull outputs (balance sheet, cash quality, trajectory, bull/bear, etc.), voice, native app, user accounts, real-time streaming, enrichment of every announcement type.

### Fallback if behind schedule
Cut the contextual chat to a simple "show source" link first. Never cut push or the Promise Ledger.

## Companies
- Portfolio (18): RELIANCE, TCS, HDFCBANK, INFY, ITC, SUNPHARMA, MARUTI, LT, BAJFINANCE, TITAN, CGPOWER, BHARATFORG, MARICO, PERSISTENT, TRENT, POLYCAB, DIXON, BHARATSEATS
- Ad-hoc pull demos (4): DMART, ASIANPAINT, ETERNAL (formerly Zomato), PIDILITIND
- Tickers use .NS (NSE) or .BO (BSE) on Yahoo Finance, e.g. RELIANCE.NS.

## Data sources
1. Price and volume (EOD): yfinance (or equivalent).
2. Announcements: NSE/BSE feeds for the portfolio.
3. Fundamentals: annual reports and concall transcripts via links on screener.in or company IR sites.
- Public pages only. No logged-in Screener cookies or anything that breaches terms of service. Be gentle (low request rate, cache everything).
- Plumbing, not the point. Do not over-engineer.
- If a source is blocked, fall back to pre-fetched cached filings for the push demo set. The pull side must stay live for any ticker.

## Architecture
- Vercel: Next.js mobile-first PWA + Python serverless functions.
- Supabase free tier for cache/storage (respect that it auto-pauses).
- Runtime models must be FREE TIER (no API budget): Gemini free tier as the main model, Groq free tier as fast fallback. Confirm current free models and limits in the spike; do not trust memory.
- Model routing: cheap/fast model for bulk extraction and classification, stronger model only for the promise-versus-delivery reasoning.
- Cache everything (fetched docs, extracted text, model outputs) keyed by ticker + document + quarter. Chunk long documents. Respect rate limits with backoff.
- Push realism: daily scheduled job plus a "replay" mode over real recent filings so the demo works at any time.
- Track and report approximate model cost/tokens per ticker (efficiency earns bonus points).

## Working rules
- One step at a time. Confirm before moving to the next.
- Small, frequent commits with clear messages. Repo is private under the Aryanchandramauli GitHub account.
- Never commit secrets. Keys live in .env (gitignored) and Vercel env vars.
- Prefer root-cause fixes. Check raw intermediate values rather than accepting surface-level fixes.
- Borrow ideas only from the earlier Callidus project, never copy its code (it belongs to a separate commercial product).
- Keep a short BUILD_LOG.md of key decisions and trade-offs as we go (feeds the write-up).
- The build conversations are graded. Keep sessions focused and exportable.

## Definition of done
- Opens and works on a phone via a deployed Vercel link.
- Push digest + alerts + results card + management-change card work on real data.
- Promise Ledger works on a ticker not in the demo set.
- Design is dense, clean, and has a clear point of view.

## Submission checklist
- [ ] Deployed mobile-friendly link
- [ ] GitHub repo (private, access granted or made public)
- [ ] AI build history (Claude Code / LLM conversation exports or share links)
- [ ] Covering-email write-up: what I built, key decisions and trade-offs, what I deliberately left out, where I'd take it next
- [ ] Email to assessment@enam.com, subject exactly: IIT Delhi – AI Engineer - 2027
