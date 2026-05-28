# Correção tela preta Streamlit Cloud

Arquivos ajustados para deploy:
- `runtime.txt` fixa Python 3.11
- `requirements.txt` com versões estáveis
- `.streamlit/config.toml` em tema claro
- módulos lendo `st.secrets` e `.env`

Suba tudo na raiz do GitHub e use `Main file path: app.py`.
Depois clique em `Manage app > Reboot app`.
