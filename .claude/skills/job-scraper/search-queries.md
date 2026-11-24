# Search Queries for Job Scraper

<!-- Customized 2026-11-24 from the candidate profile. Re-run /setup --section search to change. -->

## Installed portal CLIs (primary for `/scrape`)

`/scrape` discovers every portal skill under `.agents/skills/*/SKILL.md` and runs its CLI first. None ship with AI Job Search: copy the ones for your market from [community-portals](https://github.com/ai-job-search-dev/community-portals) (e.g. `linkedin-search`, `freehire-search` under `portals/global/`), or build one with `/add-portal`. You do **not** need a matching `site:` line below for those CLIs to run.

The `site:` query templates in this file are the **WebSearch fallback** — for portals without a CLI, company career pages, or when a CLI fails.

**Language scope:** write every query category in every language listed in your CLAUDE.md Languages table (typically 1-2, sometimes more). A posting requiring a language you have *not* declared, as a job condition, is excluded before scoring; a posting requiring a *higher level* than you declared in a language you *do* work in is flagged for your own judgment, not excluded — see `04-job-evaluation.md`'s Language Gate, the single source of truth for this rule. Translate each category's keywords rather than machine-translating word-for-word (e.g. "Frontend Developer" -> "Desarrollador Frontend", not a literal word-for-word translation) if you work in more than one language.

## Search Sites

<!-- Configured 2026-11-24 for Juan Diego Chaves Guerrero (Bogotá, Colombia). No portal CLI is installed yet, so every query below runs through the WebSearch fallback. -->

Primary (Colombian job boards - none has a CLI yet; scaffold one with `/add-portal`):
- **co.computrabajo.com** - Colombia's largest general job board
- **linkedin.com/jobs** - LinkedIn job listings (filter: Colombia / Bogotá); also covered by the community `linkedin-search` CLI once installed
- **elempleo.com** - major Colombian general board
- **magneto365.com** - Colombian board with many tech and trainee postings

Secondary (company career pages via Google):
- Direct Google searches with `site:` filters for known target companies (PENDIENTE: target companies)

## Query Categories

Queries are grouped by priority and written in both of the candidate's working languages (Spanish, English). Combine each query with location terms (Bogotá, Colombia, remoto) where the site supports it.

Plain terms blocks are what portal CLIs consume (one term per line, no `OR`, no `site:`, no location). WebSearch-only blocks are Google syntax for the fallback path.

### Priority 1: AI Engineer (primary target)

The candidate's confirmed target (2026-11-24): AI Engineer at analyst / junior professional level. Never internships, apprenticeships or semilleros.

#### Plain terms (portal CLIs)

```
Ingeniero de Inteligencia Artificial
Ingeniero IA
Desarrollador IA
Ingeniero de automatización con IA
AI Engineer
Junior AI Engineer
Generative AI Engineer
LLM Engineer
AI Automation Engineer
```

#### WebSearch-only (`site:` fallback)

```
site:co.computrabajo.com "ingeniero de inteligencia artificial" Bogotá
site:co.computrabajo.com "inteligencia artificial" desarrollador Bogotá
site:elempleo.com "inteligencia artificial" ingeniero Bogotá
site:magneto365.com "inteligencia artificial" Bogotá
site:linkedin.com/jobs "AI Engineer" Bogotá
site:linkedin.com/jobs "Ingeniero de IA" Colombia
site:linkedin.com/jobs "Generative AI" engineer Colombia
```

### Priority 2: DevOps / cloud with AI (Azure)

Also of interest, always AI-related: DevOps with AI, AI deployment on Azure.

#### Plain terms (portal CLIs)

```
Ingeniero DevOps IA
Ingeniero cloud Azure IA
MLOps Engineer
AI DevOps Engineer
Azure AI Engineer
```

#### WebSearch-only (`site:` fallback)

```
site:co.computrabajo.com "DevOps" "inteligencia artificial" Bogotá
site:linkedin.com/jobs "MLOps" Bogotá
site:linkedin.com/jobs "Azure AI" engineer Colombia
site:elempleo.com "Azure" "inteligencia artificial" Bogotá
```

### Priority 3: Software development with AI agents

Developer roles whose core is AI: agents, LLM integrations, MCP, automation (Python, TypeScript, Node.js).

#### Plain terms (portal CLIs)

```
Desarrollador Python IA
Desarrollador de agentes IA
Python AI Developer
LLM Developer
```

#### WebSearch-only (`site:` fallback)

```
site:co.computrabajo.com "python" "inteligencia artificial" Bogotá
site:linkedin.com/jobs "AI developer" python Bogotá
site:linkedin.com/jobs "LLM" developer Colombia
```

## Excluded (deal-breakers, confirmed by the candidate)

Drop these from results before scoring: service desk / mesa de ayuda / soporte TI roles, internships (práctica, practicante), apprenticeship programs (aprendiz SENA), semilleros, trainee programs, and roles not related to AI. Banks and large non-software corporations are not excluded, only ranked lower.

## Location Filter

Home base: Bogotá, Colombia. Hybrid in Bogotá is the ideal (confirmed).
- Bogotá, hybrid (ideal)
- Bogotá, fully on-site, or fully remote (acceptable - confirmed by the candidate; rank slightly below hybrid)
- Other cities requiring relocation (FLAG - relocation not yet confirmed by the candidate)

## Language Filter

Your working languages and levels are in CLAUDE.md's Languages table. When filtering scraped results, apply `04-job-evaluation.md`'s Language Gate: a posting requiring a language you haven't declared at all is excluded; a posting requiring a higher level than you declared in a language you do work in is not excluded, flag it clearly instead (see `job-scraper/SKILL.md`'s Step 3 "Quick Fit Assessment" for how the flag surfaces in `/scrape` output). Postings simply *written* in a language you don't work in, that don't require it on the job, are fine.

## Date Filter

Only include jobs posted within the last 14 days, matching `/scrape` Step 1b.3: use a supported recency filter or filter the returned publication dates client-side. A future application deadline does not bypass this discovery window; `/rank` handles deadline expiry and urgency separately after discovery. If a posting date cannot be determined, include it but flag as "date unknown".

## Adapting Queries

If the user specifies a focus area, select queries from the matching category and also generate 2-3 custom queries for that focus. For example:
- "/scrape [focus_area]" -> relevant category queries + custom focus-specific queries
