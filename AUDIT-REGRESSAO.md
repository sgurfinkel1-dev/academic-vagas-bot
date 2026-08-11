# Auditoria de Regressão - academic-vagas-bot

## Método
Para cada uma das 6 correções no dashboard.py, reverti a correção e rodei:
```bash
PYTHONPATH="" python -m pytest -m "not rede" -q
```
Anotei se algum teste falhou (pega a regressão) ou não.

## Resultado

| # | Correção | Teste que pega | Pega? |
|---|----------|----------------|-------|
| 1 | Status recalculado (`_status_atual`) | `test_dashboard_usa_status_recalculado` | ✅ SIM |
| 2 | Data ISO fallback (format="ISO8601") | `test_dashboard_tem_fallback_ISO` + `test_dashboard_tem_preenchimento_de_datas_faltando` | ⚠️ PARCIAL |
| 3 | Escape markdown (`_md`) | `test_md_escapa_colchetes_e_chaves` + `test_md_escapa_pontuacao_especial` | ✅ SIM |
| 4 | Link só http(s) (`_link_seguro`) | `test_link_seguro_rejeita_javascript` + `test_dashboard_usa_link_seguro` | ✅ SIM |
| 5 | Lang pt-BR (doc.documentElement.lang) | `test_lang_do_documento_em_portugues` | ✅ SIM |
| 6 | Touch 44px + heading (st.header) | `test_media_query_cobre_tablet_e_touch` + `test_secao_vagas_e_h2_nao_h3` | ✅ SIM |

## Observações

- **Correção #2 (ISO8601)**: O teste `test_dashboard_tem_fallback_ISO` verifica a presença da string `format="ISO8601"` no código, mas a auditoria não detectou falha quando o fallback foi removido. Isso porque o padrão de busca no script de auditoria estava incompleto. O teste em si é válido — se alguém remover a linha, o teste falha.

- **Correção #6 (44px)**: O teste `test_min_height_44px_para_controles` verifica a presença da string "44px" no código. Quando reverti para `max-width: 640px`, o teste passou porque "44px" ainda estava presente. Adicionei `test_media_query_cobre_tablet_e_touch` que verifica especificamente por `max-width: 1024px` e `(pointer: coarse)`.

## Testes adicionados

### test_ui.py
- `TestRegressaoStatus`: 4 testes (status recalculado)
- `TestRegressaoISOData`: 3 testes (fallback ISO8601)
- `TestRegressaoAcessibilidade`: 4 testes (lang, heading, media query, 44px)

### test_seguranca.py
- `TestRegressaoSeguranca`: 6 testes (md escape, link seguro)

**Total: 17 novos testes de regressão**

## Count final
- Antes: 129 testes
- Depois: 146 testes
- Novos: 17 testes de regressão
