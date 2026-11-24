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
- Direct Google searches with `site:` filters for known target companies; the verified list lives in `job_scraper/companies.yaml` and `/scrape-navegador` reads it with the built-in browser

## Query Categories

Queries are grouped by priority and written in both of the candidate's working languages (Spanish, English). Combine each query with location terms (Bogotá, Colombia, remoto) where the site supports it.

Plain terms blocks are what portal CLIs consume (one term per line, no `OR`, no `site:`, no location). WebSearch-only blocks are Google syntax for the fallback path.

### Priority 1: Python / data / AI development

Strongest direction: the candidate's advanced Python, data mining and ML projects, and stated passion for AI.

#### Plain terms (portal CLIs)

```
Desarrollador Python junior
Analista de datos junior
Científico de datos junior
Practicante ingeniería de sistemas
Junior Python Developer
Junior Data Analyst
Junior Data Scientist
Machine Learning intern
```

#### WebSearch-only (`site:` fallback)

```
site:co.computrabajo.com "desarrollador python" Bogotá
site:co.computrabajo.com "analista de datos" junior Bogotá
site:elempleo.com "python" junior Bogotá
site:magneto365.com "analista de datos" Bogotá
site:linkedin.com/jobs "junior python developer" Colombia
site:linkedin.com/jobs "data analyst" junior Bogotá
site:linkedin.com/jobs "machine learning" intern Colombia
```

### Priority 2: Software and mobile development

The candidate's programming range (Java, Kotlin, C#, JavaScript, SQL) and the TadIA Android project.

#### Plain terms (portal CLIs)

```
Desarrollador de software junior
Desarrollador Android junior
Desarrollador Java junior
Practicante desarrollo de software
Junior Software Developer
Junior Android Developer
```

#### WebSearch-only (`site:` fallback)

```
site:co.computrabajo.com "desarrollador de software" junior Bogotá
site:co.computrabajo.com "desarrollador android" Bogotá
site:elempleo.com "desarrollador" junior Bogotá
site:linkedin.com/jobs "junior software developer" Bogotá
site:linkedin.com/jobs "android developer" junior Colombia
```

### Priority 3: Data quality, QA and databases

Adjacent roles using SQA training and SQL.

#### Plain terms (portal CLIs)

```
Analista QA junior
Analista de pruebas de software
Analista de bases de datos junior
Junior QA Analyst
```

#### WebSearch-only (`site:` fallback)

```
site:co.computrabajo.com "analista QA" junior Bogotá
site:elempleo.com "analista de pruebas" Bogotá
site:linkedin.com/jobs "QA analyst" junior Bogotá
```

### Priority 4: IT support / service desk (wider net)

Direct experience from the SOE 360 internship; useful as a fallback while studying.

#### Plain terms (portal CLIs)

```
Analista mesa de ayuda
Analista de soporte TI
IT Service Desk Analyst
```

#### WebSearch-only (`site:` fallback)

```
site:co.computrabajo.com "mesa de ayuda" Bogotá
site:elempleo.com "soporte TI" Bogotá
site:linkedin.com/jobs "service desk" Bogotá
```

## Location Filter

Home base: Bogotá, Colombia (PENDIENTE: confirm commute limits and remote preference).
- Bogotá (ideal)
- Remote from Colombia (acceptable)
- Chía, Cota, Funza, Mosquera, Soacha (borderline - check commute)
- Other cities requiring relocation (too far unless confirmed otherwise)

## Language Filter

Your working languages and levels are in CLAUDE.md's Languages table. When filtering scraped results, apply `04-job-evaluation.md`'s Language Gate: a posting requiring a language you haven't declared at all is excluded; a posting requiring a higher level than you declared in a language you do work in is not excluded, flag it clearly instead (see `job-scraper/SKILL.md`'s Step 3 "Quick Fit Assessment" for how the flag surfaces in `/scrape` output). Postings simply *written* in a language you don't work in, that don't require it on the job, are fine.

## Date Filter

Only include jobs posted within the last 14 days, matching `/scrape` Step 1b.3: use a supported recency filter or filter the returned publication dates client-side. A future application deadline does not bypass this discovery window; `/rank` handles deadline expiry and urgency separately after discovery. If a posting date cannot be determined, include it but flag as "date unknown".

## Adapting Queries

If the user specifies a focus area, select queries from the matching category and also generate 2-3 custom queries for that focus. For example:
- "/scrape [focus_area]" -> relevant category queries + custom focus-specific queries
