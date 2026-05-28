import io
import json
import time
import zipfile
from datetime import date
from typing import Any, Dict, List

import pandas as pd
import plotly.express as px
import streamlit as st

from api_raster_live import (
    GET_TABELA_NOMES,
    METHOD_REGISTRY,
    RasterClient,
    as_int,
    extract_documents,
    extract_values,
    make_download_json,
    period_previous_current_month,
    records_from_response,
)

st.set_page_config(page_title="Raster API — GET e Consultas", page_icon="🔎", layout="wide")

st.title("🔎 Raster API — Bases GET e Consultas")
st.caption("Consulta direta na API Raster, sem Supabase, sem métodos de inclusão/alteração. Somente métodos GET/consulta do manual.")


def secret_ok() -> bool:
    required = ["RASTER_BASE_URL", "RASTER_LOGIN", "RASTER_SENHA"]
    missing = []
    for k in required:
        try:
            if not st.secrets.get(k):
                missing.append(k)
        except Exception:
            import os
            if not os.getenv(k):
                missing.append(k)
    if missing:
        st.error("Configure os Secrets antes de rodar: " + ", ".join(missing))
        return False
    return True


if "results" not in st.session_state:
    st.session_state.results = {}
if "logs" not in st.session_state:
    st.session_state.logs = []


def log(msg: str, status: str = "INFO"):
    line = f"[{status}] {msg}"
    st.session_state.logs.insert(0, line)


def call_method(client: RasterClient, method: str, payload: Dict[str, Any], key: str | None = None, delay: float = 0.0) -> Dict[str, Any]:
    if delay > 0:
        time.sleep(delay)
    data = client.post(method, payload)
    store_key = key or method
    st.session_state.results[store_key] = data
    cod_erro = str(data.get("CodErro", "0"))
    if cod_erro not in ("0", "", "None"):
        log(f"{method}: erro {data.get('CodErro')} - {data.get('MsgErro')}", "ERRO")
    else:
        log(f"{method}: consulta finalizada", "OK")
    return data


def show_response(title: str, data: Dict[str, Any]):
    st.subheader(title)
    cod_erro = str(data.get("CodErro", "0"))
    if cod_erro not in ("0", "", "None"):
        st.warning(f"Raster retornou: {data.get('CodErro')} — {data.get('MsgErro')}")
    records = records_from_response(data)
    df = pd.DataFrame(records)
    if not df.empty:
        st.dataframe(df, use_container_width=True, height=360)
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("Baixar CSV", csv, file_name=f"{title.replace(' ', '_')}.csv", mime="text/csv", key=f"csv_{title}")
    with st.expander("Ver JSON bruto"):
        st.json(data)


def build_zip(results: Dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("raster_resultados_completos.json", make_download_json(results))
        for name, data in results.items():
            safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in name)[:80]
            z.writestr(f"json/{safe}.json", make_download_json(data))
            try:
                df = pd.DataFrame(records_from_response(data))
                if not df.empty:
                    z.writestr(f"csv/{safe}.csv", df.to_csv(index=False))
            except Exception:
                pass
    return buf.getvalue()


with st.sidebar:
    st.header("Configuração")
    if secret_ok():
        st.success("Secrets carregados")
    st.divider()
    data_ini_default, data_fim_default = period_previous_current_month()
    data_inicial = st.date_input("Data inicial", value=date.fromisoformat(data_ini_default))
    data_final = st.date_input("Data final", value=date.fromisoformat(data_fim_default))
    status_viagem = st.selectbox("Status viagem", ["T", "F", "A", "AB"], index=0, help="T=todas, F=finalizadas, A=andamento, AB=efetivada em aberto")
    limite_auto = st.number_input("Limite de encadeamento", min_value=1, max_value=500, value=50, step=1)
    delay_curto = st.number_input("Delay curto entre chamadas", min_value=0.0, max_value=30.0, value=1.0, step=0.5)
    delay_checklist = st.number_input("Delay checklist", min_value=0.0, max_value=60.0, value=12.0, step=1.0)

client = RasterClient()

abas = st.tabs([
    "🚀 Pacote automático",
    "📚 getTabela / Cadastros",
    "🚚 Viagens e documentos",
    "✅ Checklist",
    "🧪 Explorador manual",
    "📦 Resultados",
    "🖥️ Terminal",
])

with abas[0]:
    st.header("Pacote automático de bases GET/consulta")
    st.info("Roda somente consultas. Não chama setPreSM, setIncluirCheckList, setProgramacaoCargas ou qualquer método de inclusão/alteração.")
    col1, col2, col3 = st.columns(3)
    run_tabelas = col1.checkbox("getTabela — cadastros", value=True)
    run_viagens = col1.checkbox("getEventoFimViagem — período", value=True)
    run_status_docs = col2.checkbox("getStatusViagem por CARGA/CTE", value=True)
    run_posicoes = col2.checkbox("getPosicoes últimas", value=False)
    run_checklist = col3.checkbox("Checklist existente", value=False)
    run_km = col3.checkbox("getKMRodado", value=False)

    if st.button("▶️ Rodar pacote automático", type="primary", use_container_width=True):
        st.session_state.results = {}
        st.session_state.logs = []
        progress = st.progress(0)
        step = 0
        total_steps = (len(GET_TABELA_NOMES) if run_tabelas else 0) + 6

        if run_tabelas:
            for nome in GET_TABELA_NOMES:
                call_method(client, "getTabela", {"NomeTabela": nome}, key=f"getTabela_{nome}", delay=delay_curto)
                step += 1
                progress.progress(min(step / total_steps, 1.0))

        evento_data = {}
        docs: List[Dict[str, Any]] = []
        placas = []
        cod_solicitacoes = []
        cod_pre = []

        if run_viagens:
            evento_payload = {
                "DataInicial": data_inicial.isoformat(),
                "DataFinal": data_final.isoformat(),
                "StatusViagem": status_viagem,
            }
            evento_data = call_method(client, "getEventoFimViagem", evento_payload, key="getEventoFimViagem_periodo", delay=delay_curto)
            docs = extract_documents(evento_data)
            docs = [d for d in docs if d["Tipo"] in ("CARGA", "CTE", "CT-E", "SHIPMENT")][: int(limite_auto)]
            placas = extract_values(evento_data, ["Placa", "PlacaVeiculo", "Veiculo"])
            cod_solicitacoes = extract_values(evento_data, ["CodSolicitacao"])
            cod_pre = extract_values(evento_data, ["CodPreSolicitacao"])
            step += 1
            progress.progress(min(step / total_steps, 1.0))

        if run_status_docs and docs:
            for i, doc in enumerate(docs[: int(limite_auto)], start=1):
                call_method(client, "getStatusViagem", {"Documentos": [doc]}, key=f"getStatusViagem_{doc['Tipo']}_{doc['Numero']}", delay=delay_curto)
                step += 1
                progress.progress(min(step / max(total_steps + len(docs), 1), 1.0))
        elif run_status_docs:
            st.warning("Nenhum documento CARGA/CTE/SHIPMENT encontrado no getEventoFimViagem para encadear getStatusViagem.")

        if run_posicoes:
            call_method(client, "getPosicoes", {"TipoConsulta": "Ultimas", "CodUltPosicao": 0}, key="getPosicoes_ultimas", delay=delay_curto)

        if run_km:
            for placa in placas[: int(limite_auto)]:
                call_method(client, "getKMRodado", {"DataInicial": data_inicial.isoformat(), "DataFinal": data_final.isoformat(), "Placa": placa}, key=f"getKMRodado_{placa}", delay=delay_curto)

        if run_checklist:
            cod_filial = st.secrets.get("RASTER_COD_FILIAL", "") if hasattr(st, "secrets") else ""
            cod_perfil = st.secrets.get("RASTER_COD_PERFIL_SEGURANCA", "") if hasattr(st, "secrets") else ""
            produtos_raw = st.secrets.get("RASTER_PRODUTOS", "[]") if hasattr(st, "secrets") else "[]"
            try:
                produtos = json.loads(produtos_raw) if isinstance(produtos_raw, str) else produtos_raw
            except Exception:
                produtos = []
            # Usa histórico por veículo apenas para descobrir CodCheckList existente. Não cria nada.
            for placa in placas[: int(limite_auto)]:
                hist = call_method(client, "getHistoricoTestes", {"Veiculo": placa}, key=f"getHistoricoTestes_{placa}", delay=delay_curto)
                cods = extract_values(hist, ["CodCheckList", "CodChecklist", "cod_checklist"])
                for cod in cods[:3]:
                    payload = {"CodCheckList": cod, "CodFilial": cod_filial, "CodPerfilSeguranca": cod_perfil, "Produtos": produtos}
                    call_method(client, "getGerarResultadoCheckList", payload, key=f"getGerarResultadoCheckList_{cod}", delay=delay_checklist)

        progress.progress(1.0)
        st.success("Pacote automático finalizado.")

with abas[1]:
    st.header("📚 getTabela — cadastros/base de apoio")
    st.write("Consulta as tabelas de apoio do manual: filiais, perfil de segurança, produtos, erros, cidades, tecnologias etc.")
    selecionadas = st.multiselect("Tabelas", GET_TABELA_NOMES, default=["FILIAIS", "PERFIL_SEGURANCA", "PRODUTOS", "ERROS_WEBSERVICE"])
    if st.button("Consultar tabelas selecionadas", use_container_width=True):
        for nome in selecionadas:
            call_method(client, "getTabela", {"NomeTabela": nome}, key=f"getTabela_{nome}", delay=delay_curto)
    for nome in selecionadas:
        key = f"getTabela_{nome}"
        if key in st.session_state.results:
            show_response(key, st.session_state.results[key])

with abas[2]:
    st.header("🚚 Viagens, SM e documentos")
    st.write("Busca viagem/SM por período e também permite consultar por documentos CARGA, CTE, CT-E, SHIPMENT ou OUTROS.")
    c1, c2, c3 = st.columns(3)
    dt_ini = c1.date_input("Data inicial viagem", value=data_inicial, key="viagem_ini")
    dt_fim = c2.date_input("Data final viagem", value=data_final, key="viagem_fim")
    stv = c3.selectbox("Status", ["T", "F", "A", "AB"], index=0, key="viagem_status")
    if st.button("Consultar getEventoFimViagem", use_container_width=True):
        call_method(client, "getEventoFimViagem", {"DataInicial": dt_ini.isoformat(), "DataFinal": dt_fim.isoformat(), "StatusViagem": stv}, key="getEventoFimViagem_manual")
    if "getEventoFimViagem_manual" in st.session_state.results:
        data = st.session_state.results["getEventoFimViagem_manual"]
        show_response("getEventoFimViagem_manual", data)
        docs = extract_documents(data)
        if docs:
            st.subheader("Documentos encontrados")
            dfd = pd.DataFrame(docs)
            st.dataframe(dfd, use_container_width=True, height=260)
            if st.button("Consultar getStatusViagem para documentos encontrados", use_container_width=True):
                for doc in docs[: int(limite_auto)]:
                    call_method(client, "getStatusViagem", {"Documentos": [doc]}, key=f"getStatusViagem_{doc['Tipo']}_{doc['Numero']}", delay=delay_curto)

    st.divider()
    st.subheader("Consulta direta por documento")
    c1, c2 = st.columns(2)
    tipo_doc = c1.selectbox("Tipo", ["CARGA", "CTE", "CT-E", "SHIPMENT", "OUTROS"])
    numero_doc = c2.text_input("Número do documento")
    if st.button("Consultar getStatusViagem por documento", use_container_width=True):
        if numero_doc.strip():
            doc = {"Tipo": tipo_doc, "Numero": numero_doc.strip()}
            call_method(client, "getStatusViagem", {"Documentos": [doc]}, key=f"getStatusViagem_{tipo_doc}_{numero_doc.strip()}")
        else:
            st.warning("Informe o número do documento.")

with abas[3]:
    st.header("✅ Checklist existente")
    st.warning("Não cria checklist. Usa apenas getHistoricoTestes e getGerarResultadoCheckList para consultar o que já existe.")
    c1, c2, c3 = st.columns(3)
    veiculo = c1.text_input("Veículo/placa para histórico")
    cod_checklist = c2.text_input("CodCheckList para resultado")
    cod_filial = c3.text_input("CodFilial", value=str(st.secrets.get("RASTER_COD_FILIAL", "") if hasattr(st, "secrets") else ""))
    c4, c5 = st.columns(2)
    cod_perfil = c4.text_input("CodPerfilSeguranca", value=str(st.secrets.get("RASTER_COD_PERFIL_SEGURANCA", "") if hasattr(st, "secrets") else ""))
    produtos_raw = c5.text_area("Produtos JSON", value=str(st.secrets.get("RASTER_PRODUTOS", '[{"CodProduto":2134,"Valor":1}]') if hasattr(st, "secrets") else '[{"CodProduto":2134,"Valor":1}]'), height=90)
    if st.button("Consultar histórico de testes", use_container_width=True):
        if veiculo.strip():
            call_method(client, "getHistoricoTestes", {"Veiculo": veiculo.strip()}, key=f"getHistoricoTestes_{veiculo.strip()}")
        else:
            st.warning("Informe um veículo/placa.")
    if st.button("Consultar resultado oficial do checklist", use_container_width=True):
        try:
            produtos = json.loads(produtos_raw) if produtos_raw.strip() else []
        except Exception as exc:
            st.error(f"Produtos JSON inválido: {exc}")
            produtos = []
        payload = {"CodCheckList": cod_checklist.strip(), "CodFilial": cod_filial.strip(), "CodPerfilSeguranca": cod_perfil.strip(), "Produtos": produtos}
        if cod_checklist.strip():
            call_method(client, "getGerarResultadoCheckList", payload, key=f"getGerarResultadoCheckList_{cod_checklist.strip()}")
        else:
            st.warning("Informe o CodCheckList.")

with abas[4]:
    st.header("🧪 Explorador manual de métodos GET/consulta")
    st.write("Use para qualquer método de consulta listado no manual. Não há métodos set* nesta tela.")
    grupos = sorted(set(v["grupo"] for v in METHOD_REGISTRY.values()))
    grupo = st.selectbox("Grupo", grupos)
    metodos = [m for m, cfg in METHOD_REGISTRY.items() if cfg["grupo"] == grupo]
    metodo = st.selectbox("Método", metodos)
    default_payload = METHOD_REGISTRY[metodo].get("auto_payload", {})
    payload_text = st.text_area("Payload adicional JSON", value=json.dumps(default_payload, ensure_ascii=False, indent=2), height=220)
    if st.button("Executar método", use_container_width=True):
        try:
            payload = json.loads(payload_text) if payload_text.strip() else {}
            if not isinstance(payload, dict):
                st.error("O payload precisa ser um objeto JSON.")
            else:
                call_method(client, metodo, payload, key=f"manual_{metodo}_{len(st.session_state.results)}")
        except Exception as exc:
            st.error(f"JSON inválido: {exc}")

with abas[5]:
    st.header("📦 Resultados em memória")
    st.caption("Esses dados não são salvos no Supabase. Ficam apenas na sessão do Streamlit e podem ser baixados.")
    if st.session_state.results:
        st.download_button("Baixar ZIP com JSON/CSV", build_zip(st.session_state.results), file_name="raster_get_consultas_resultados.zip", mime="application/zip", use_container_width=True)
        selected = st.selectbox("Resultado", list(st.session_state.results.keys()))
        show_response(selected, st.session_state.results[selected])
    else:
        st.info("Nenhum resultado ainda.")

with abas[6]:
    st.header("🖥️ Terminal")
    if st.session_state.logs:
        st.code("\n".join(st.session_state.logs[:200]))
    else:
        st.info("Sem logs ainda.")
    if st.session_state.results:
        with st.expander("Últimas tentativas HTTP"):
            for k, data in list(st.session_state.results.items())[-5:]:
                st.write(k)
                st.json(data.get("_tentativas_http", []))
