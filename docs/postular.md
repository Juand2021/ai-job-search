# /postular - guía rápida

`/postular` lleva una oferta de empleo desde el enlace hasta un borrador listo
para revisar, en una sola ejecución: evalúa el encaje, escribe la hoja de vida
(y la carta si la oferta la pide), la compila a PDF, la verifica para ATS y la
registra en el tracker. Por dentro sigue los pasos de `/apply`; las reglas
compartidas están en [`pipeline-contract.md`](pipeline-contract.md).

**Nunca envía la postulación.** El clic final en "Postular" siempre es tuyo.

## Qué hace

1. Lee la oferta (enlace o texto pegado). Si el portal bloquea la descarga
   (403, inicio de sesión) y el navegador integrado de Claude está disponible,
   abre el enlace ahí y solo lee el texto; si no, te pide que pegues la oferta.
2. Calcula el puntaje de encaje (0-100). Si es igual o mayor que
   `fit_threshold`, sigue sin preguntar; si es menor, o si la oferta trae
   texto sospechoso, se detiene y te pregunta.
3. Escribe la hoja de vida en el idioma de la oferta (español con títulos de
   sección en español), y la carta de presentación solo si la oferta la pide.
4. Compila, revisa el PDF y la verificación ATS.
5. Registra la fila en `job_search_tracker.csv` (estado `drafted`) y la etapa
   `borrador` en el historial de la postulación.
6. Te entrega un informe: puntaje con su explicación, archivos, resultado ATS,
   fila del tracker y siguiente paso.

## Configuración (`pipeline.config.json`, opcional)

| Clave | Por defecto | Qué controla |
|---|---|---|
| `fit_threshold` | `65` | Puntaje mínimo para seguir sin preguntar |
| `cover_letter` | `"when_requested"` | `when_requested` (solo si la oferta la pide), `always` o `never` |
| `cv_language` | `"posting"` | `posting` (idioma de la oferta) o un idioma fijo, p. ej. `"Spanish"` |
| `open_pdf` | `true` | Abrir el PDF al terminar (si corre en tu computador) |
| `rebuild_dashboard` | `true` | Recordarte `/sincronizar` al terminar |
| `dashboard_url` | sin valor | URL del tablero "Mis postulaciones"; sin ella no se sugiere `/sincronizar` |

Ejemplo:

```json
{ "fit_threshold": 70, "cover_letter": "when_requested", "cv_language": "posting" }
```

## Ejemplos

```text
/postular https://empresa.com/empleos/analista-de-datos-junior
/postular <pega aquí el texto completo de la oferta>
/postular buscar
```

`/postular buscar` toma la mejor oferta de tu última lista de `/rank` a la
que todavía no te has postulado (corre antes `/scrape` y `/rank`).

## Después

- Revisa el PDF y envía la postulación tú mismo.
- Cuando la envíes: `/outcome <empresa>`.
- Para dejar el formulario del portal lleno en el navegador integrado, usa `/llenar-formulario <empresa>` (Fase 5). Se detiene antes de enviar.
