# Handoff — academic-vagas-bot (robô de vagas acadêmicas + dashboard na nuvem)

You're picking up work on this project with no prior context — here's what you need to continue it.

## Goal

The user (a job-seeker in Brazil, non-developer) wants a free system that monitors academic job openings across Brazil — professor (efetivo/substituto/visitante/colaborador), pesquisador, pós-doutorado, bolsas — from official gazettes and institutional sources, both public and private, and presents them in a filterable dashboard. It must run automatically (no PC on) and be accessible via a shareable link with Google login. All conversation with the user is in **Portuguese** — respond in Portuguese.

## Current State

**Working and deployed end-to-end:**
- Python pipeline (`python -m src.main`) scrapes sources → rule-based classifier → SQLite dedup → CSV/JSON/Markdown exports → Streamlit dashboard.
- **~545 vacancies** in the DB currently. Central validator keeps only higher-ed teaching/research openings (filters out basic-ed municipal teachers, DOU contract extracts, licitações, homologations, etc.).
- **GitHub Actions** (`.github/workflows/daily.yml`) runs the full search daily at 07:00 BRT and on `workflow_dispatch`. Tested successfully (run #1, ~7.5 min, committed results back to repo). Uses `AVB_REAL_CHROME=0` so Scrapling uses the bundled Chromium on Linux CI.
- **Deployed dashboard:** https://vagas-academicas.streamlit.app (Streamlit Community Cloud, from repo `sgurfinkel1-dev/academic-vagas-bot`, branch `main`, main file `dashboard.py`, Python 3.12).
- **Google login WORKS** — verified the full OAuth flow completes and the dashboard loads authenticated as sgurfinkel1@gmail.com.

**Sources status (learned empirically — do not re-derive):**
- DOU (federal) — works via Scrapling + browser; results embedded in a `<script>` with `jsonArray` on the in.gov.br consulta page. Plain httpx gets 502/timeout. On Windows local, the bundled Chromium fails (side-by-side error) so it needs `real_chrome=True`; on Linux CI the opposite. Controlled by env `AVB_REAL_CHROME` (default "1").
- Querido Diário (municipal SP/MG) — works via `https://api.queridodiario.ok.org.br/gazettes` (the `api.` subdomain; `/api/gazettes` on the main host returns the SPA and Cloudflare-blocks).
- FAPESP, university concurso pages, Gupy (private via `https://employability-portal.gupy.io/api/v1/jobs`), Vagas.com — all working via plain httpx.
- Open web search (Bing/DDG) — disabled; they serve captchas to scrapers.

## Key Files & Locations

- Repo: `~/academic-vagas-bot` (git, remote `https://github.com/sgurfinkel1-dev/academic-vagas-bot.git`, **private**).
- `dashboard.py` — Streamlit app. Sidebar filters, whole-word accent-insensitive text search, two live-search buttons ("Busca geral" = Gupy+QD, "Buscar só nos diários oficiais" = DOU+QD), "⚙️ Busca automática" config panel (areas/period), Google-login gate (`_exigir_login`, active only when `auth` in st.secrets).
- `src/main.py` — orchestrator + `--palavra <area>` / `--modo geral|diarios` live-search entry point. Reads `agenda.yaml` to override areas/period.
- `src/sources/*.py` — dou, querido_diario, fapesp, universidades_publicas, universidades_privadas, gupy, vagas_com, inlabs(stub), busca_aberta(disabled).
- `src/extractors/llm_classifier.py` — rule-based classification + `eh_vaga_academica()` central validator.
- `src/nuvem.py` — GitHub API helpers (commit agenda.yaml, dispatch workflow) for the cloud config panel.
- `config.yaml` — sources on/off, `termos_base` (22 terms), `paginas_concursos`, `paginas_privadas`.
- `agenda.yaml` — user-editable areas + dias_retroativos.
- `DEPLOY.md` + `.streamlit/secrets.toml.example` — deploy guide and secrets template.
- Google Cloud project "Vagas Academicas" (id `atlantean-house-503315-f4`), OAuth client "Dashboard Streamlit", client_id `896191028029-e7g4l2gd6bcv3kp3i39c3k6aq4j3usd2.apps.googleusercontent.com`. Redirect URIs: `http://localhost:8501/oauth2callback` and `https://vagas-academicas.streamlit.app/oauth2callback`.

## Decisions & Rationale

- **Rule-based classifier, not an LLM** — free, deterministic, good enough; upgrade path noted in code if precision falls short.
- **DOU area search combines a single quoted phrase + local filtering**, because the DOU engine returns 0 for two AND-ed quoted phrases (a real engine quirk). So `buscar_palavra` searches `"<area>"` and filters vacancy-type terms in Python.
- **Cloud stack = GitHub Actions + Streamlit Cloud, NOT Google Apps Script.** Apps Script can't run Python or a browser, so it would lose the DOU (biggest source). This was explicitly evaluated and rejected.
- **Repo is private**; Streamlit needed the "Connect here" private-repo grant under Streamlit → Settings → Linked accounts (the initial OAuth only covers public repos).

## Do NOT

- Do NOT enter/paste/type secrets, tokens, API keys, or passwords into any field — the assistant is barred from this even when asked. The user does all credential entry themselves. This came up repeatedly and is a hard rule.
- Do NOT try Google Apps Script for the automation (see rationale).
- Do NOT use plain httpx for DOU or for `queridodiario.ok.org.br/api/...` — they block/oscillate; use the browser (DOU) and the `api.` subdomain (QD).
- Do NOT re-enable busca_aberta expecting results — search engines captcha the scraper.
- Do NOT assume the internal Claude browser pane can do Google/GitHub OAuth — it crashed mid-flow; the real Chrome (via claude-in-chrome, the user's Browser 2) was used instead.

## Open Questions / Unresolved

- The user's Streamlit secrets still have `github_token = "COLE_O_TOKEN_GITHUB_AQUI"` (placeholder). The "Rodar busca agora" cloud button won't work until they paste a real fine-grained PAT (Contents + Actions RW, this repo). Login and daily search work without it.
- Only sgurfinkel1@gmail.com is a Google OAuth "test user", so only that account can log in. To add others: Google Cloud → Audience → Test users → Add users.
- The old Google client secret (ends `D7X_`) is still enabled alongside the new one; user was advised to disable/delete it for hygiene.

## Next Steps

1. If the user reports login issues again: check app logs via "Manage app" — `invalid_client` means the `client_secret` in Streamlit secrets is wrong/truncated (this exact bug happened twice: first a truncated value, then the placeholder was saved unreplaced).
2. Guide the user (do not do it yourself) to fill `github_token` if they want the on-demand cloud search button.
3. Coverage requests usually mean adding URLs to `paginas_concursos`/`paginas_privadas` in `config.yaml`, or terms to `termos_base` — the cheapest way to widen results.
4. A memory note exists at `~/.claude/projects/C--Users-Saul-Godoi/memory/academic-vagas-bot-project.md`; update it if project facts change.
