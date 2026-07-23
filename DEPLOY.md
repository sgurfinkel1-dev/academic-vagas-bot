# Deploy na nuvem (grátis): busca automática + dashboard com login Google

Arquitetura:
- **GitHub Actions** roda a busca sozinho no horário agendado (sem seu PC ligado) e salva os resultados no repositório.
- **Streamlit Community Cloud** hospeda o dashboard, com **login Google** e link para compartilhar.
- O painel **⚙️ Busca automática** no dashboard salva áreas/período e pode disparar a busca na hora.

Siga na ordem. Onde disser "copie", guarde o valor para um passo adiante.

## 1. Subir o código para o GitHub
1. Crie um repositório em https://github.com/new — nome `academic-vagas-bot` (pode ser **Private**).
2. No terminal, dentro da pasta do projeto:
   ```bash
   git remote add origin https://github.com/SEU_USUARIO/academic-vagas-bot.git
   git push -u origin main
   ```
3. Em **Settings → Actions → General → Workflow permissions**, marque **Read and write permissions** (deixa o robô commitar os resultados).

A busca já passa a rodar todo dia às 07:00 (BRT). Para rodar na hora: aba **Actions → Busca diária → Run workflow**.

## 2. Criar o login Google (OAuth)
1. Acesse https://console.cloud.google.com → crie um projeto (ou use um existente).
2. **APIs e serviços → Tela de consentimento OAuth**: tipo **Externo**, preencha nome do app e seu e-mail. Em "Usuários de teste", adicione os e-mails que poderão entrar.
3. **APIs e serviços → Credenciais → Criar credenciais → ID do cliente OAuth**:
   - Tipo: **Aplicativo da Web**.
   - **URIs de redirecionamento autorizados**: `https://SEU-APP.streamlit.app/oauth2callback`
     (você define o nome `SEU-APP` no passo 3; volte aqui e ajuste se necessário.)
   - Copie o **Client ID** e o **Client secret**.

## 3. Publicar o dashboard no Streamlit Cloud
1. Acesse https://share.streamlit.io → **New app** → conecte sua conta GitHub.
2. Repositório `academic-vagas-bot`, branch `main`, arquivo `dashboard.py`. Anote a URL final (`https://SEU-APP.streamlit.app`) e ajuste o redirect do passo 2 se mudou.
3. Em **App → Settings → Secrets**, cole o conteúdo de [.streamlit/secrets.toml.example](.streamlit/secrets.toml.example) preenchido:
   - `[auth]` com o Client ID/secret do passo 2, o `redirect_uri` da sua URL e um `cookie_secret` aleatório.
   - `github_repo` = `SEU_USUARIO/academic-vagas-bot`.
   - `github_token` = um **Fine-grained PAT** (https://github.com/settings/tokens?type=beta) com acesso só a este repo e permissões **Contents: Read and write** + **Actions: Read and write** (habilita salvar a agenda e o botão "Rodar busca agora").
4. Salve. O app reinicia e passa a exigir login Google.

## Pronto
- Dashboard: `https://SEU-APP.streamlit.app` (compartilhe com quem estiver na lista de usuários de teste).
- Configurar áreas/período: painel **⚙️ Busca automática** na barra lateral → **Salvar**.
- Rodar na hora: botão **☁️ Rodar busca completa agora**.
- Mudar o horário/frequência: edite o `cron` em [.github/workflows/daily.yml](.github/workflows/daily.yml).

Alertas (Telegram/Discord/e-mail) são opcionais: adicione os secrets correspondentes em
**Settings → Secrets and variables → Actions** do GitHub (não no Streamlit).
