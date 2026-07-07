# academic-vagas-bot

Robô gratuito (Python) que monitora vagas de **professor, pesquisador e pós-doutorado** no Brasil, classifica a instituição (federal / estadual / municipal / privada / instituto / agência), deduplica, exporta CSV/JSON/Markdown e mostra tudo num **dashboard com filtros**.

## Fontes e status
| Fonte | Como | Status |
|---|---|---|
| Universidades públicas | páginas oficiais de concursos listadas em `config.yaml` | ✅ funcionando |
| FAPESP | página de Oportunidades | ✅ funcionando |
| DOU | busca pública do in.gov.br (seção 3) com retry | ⚠️ o endpoint oscila (502/timeout); alternativa robusta: INLABS ou [Ro-DOU](https://github.com/gestaogovbr/Ro-dou) |
| Diários municipais | API do [Querido Diário](https://queridodiario.ok.org.br) | ⚠️ atrás de challenge Cloudflare para clientes sem navegador |
| Busca aberta | Bing/DDG | ❌ desligada por padrão — buscadores servem captcha a scrapers; plugue uma API (SerpAPI tem tier grátis) |
| INLABS / privadas | stubs comentados nos módulos | 🔧 opcional |

Para ampliar a cobertura, o caminho de melhor custo/benefício é **adicionar mais páginas oficiais de concursos** em `paginas_concursos` no `config.yaml` (funciona para qualquer universidade/instituto, público ou privado).

## Uso
```bash
cd academic-vagas-bot
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt

# editar config.yaml (áreas, estados, canal de alerta) e rodar:
python -m src.main

# dashboard com filtros:
streamlit run dashboard.py
```

## Alertas
Configure via variáveis de ambiente (ou `config.yaml`):
- Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Discord: `DISCORD_WEBHOOK_URL`
- E-mail: `SMTP_USER`, `SMTP_PASS`

## Agendamento
`.github/workflows/daily.yml` roda todo dia às 07:00 BRT no GitHub Actions (grátis), commita os resultados e dispara alertas via secrets do repositório.

## Saídas
- `data/processed/vagas.db` — banco SQLite (dedup por hash do link/edital)
- `data/processed/vagas.csv`, `vagas.json`, `vagas.md`

## Qualidade
- Só entram vagas com fonte identificável; busca aberta entra com `confianca: baixo`.
- Vagas vencidas são filtradas (mude `incluir_vencidas: true` no config).
- Classificação por regras em `src/extractors/llm_classifier.py`; incertezas viram "verificar manualmente".
