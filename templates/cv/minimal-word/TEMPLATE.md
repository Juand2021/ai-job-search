# Template: minimal-word

- **Type:** CV
- **Source extension:** .tex
- **Engine/toolchain:** lualatex
- **Page limit:** 1 page(s)
- **Fonts:** Calibri (system font on Windows) through fontspec; falls back to Carlito, its metric-compatible clone (`fonts-crosextra-carlito` on Linux), when Calibri is not installed
- **Class/packages:** article + geometry, fontspec, xcolor, enumitem, titlesec, needspace, hyperref. `preamble.tex` must sit next to the CV source (`\input{preamble.tex}`).

## Compile command

    cd cv && rm -f <file>.pdf && mkdir -p build && lualatex -interaction=nonstopmode -output-directory=build <file>.tex && mv build/<file>.pdf ./

## Style rules

- Recreates the candidate's own Word CV: single column, black text, hierarchy through bold, italics and size only. No colour accents; grey (`meta`) only for secondary text (the `| location` part and dates).
- Header: name in `\large` bold, centred; one contact line with ` | ` separators; city line; italic grey headline. Keep the header small so the page holds more content.
- Section headings: bold uppercase with a full-width rule underneath (`\section{...}` does this).
- Entries use `\entry{Bold title}{grey meta}{date}{italic subtitle}` followed by an `itemize` list.
- Skills use `\skill{Label}{items}`, one line each where possible.
- Section order: Profile, Core Competencies, Work Experience, Projects, Education, Certifications, Languages & Awards. Translate every `\section{}` title when the CV is in Spanish (Perfil, Competencias Clave, Experiencia Laboral, Proyectos, Educación, Certificaciones, Idiomas y Reconocimientos).
- Use the whole page: fill to within ~8% of the bottom margin before calling it done; never leave a large empty block at the end.

## Known pitfalls

- `\entry`'s second and fourth arguments may be empty (`{}`), which drops the `|` meta or the italic line.
- `#` in text must be written `\#` (C\#).
- Copy `preamble.tex` into `cv/` (it already lives there as `cv/preamble.tex`). Edit both copies together.
- `tools/verify_layout.py` reports "body text inside the bottom margin band, colliding with the footer" when the page is full. This template has no footer (`\pagestyle{empty}`), so that one finding is a false positive here as long as the text ends above the bottom margin; every other layout finding still applies.
- Keep `\atsspaces` at the start of the name line. LuaTeX writes no space characters, and without a real space glyph in each font subset pypdf (and some ATS parsers) glue words together (`AIEngineerfocused...`). It is zero width and invisible.
- `\entry` already reserves space with `\needspace`; no `\needspace` is needed before it.
