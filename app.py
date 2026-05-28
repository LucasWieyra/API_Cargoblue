import pandas as pd
import streamlit as st

from api_raster_live import (
    previous_and_current_month,
    get_evento_fim_viagem,
    rows_sm_documentos,
    rows_status_by_documents,
    checklist_rows_by_documents,
)

st.set_page_config(page_title="Raster API Live", page_icon="🚚", layout="wide")

st.title("🚚 Raster API Live — SM, CARGA/CT-e e Checklist")
st.caption("Consulta direto na API da Raster, sem montar vínculo pelo Supabase. Preferência de documento: CARGA > CT-e.")

with st.sidebar:
    st.header("Filtros")
    di, df = previous_and_current_month()
    data_inicial = st.date_input("Data inicial", value=pd.to_datetime(di).date())
    data_final = st.date_input("Data final", value=pd.to_datetime(df).date())
    status = st.selectbox("Status viagem", ["T", "F", "A", "AB"], index=0, help="T=Todas, F=Finalizadas, A=Andamento, AB=Efetivada em aberto")
    apenas_carga_cte = st.toggle("Somente CARGA / CT-e", value=True)
    limite_docs_status = st.number_input("Limite documentos para getStatusViagem", min_value=1, max_value=200, value=25)
    limite_docs_check = st.number_input("Limite documentos para checklist", min_value=1, max_value=50, value=5)
    limite_check_por_doc = st.number_input("Checklists por documento", min_value=1, max_value=10, value=2)

if "sm_docs" not in st.session_state:
    st.session_state.sm_docs = []
if "status_docs" not in st.session_state:
    st.session_state.status_docs = []
if "check_docs" not in st.session_state:
    st.session_state.check_docs = []
if "last_raw" not in st.session_state:
    st.session_state.last_raw = None

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("1️⃣ Buscar SM + CARGA/CT-e", width="stretch"):
        with st.spinner("Consultando getEventoFimViagem na Raster..."):
            raw = get_evento_fim_viagem(str(data_inicial), str(data_final), status)
            st.session_state.last_raw = raw
            st.session_state.sm_docs = rows_sm_documentos(raw, only_operational=apenas_carga_cte)
            st.session_state.status_docs = []
            st.session_state.check_docs = []

with col2:
    if st.button("2️⃣ Consultar viagens por documentos", width="stretch"):
        if not st.session_state.sm_docs:
            st.warning("Rode primeiro a busca de SM + CARGA/CT-e.")
        else:
            with st.spinner("Consultando getStatusViagem por CARGA/CT-e..."):
                st.session_state.status_docs = rows_status_by_documents(st.session_state.sm_docs, int(limite_docs_status))

with col3:
    if st.button("3️⃣ Consultar checklist dos documentos", width="stretch"):
        if not st.session_state.status_docs:
            st.warning("Rode primeiro a consulta de viagens por documentos.")
        else:
            with st.spinner("Consultando checklist pela trilha Documento → Viagem → API Checklist..."):
                st.session_state.check_docs = checklist_rows_by_documents(
                    st.session_state.status_docs,
                    limit_docs=int(limite_docs_check),
                    limit_checklists_per_doc=int(limite_check_por_doc),
                )

st.divider()

c1, c2, c3 = st.columns(3)
c1.metric("SM + documentos", len(st.session_state.sm_docs))
c2.metric("Status por documento", len(st.session_state.status_docs))
c3.metric("Checklist por documento", len(st.session_state.check_docs))

st.subheader("1. SM com CARGA / CT-e")
if st.session_state.sm_docs:
    df = pd.DataFrame(st.session_state.sm_docs)
    cols = ["sm", "cod_pre_solicitacao", "tipo_documento", "numero_documento", "status_viagem", "status_checklist_viagem", "data_real_inicio", "data_real_fim", "origem"]
    st.dataframe(df[[c for c in cols if c in df.columns]], width="stretch", height=360)
    st.download_button("Baixar SM + documentos CSV", df.to_csv(index=False).encode("utf-8-sig"), "sm_documentos_api.csv", "text/csv", width="stretch")
else:
    st.info("Sem dados ainda. Clique em 'Buscar SM + CARGA/CT-e'.")

st.subheader("2. Viagem consultada por documento — getStatusViagem")
if st.session_state.status_docs:
    df = pd.DataFrame(st.session_state.status_docs)
    cols = ["sm", "cod_pre_solicitacao", "tipo_documento", "numero_documento", "status_viagem", "status_checklist_viagem", "placa_veiculo_api", "origem"]
    st.dataframe(df[[c for c in cols if c in df.columns]], width="stretch", height=320)
    st.download_button("Baixar status por documento CSV", df.to_csv(index=False).encode("utf-8-sig"), "status_viagem_documentos_api.csv", "text/csv", width="stretch")
else:
    st.info("Sem dados ainda. Clique em 'Consultar viagens por documentos'.")

st.subheader("3. Checklist com CARGA / CT-e")
st.caption("A saída fica vinculada ao documento/SM. A placa só é usada internamente quando a API da Raster exige para localizar histórico de checklist.")
if st.session_state.check_docs:
    df = pd.DataFrame(st.session_state.check_docs)
    cols = ["sm", "tipo_documento", "numero_documento", "cod_checklist", "status_checklist", "resultado", "apto", "data_geracao", "data_expiracao", "url_documento", "observacao"]
    st.dataframe(df[[c for c in cols if c in df.columns]], width="stretch", height=360)
    st.download_button("Baixar checklist por documento CSV", df.to_csv(index=False).encode("utf-8-sig"), "checklist_documentos_api.csv", "text/csv", width="stretch")
else:
    st.info("Sem dados ainda. Clique em 'Consultar checklist dos documentos'.")

with st.expander("Diagnóstico técnico do último retorno da Raster"):
    st.json(st.session_state.last_raw or {})

st.divider()
st.caption("Sem gravação obrigatória no Supabase. Esta tela monta as relações em memória a partir das respostas da API.")
