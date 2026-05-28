# Arquivos para subir no Streamlit Cloud

Suba estes arquivos na raiz do repositório GitHub:

- app.py
- api_raster.py
- api_omnilink.py
- supabase_db.py
- requirements.txt
- supabase_schema.sql
- .streamlit/config.toml
- .gitignore

No Streamlit Cloud, configure o app assim:

- Branch: main
- Main file path: app.py

Secrets necessários no Streamlit Cloud:

DASHBOARD_USER = "Admin"
DASHBOARD_PASSWORD = "inicio@01A"

SUPABASE_URL = "https://ptcfszcwpebuutdrurbl.supabase.co"
SUPABASE_SERVICE_KEY = "SUA_SERVICE_ROLE_KEY"

RASTER_BASE_URL = "https://integra.logae.com.br/datasnap/rest/TWebService"
RASTER_LOGIN = "28150710000"
RASTER_SENHA = "SUA_SENHA_RASTER"
RASTER_AMBIENTE = "Producao"
RASTER_TIPO_RETORNO = "JSON"

RASTER_COD_FILIAL = "6278"
RASTER_COD_PERFIL_SEGURANCA = "14341"
RASTER_PRODUTOS = '[{"CodProduto":2134,"Valor":1}]'
RASTER_DELAY_CHECKLIST_SECONDS = "12"
RASTER_TIMEOUT_SECONDS = "20"
RASTER_ALLOW_UNQUOTED_URL = "1"

RASTER_EVENTO_FIM_DIAS = ""
RASTER_EVENTO_FIM_STATUS = "T"
RASTER_STATUS_VIAGEM_LIMITE = "50"
RASTER_DELAY_STATUS_VIAGEM_SECONDS = "1"

WSTT_USUARIO = "frota@cargoblue.com.br"
WSTT_SENHA = "SUA_SENHA_WSTT"

Importante: não suba .env com senhas no GitHub.
