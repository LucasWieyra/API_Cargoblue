import os
import json
import uuid
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
except Exception:
    st_autorefresh = None
from dotenv import load_dotenv

# Imports pesados carregados depois do login para evitar tela branca no Streamlit Cloud.
api_omnilink = None
api_raster = None
select_rows = None
test_connection = None

load_dotenv()


def load_project_modules():
    """Carrega APIs e Supabase somente depois da tela de login aparecer.
    Isso evita tela branca quando alguma lib/API demora no import no Streamlit Cloud.
    """
    global api_omnilink, api_raster, select_rows, test_connection
    if api_omnilink is not None and api_raster is not None and select_rows is not None:
        return
    import api_omnilink as _api_omnilink
    import api_raster as _api_raster
    from supabase_db import select_rows as _select_rows, test_connection as _test_connection
    api_omnilink = _api_omnilink
    api_raster = _api_raster
    select_rows = _select_rows
    test_connection = _test_connection


def get_config(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, None)
        if value is not None:
            return str(value).strip().strip('"')
    except Exception:
        pass
    return (os.getenv(name, default) or default).strip().strip('"')

# Disponibiliza secrets também como variáveis de ambiente para módulos auxiliares.
try:
    for _k, _v in st.secrets.items():
        os.environ.setdefault(str(_k), str(_v))
except Exception:
    pass
    
st.success("✅ App carregado no Streamlit Cloud")
st.set_page_config(
    page_title="Central Raster + Omnilink",
    page_icon="🚚",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS = """
<style>
/* SAFE MODE: sem CSS de fundo/cor para não deixar tela branca/preta no Streamlit Cloud. */
.block-container { max-width: 1520px; padding-top: 1rem; padding-bottom: 2rem; }
.terminal-box { white-space: pre-wrap; font-family: monospace; font-size: 12px; border: 1px solid rgba(128,128,128,.25); border-radius: 10px; padding: 12px; overflow:auto; }
.kpi-card, .panel, .sync-card, .metric-tile { border: 1px solid rgba(128,128,128,.25); border-radius: 16px; padding: 14px; margin-bottom: 8px; }
.kpi-value { font-size: 28px; font-weight: 800; }
.kpi-label, .kpi-help, .section-desc, .small-muted { opacity: .75; }
.hero-title { font-size: 34px; font-weight: 800; }
.badge { display:inline-block; padding: 4px 10px; border: 1px solid rgba(128,128,128,.25); border-radius: 999px; margin: 4px 4px 4px 0; }
.info-box, .warn-box, .auto-box { border: 1px solid rgba(128,128,128,.25); border-radius: 12px; padding: 12px; margin-bottom: 10px; }
</style>
"""
#st.markdown(CSS, unsafe_allow_html=True)
st.caption("✅ App carregado no Streamlit Cloud")


def require_login() -> bool:
    user_ok = get_config("DASHBOARD_USER", "Admin")
    pass_ok = get_config("DASHBOARD_PASSWORD", "inicio@01A")
    if "auth_ok" not in st.session_state:
        st.session_state.auth_ok = False
    if st.session_state.auth_ok:
        return True

    st.markdown("<div class='hero'>", unsafe_allow_html=True)
    st.markdown("<div class='hero-grid'>", unsafe_allow_html=True)
    st.markdown("<div class='logo-wrap'>🚚</div>", unsafe_allow_html=True)
    st.markdown(
        "<div><div class='hero-title'>Central de Integrações</div>"
        "<p class='hero-subtitle'>Raster + Omnilink/WSTT • Operação, telemetria, viagens e análises em um só lugar.</p>"
        "<div><span class='badge ok'>Supabase</span><span class='badge info'>Raster</span><span class='badge info'>Omnilink/WSTT</span></div>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("</div></div>", unsafe_allow_html=True)

    st.write("")
    c1, c2, c3 = st.columns([1, 1, 1])
    with c2:
        with st.container(border=True):
            st.subheader("Acesso")
            with st.form("login"):
                usuario = st.text_input("Usuário")
                senha = st.text_input("Senha", type="password")
                entrar = st.form_submit_button("Entrar", use_container_width=True)
            if entrar:
                if usuario == user_ok and senha == pass_ok:
                    st.session_state.auth_ok = True
                    st.rerun()
                else:
                    st.error("Usuário ou senha inválidos.")
    return False


def metric_card(label: str, value, help_text: str | None = None):
    st.markdown(
        f"<div class='kpi-card'><div class='kpi-label'>{label}</div><div class='kpi-value'>{value}</div>"
        + (f"<div class='kpi-help'>{help_text}</div>" if help_text else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def safe_int(value, default: int = 0) -> int:
    try:
        if pd.isna(value):
            return default
        return int(float(value))
    except Exception:
        return default


def safe_float(value, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


CHECKLIST_STATUS_DESC = {
    "ST": "Sem teste",
    "AI": "Aguardando início",
    "AE": "Aguardando espelhamento",
    "CV": "Configurando veículo",
    "ET": "Teste em execução",
    "FI": "Finalizado",
    "CA": "Cancelado",
    "SEM_STATUS": "Sem status",
}


def add_checklist_status_desc(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "status" not in df.columns:
        return df
    out = df.copy()
    out["status_descricao"] = out["status"].fillna("SEM_STATUS").astype(str).map(CHECKLIST_STATUS_DESC).fillna("Status não mapeado")
    return out


def checklist_status_summary(df: pd.DataFrame):
    if df.empty or "status" not in df.columns:
        return
    tmp = add_checklist_status_desc(df)
    resumo = (
        tmp.groupby(["status", "status_descricao"], dropna=False)
        .size()
        .reset_index(name="qtd")
        .sort_values("qtd", ascending=False)
    )
    c1, c2 = st.columns([0.62, 0.38])
    with c1:
        try:
            fig = px.bar(resumo, x="status_descricao", y="qtd", text="qtd", title="Resumo por status do checklist")
            fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=320, xaxis_title="", yaxis_title="Qtd")
            st.plotly_chart(fig, use_container_width=True)
        except Exception:
            pass
    with c2:
        st.dataframe(resumo, use_container_width=True, hide_index=True, height=320)


def header():
    st.markdown("<div class='hero'>", unsafe_allow_html=True)
    cols = st.columns([0.12, 0.88])
    with cols[0]:
        st.markdown("<div class='logo-wrap' style='font-size:42px;width:88px;height:88px;'>🚚</div>", unsafe_allow_html=True)
    with cols[1]:
        st.markdown("<div class='hero-title'>Central Raster + Omnilink/WSTT</div>", unsafe_allow_html=True)
        st.markdown(
            "<p class='hero-subtitle'>Sincronização separada das APIs, visão executiva, análise operacional por placa e estrutura Supabase organizada.</p>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<span class='badge ok'>Layout premium</span>"
            "<span class='badge info'>Layout organizado</span>"
            "<span class='badge info'>Sincronizações separadas</span>"
            "<span class='badge warn'>Detalhamento por placa</span>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p class='hero-caption'>Use o menu lateral para navegar entre visão executiva, Raster, Omnilink/WSTT, análises e SQL da estrutura.</p>",
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)
    st.write("")


def df_table(table: str, columns: str = "*", limit: int = 5000, order_by: str | None = None) -> pd.DataFrame:
    try:
        data = select_rows(table, columns, limit=limit, order_by=order_by)
        return pd.DataFrame(data)
    except Exception as exc:
        st.error(f"Erro ao consultar {table}: {exc}")
        return pd.DataFrame()


def style_aptidao(row):
    color = ""
    value = str(row.get("aptidao_operacional", ""))
    if value == "APTO":
        color = "background-color: rgba(34,197,94,.18); color:#BBF7D0; font-weight:700;"
    elif value == "NAO_APTO":
        color = "background-color: rgba(239,68,68,.18); color:#FECACA; font-weight:700;"
    elif value in ("PENDENTE", "INDEFINIDO", "SEM_STATUS"):
        color = "background-color: rgba(245,158,11,.18); color:#FDE68A; font-weight:700;"
    return [color if col == "aptidao_operacional" else "" for col in row.index]


def normalize_plate_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.upper().str.replace("-", "", regex=False).str.replace(" ", "", regex=False)


def apply_filters(df: pd.DataFrame, plate_filter: str = "", search_text: str = "") -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if plate_filter:
        plate_cols = [c for c in out.columns if "placa" in c.lower() or c.lower() == "veiculo"]
        if plate_cols:
            mask = False
            for col in plate_cols:
                try:
                    mask = mask | normalize_plate_series(out[col]).str.contains(plate_filter, na=False)
                except Exception:
                    pass
            out = out[mask] if not isinstance(mask, bool) else out
    if search_text:
        txt = search_text.lower().strip()
        mask = out.astype(str).apply(lambda row: row.str.lower().str.contains(txt, na=False)).any(axis=1)
        out = out[mask]
    return out



def dataframe_arrow_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Converte colunas com dict/list em texto para evitar erro do Streamlit/Arrow."""
    if df.empty:
        return df
    safe = df.copy()
    for col in safe.columns:
        if safe[col].dtype == "object":
            def normalize_cell(value):
                if isinstance(value, (dict, list, tuple, set)):
                    try:
                        return json.dumps(value, ensure_ascii=False, default=str)
                    except Exception:
                        return str(value)
                return value
            safe[col] = safe[col].map(normalize_cell)
    return safe

def show_dataframe(df: pd.DataFrame, height: int = 420, style: bool = False, plate_filter: str = "", search_text: str = ""):
    if df.empty:
        st.info("Sem dados para exibir ainda.")
        return
    filtered = apply_filters(df, plate_filter=plate_filter, search_text=search_text)
    if filtered.empty:
        st.warning("Nenhum registro encontrado com os filtros aplicados.")
        return

    filtered = dataframe_arrow_safe(filtered)

    c1, c2 = st.columns([0.82, 0.18])
    with c1:
        st.caption(f"{len(filtered):,} registro(s) exibidos".replace(",", "."))
    with c2:
        st.download_button(
            "Baixar CSV",
            data=filtered.to_csv(index=False).encode("utf-8-sig"),
            file_name="dados.csv",
            mime="text/csv",
            use_container_width=True,
            key=f"download_csv_{uuid.uuid4().hex}",
        )
    if style and "aptidao_operacional" in filtered.columns:
        st.dataframe(filtered.style.apply(style_aptidao, axis=1), use_container_width=True, hide_index=True, height=height)
    else:
        st.dataframe(filtered, use_container_width=True, hide_index=True, height=height)


def periodo_inputs(prefix: str, default_days: int = 2):
    c1, c2 = st.columns(2)
    with c1:
        ini = st.date_input("Data início", value=date.today() - timedelta(days=default_days), key=f"{prefix}_ini")
    with c2:
        fim = st.date_input("Data fim", value=date.today(), key=f"{prefix}_fim")
    return ini, fim


def mini_metrics(items: list[tuple[str, str | int | float]]):
    tiles = []
    for label, value in items:
        tiles.append(f"<div class='metric-tile'><div class='metric-tile-label'>{label}</div><div class='metric-tile-value'>{value}</div></div>")
    st.markdown(f"<div class='metric-strip'>{''.join(tiles)}</div>", unsafe_allow_html=True)


def metros_para_km(valor):
    """Converte metros para KM apenas na camada visual do dashboard."""
    return round(safe_float(valor) / 1000, 2)


def format_km(valor) -> str:
    return f"{metros_para_km(valor):,.2f} km".replace(",", "X").replace(".", ",").replace("X", ".")


def terminal_log(msg: str, level: str = "INFO") -> None:
    """Registra mensagens visuais do terminal interno do dashboard."""
    if "terminal_logs" not in st.session_state:
        st.session_state.terminal_logs = []
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    st.session_state.terminal_logs.append(f"[{timestamp}] {level.upper()} • {msg}")
    st.session_state.terminal_logs = st.session_state.terminal_logs[-250:]


def render_terminal_block(height: int = 320, include_db_logs: bool = True) -> None:
    linhas = []
    if "terminal_logs" in st.session_state and st.session_state.terminal_logs:
        linhas.extend(st.session_state.terminal_logs[-80:])
    if include_db_logs:
        try:
            db_logs = select_rows("integracao_execucoes", "origem,rotina,status,qtd_registros,executado_em", 40, order_by="executado_em")
            if db_logs:
                linhas.append("\n--- Últimas execuções gravadas no Supabase ---")
                for item in db_logs[:40]:
                    erro = item.get("erro")
                    detalhe = f" | erro: {erro}" if erro else ""
                    linhas.append(
                        f"[{item.get('executado_em')}] {item.get('origem')} • {item.get('rotina')} • {item.get('status')} • {item.get('qtd_registros')} registro(s){detalhe}"
                    )
        except Exception as exc:
            linhas.append(f"[terminal] Não foi possível consultar logs do Supabase: {exc}")

    if not linhas:
        linhas = ["Aguardando execução das APIs...", "Quando você sincronizar Raster ou Omnilink/WSTT, os eventos aparecem aqui."]
    conteudo = "\n".join(str(x) for x in linhas)
    st.markdown(f"<div class='terminal-box' style='max-height:{height}px'>{conteudo}</div>", unsafe_allow_html=True)


def sidebar_terminal_preview() -> None:
    with st.sidebar.expander("🖥️ Terminal", expanded=False):
        if st.button("Limpar terminal", use_container_width=True, key="btn_clear_terminal_sidebar"):
            st.session_state.terminal_logs = []
            st.rerun()
        render_terminal_block(height=230, include_db_logs=False)


def wstt_df_para_dashboard(df: pd.DataFrame) -> pd.DataFrame:
    """A API Omnilink/WSTT entrega distâncias em metros. Aqui convertemos só para exibição."""
    if df.empty:
        return df
    out = df.copy()
    colunas_distancia = {
        "km_total": "km_total_km",
        "distancia_total_percorrida": "distancia_total_percorrida_km",
        "distancia_total": "distancia_total_km",
    }
    for origem, destino in colunas_distancia.items():
        if origem in out.columns:
            out[destino] = pd.to_numeric(out[origem], errors="coerce").fillna(0) / 1000
    return out


def auto_cycle(rotinas: list[str], dias_viagens: int, dias_telemetria: int, limite_placas: int) -> list[str]:
    logs: list[str] = []
    hoje = date.today()

    # Ordem segura do ciclo automático:
    # 1) Raster operacional; 2) Omnilink/WSTT; 3) Checklist Raster SOMENTE CONSULTA.
    # O checklist fica no final para aproveitar placas/frota atualizadas no mesmo ciclo.
    if "Raster SM" in rotinas:
        terminal_log("Iniciando Raster • SM abertas")
        qtd = api_raster.sync_sm_abertas()
        logs.append(f"Raster SM abertas: {qtd}")
        terminal_log(f"Finalizado Raster • SM abertas: {qtd} registro(s)", "OK")

    if "Raster viagens" in rotinas:
        terminal_log("Iniciando Raster • viagens finalizadas")
        try:
            qtd = api_raster.sync_evento_fim_viagem()
            logs.append(f"Raster viagens finalizadas: {qtd}")
            terminal_log(f"Finalizado Raster • viagens finalizadas: {qtd} registro(s)", "OK")
        except Exception as exc:
            logs.append(f"Raster viagens finalizadas: ignorada por erro ({exc})")
            terminal_log(f"Erro Raster • viagens finalizadas: {exc}", "ERRO")

    if "Raster status viagem" in rotinas:
        terminal_log("Iniciando Raster • status viagem")
        qtd = api_raster.sync_status_viagem(limite=limite_placas)
        logs.append(f"Raster status viagem: {qtd}")
        terminal_log(f"Finalizado Raster • status viagem: {qtd} registro(s)", "OK")

    if "WSTT frota" in rotinas:
        terminal_log("Iniciando WSTT • frota")
        qtd = api_omnilink.sync_veiculos()
        logs.append(f"WSTT frota: {qtd}")
        terminal_log(f"Finalizado WSTT • frota: {qtd} registro(s)", "OK")

    if "WSTT viagens" in rotinas:
        terminal_log("Iniciando WSTT • viagens")
        qtd = api_omnilink.sync_viagens(hoje - timedelta(days=dias_viagens), hoje, limite_placas)
        logs.append(f"WSTT viagens: {qtd}")
        terminal_log(f"Finalizado WSTT • viagens: {qtd} registro(s)", "OK")

    if "WSTT telemetria" in rotinas:
        terminal_log("Iniciando WSTT • telemetria")
        qtd = api_omnilink.sync_telemetria(hoje - timedelta(days=dias_telemetria), hoje)
        logs.append(f"WSTT telemetria: {qtd}")
        terminal_log(f"Finalizado WSTT • telemetria: {qtd} registro(s)", "OK")

    if "WSTT eventos" in rotinas:
        terminal_log("Iniciando WSTT • eventos")
        qtd = api_omnilink.sync_eventos(hoje - timedelta(days=dias_telemetria), hoje, 2)
        logs.append(f"WSTT eventos: {qtd}")
        terminal_log(f"Finalizado WSTT • eventos: {qtd} registro(s)", "OK")

    if "Raster checklist existente válido" in rotinas:
        terminal_log("Iniciando Raster • checklist somente consulta")
        res = api_raster.sync_checklist_fluxo_automatico(limite=limite_placas)
        resultado = res.get("resultado", {}) if isinstance(res, dict) else {}
        logs.append(
            "Raster checklist consulta: "
            f"histórico={res.get('historico_codchecklist', 0) if isinstance(res, dict) else 0} "
            f"consultados={resultado.get('consultados', 0) if isinstance(resultado, dict) else 0} "
            f"salvos={resultado.get('salvos', 0) if isinstance(resultado, dict) else 0} "
            f"válidos={resultado.get('validos', 0) if isinstance(resultado, dict) else 0}"
        )
        terminal_log(f"Finalizado Raster • checklist somente consulta: {res}", "OK")

    return logs


def controle_automatico():
    st.sidebar.divider()
    st.sidebar.markdown("#### Execução automática")
    if "auto_api_on" not in st.session_state:
        st.session_state.auto_api_on = False
    if "auto_last_run" not in st.session_state:
        st.session_state.auto_last_run = None
    if "auto_last_log" not in st.session_state:
        st.session_state.auto_last_log = []

    c1, c2 = st.sidebar.columns(2)
    with c1:
        if st.button("Iniciar", use_container_width=True):
            st.session_state.auto_api_on = True
            st.session_state.auto_last_run = None
            st.rerun()
    with c2:
        if st.button("Parar", use_container_width=True):
            st.session_state.auto_api_on = False
            st.rerun()

    intervalo_min = st.sidebar.number_input("Intervalo", min_value=15, max_value=240, value=30, step=5, help="Intervalo em minutos entre cada ciclo automático. Mínimo 15 min para respeitar limites da Raster.")
    limite_auto = st.sidebar.number_input("Limite placas auto", min_value=1, max_value=500, value=50, step=10)
    dias_viagens_auto = st.sidebar.number_input("Dias viagens", min_value=1, max_value=30, value=7, step=1)
    dias_tele_auto = st.sidebar.number_input("Dias telemetria/eventos", min_value=1, max_value=3, value=1, step=1)
    rotinas_auto = st.sidebar.multiselect(
        "Rotinas",
        [
            "Raster SM",
            "Raster viagens",
            "Raster status viagem",
            "Raster checklist existente válido",
            
            "WSTT frota",
            "WSTT viagens",
            "WSTT telemetria",
            "WSTT eventos",
        ],
        default=["Raster SM", "Raster status viagem", "Raster checklist existente válido", "WSTT frota", "WSTT viagens", "WSTT telemetria", "WSTT eventos"],
    )

    st.sidebar.caption("Automático inclui StatusViagem e checklist somente consulta. Não cria checklist e usa período automático mês anterior + mês atual para eventos Raster.")

    if st.session_state.auto_api_on:
        st.sidebar.success("Automático ligado")
        if st_autorefresh is not None:
            st_autorefresh(interval=60 * 1000, key="auto_refresh_tick")
        else:
            st.sidebar.warning("Instale streamlit-autorefresh para atualização automática mais suave.")

        agora = datetime.now(timezone.utc)
        ultimo = st.session_state.auto_last_run
        intervalo_seg = int(intervalo_min) * 60
        deve_rodar = ultimo is None or (agora - ultimo).total_seconds() >= intervalo_seg
        if deve_rodar and rotinas_auto:
            with st.spinner("Executando ciclo automático das APIs..."):
                try:
                    logs = auto_cycle(rotinas_auto, int(dias_viagens_auto), int(dias_tele_auto), int(limite_auto))
                    st.session_state.auto_last_log = logs
                    st.session_state.auto_last_run = agora
                    st.toast("Ciclo automático concluído", icon="✅")
                except Exception as exc:
                    terminal_log(f"Erro no ciclo automático: {exc}", "ERRO")
                    st.session_state.auto_last_log = [f"Erro: {exc}"]
                    st.session_state.auto_last_run = agora
                    st.toast("Erro no ciclo automático", icon="⚠️")
        if st.session_state.auto_last_run:
            st.sidebar.caption("Última execução: " + st.session_state.auto_last_run.astimezone().strftime("%d/%m/%Y %H:%M:%S"))
        if st.session_state.auto_last_log:
            with st.sidebar.expander("Último ciclo"):
                for item in st.session_state.auto_last_log:
                    st.write(item)
    else:
        st.sidebar.info("Automático desligado")


def fallback_raster_status() -> pd.DataFrame:
    viagens = df_table("raster_evento_fim_viagem", "placa_veiculo,status_checklist,aptidao_operacional,dentro_prazo,desvios_rota,eventos_velocidade,synced_at", 20000, "synced_at")
    if viagens.empty:
        return pd.DataFrame()
    viagens = viagens.sort_values("synced_at", ascending=False)
    viagens = viagens.drop_duplicates(subset=["placa_veiculo"])
    viagens = viagens.rename(columns={"placa_veiculo": "placa", "synced_at": "ultima_sincronizacao"})
    return viagens


def fallback_wstt_resumo() -> pd.DataFrame:
    viagens = df_table("wstt_viagens_telemetria", "placa,distancia_total_percorrida,quantidade_excesso_velocidade,quantidade_freada_brusca,quantidade_aceleracao_brusca", 20000)
    eventos = df_table("wstt_eventos_tracker_telemetria2", "placa,velocidade_maxima,evento_id", 20000)
    tele = df_table("wstt_dados_historico_telemetria", "placa,distancia_total,velocidade_maxima", 20000)
    if viagens.empty and eventos.empty and tele.empty:
        return pd.DataFrame()

    if not viagens.empty:
        for col in ["distancia_total_percorrida", "quantidade_excesso_velocidade", "quantidade_freada_brusca", "quantidade_aceleracao_brusca"]:
            if col in viagens.columns:
                viagens[col] = pd.to_numeric(viagens[col], errors="coerce").fillna(0)
        resumo_v = viagens.groupby("placa", dropna=False).agg(
            qtd_viagens=("placa", "size"),
            km_total=("distancia_total_percorrida", "sum"),
            excesso_velocidade=("quantidade_excesso_velocidade", "sum"),
            freada_brusca=("quantidade_freada_brusca", "sum"),
            aceleracao_brusca=("quantidade_aceleracao_brusca", "sum"),
        ).reset_index()
    else:
        resumo_v = pd.DataFrame(columns=["placa", "qtd_viagens", "km_total", "excesso_velocidade", "freada_brusca", "aceleracao_brusca"])

    if not eventos.empty:
        eventos["velocidade_maxima"] = pd.to_numeric(eventos.get("velocidade_maxima"), errors="coerce").fillna(0)
        resumo_e = eventos.groupby("placa", dropna=False).agg(
            qtd_eventos_tracker=("evento_id", "size"),
            velocidade_maxima=("velocidade_maxima", "max"),
        ).reset_index()
    else:
        resumo_e = pd.DataFrame(columns=["placa", "qtd_eventos_tracker", "velocidade_maxima"])

    base = resumo_v.merge(resumo_e, on="placa", how="outer")
    for col in ["qtd_viagens", "km_total", "excesso_velocidade", "freada_brusca", "aceleracao_brusca", "qtd_eventos_tracker", "velocidade_maxima"]:
        if col not in base.columns:
            base[col] = 0
        base[col] = pd.to_numeric(base[col], errors="coerce").fillna(0)
    return base.sort_values(["qtd_eventos_tracker", "km_total"], ascending=[False, False])


def get_raster_status_df() -> pd.DataFrame:
    df = df_table("vw_raster_status_veiculo", "*", 20000)
    return df if not df.empty else fallback_raster_status()


def get_wstt_resumo_df() -> pd.DataFrame:
    df = df_table("vw_wstt_resumo_placa", "*", 20000)
    return df if not df.empty else fallback_wstt_resumo()


def render_sync_panel(title: str, description: str):
    st.markdown(f"<div class='section-title'>{title}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='section-desc'>{description}</div>", unsafe_allow_html=True)


if not require_login():
    st.stop()

st.caption("✅ Login carregado. Inicializando módulos do sistema...")
try:
    with st.spinner("Carregando integrações e conexão com Supabase..."):
        load_project_modules()
except Exception as exc:
    st.error("O app carregou, mas falhou ao inicializar módulos ou conexão. Verifique Secrets e dependências.")
    st.exception(exc)
    st.stop()

with st.sidebar:
    st.markdown("### 🚚 Central")
    page = st.radio(
        "Menu",
        [
            "📊 Visão geral",
            "🛰️ Raster",
            "📡 Omnilink/WSTT",
            "📈 Análises detalhadas",
            "🖥️ Terminal",
            "🗄️ Supabase / SQL",
        ],
        label_visibility="collapsed",
    )

    st.divider()
    st.markdown("#### Filtros rápidos")
    plate_filter = st.text_input("Filtrar placa", placeholder="Ex.: ABC1234").upper().replace("-", "").replace(" ", "")
    global_search = st.text_input("Busca textual", placeholder="Qualquer palavra-chave")

    controle_automatico()
    sidebar_terminal_preview()

    st.divider()
    try:
        test_connection()
        st.success("Supabase conectado")
    except Exception as exc:
        st.error("Supabase com erro")
        st.caption(str(exc))

    st.divider()
    st.markdown("<span class='small-muted'>Usuário e senha do dashboard definidos no arquivo .env.</span>", unsafe_allow_html=True)

header()

page_key = page.split(" ", 1)[1]

if page_key == "Visão geral":
    r = api_raster.get_kpis()
    o = api_omnilink.get_kpis()
    raster_status = get_raster_status_df()
    wstt_resumo = wstt_df_para_dashboard(get_wstt_resumo_df())

    render_sync_panel("Painel executivo", "Resumo consolidado das integrações, saúde da base e indicadores principais para operação.")
    cards = st.columns(8)
    with cards[0]: metric_card("SM Raster", r.get("sm_abertas", 0), "Pré-SM / SM abertas")
    with cards[1]: metric_card("Placas Raster", r.get("placas", 0), "Veículos identificados")
    with cards[2]: metric_card("Aptos", r.get("aptos", 0), "StatusChecklist = S")
    with cards[3]: metric_card("Não aptos", r.get("nao_aptos", 0), "StatusChecklist = N")
    with cards[4]: metric_card("Fora prazo", r.get("fora_prazo", 0), "Indicador Raster")
    with cards[5]: metric_card("Veículos WSTT", o.get("veiculos", 0), "Frota carregada")
    with cards[6]: metric_card("Viagens WSTT", o.get("viagens", 0), "Histórico sincronizado")
    with cards[7]: metric_card("Eventos WSTT", o.get("eventos", 0), "Tracker/telemetria")

    left, right = st.columns([1.1, 0.9])
    with left:
        with st.container(border=True):
            st.subheader("Saúde das integrações")
            resumo = df_table("vw_analise_integracoes", "*", 50)
            show_dataframe(resumo, height=270, plate_filter=plate_filter, search_text=global_search)
    with right:
        with st.container(border=True):
            st.subheader("Resumo rápido")
            mini_metrics([
                ("KM viagens WSTT", format_km(o.get("km_viagens", 0))),
                ("Velocidade máxima", round(safe_float(o.get("velocidade_maxima", 0)), 2)),
                ("Pendentes Raster", r.get("pendentes", 0)),
            ])
            st.write("")
            execs = df_table("integracao_execucoes", "origem,rotina,status,qtd_registros,executado_em", 10, "executado_em")
            show_dataframe(execs, height=270, plate_filter=plate_filter, search_text=global_search)

    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.subheader("Distribuição de aptidão operacional")
            if not raster_status.empty and "aptidao_operacional" in raster_status.columns:
                chart = raster_status.groupby("aptidao_operacional", dropna=False).size().reset_index(name="qtd")
                fig = px.pie(chart, names="aptidao_operacional", values="qtd", hole=.55)
                fig.update_layout(margin=dict(l=10, r=10, t=20, b=10), height=360)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Sem base Raster para gráfico.")
    with c2:
        with st.container(border=True):
            st.subheader("Top eventos por placa")
            if not wstt_resumo.empty and "qtd_eventos_tracker" in wstt_resumo.columns:
                top = wstt_resumo.sort_values("qtd_eventos_tracker", ascending=False).head(12)
                fig = px.bar(top, x="placa", y="qtd_eventos_tracker", text="qtd_eventos_tracker")
                fig.update_layout(margin=dict(l=10, r=10, t=20, b=10), height=360, xaxis_title="", yaxis_title="Eventos")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Sem base WSTT para gráfico.")

elif page_key == "Raster":
    render_sync_panel("Raster — Operação, cadastros e checklist", "Fluxo seguro: getTabela → consultar CodCheckList existente → getGerarResultadoCheckList. Não cria checklist.")
    st.markdown("<div class='info-box'><b>Fluxo ajustado:</b> o sistema <b>não cria checklist</b>. Ele apenas consulta <b>FILIAIS / PERFIL_SEGURANCA</b> com <code>getTabela</code> e roda <code>getGerarResultadoCheckList</code> usando <b>CodCheckList já existente</b>. <b>Produtos é obrigatório no seu ambiente Raster e será enviado automaticamente pelo perfil</b>.</div>", unsafe_allow_html=True)

    b1, b2, b3, b4, b5, b6 = st.columns(6)
    with b1:
        if st.button("🔄 SM abertas", use_container_width=True):
            terminal_log("Iniciando Raster • SM abertas")
            with st.spinner("Buscando SM abertas na Raster..."):
                qtd = api_raster.sync_sm_abertas()
                terminal_log(f"Finalizado Raster • SM abertas: {qtd} registro(s)", "OK")
                st.success(f"{qtd} registro(s) sincronizado(s).")
    with b2:
        if st.button("🚚 Viagens finalizadas", use_container_width=True):
            terminal_log("Iniciando Raster • viagens finalizadas")
            with st.spinner("Buscando eventos de fim de viagem..."):
                try:
                    qtd = api_raster.sync_evento_fim_viagem()
                    terminal_log(f"Finalizado Raster • viagens finalizadas: {qtd} registro(s)", "OK")
                    if qtd == 0:
                        st.warning("A Raster não retornou viagens finalizadas agora. O app não travou; veja o Terminal/Logs para detalhes.")
                    else:
                        st.success(f"{qtd} viagem(ns) sincronizada(s).")
                except Exception as exc:
                    terminal_log(f"Erro Raster • viagens finalizadas: {exc}", "ERRO")
                    st.warning("Erro ao consultar viagens finalizadas da Raster. A rotina foi ignorada para não derrubar o app.")
    with b3:
        if st.button("📚 getTabela apoio", use_container_width=True):
            terminal_log("Iniciando Raster • getTabela FILIAIS/PERFIL/PRODUTOS/ERROS")
            with st.spinner("Consultando tabelas de apoio na Raster..."):
                qtd = api_raster.sync_tabelas_checklist()
                terminal_log(f"Finalizado Raster • getTabela apoio: {qtd} registro(s)", "OK")
                st.success(f"{qtd} item(ns) de cadastro sincronizado(s).")
    with b4:
        if st.button("🧾 Consultar resultados", use_container_width=True):
            terminal_log("Iniciando Raster • getGerarResultadoCheckList em lote")
            with st.spinner("Consultando resultado oficial na Raster. Modo seguro: lote pequeno + delay de 12s..."):
                res = api_raster.sync_resultado_checklist_detalhado()
                terminal_log(f"Finalizado Raster • getGerarResultadoCheckList: {res}", "OK")
                st.success(f"Consulta finalizada. Encontrados: {res.get('encontrados',0)} | Consultados: {res.get('consultados',0)} | Salvos: {res.get('salvos',0)} | Com datas: {res.get('validos',0)} | Status: {res.get('status',{})}")
    with b5:
        if st.button("🔎 Consultar checklist automático", use_container_width=True):
            terminal_log("Iniciando Raster • consulta automática de checklist existente")
            with st.spinner("Executando getTabela e getGerarResultadoCheckList sem criar checklist..."):
                res = api_raster.sync_checklist_fluxo_automatico()
                terminal_log(f"Finalizado Raster • consulta checklist: {res}", "OK")
                resultado = res.get('resultado', res) if isinstance(res, dict) else {}
                st.success(f"Consulta concluída. Histórico encontrado: {res.get('historico_codchecklist',0) if isinstance(res,dict) else 0} | Consultados: {resultado.get('consultados',0)} | Salvos: {resultado.get('salvos',0)} | Com datas: {resultado.get('validos',0)} | Status: {resultado.get('status',{})}. Nenhum checklist foi criado.")

    with b6:
        if st.button("📍 Status viagem", use_container_width=True):
            terminal_log("Iniciando Raster • getStatusViagem automático")
            with st.spinner("Consultando status das viagens por placa automaticamente..."):
                qtd = api_raster.sync_status_viagem()
                terminal_log(f"Finalizado Raster • getStatusViagem: {qtd} registro(s)", "OK")
                st.success(f"{qtd} status de viagem sincronizado(s).")

    with st.expander("1) Consultar tabela específica da Raster", expanded=False):
        st.caption("Use para descobrir códigos reais de filial, perfil de segurança, produtos ou erros do webservice.")
        nomes = ["FILIAIS", "PERFIL_SEGURANCA", "PRODUTOS", "ERROS_WEBSERVICE", "TIPOS_VEICULO", "TECNOLOGIAS"]
        nome_tabela = st.selectbox("NomeTabela", nomes, key="raster_nome_tabela")
        if st.button("Executar getTabela", use_container_width=True):
            terminal_log(f"Iniciando Raster • getTabela {nome_tabela}")
            with st.spinner(f"Consultando {nome_tabela}..."):
                qtd = api_raster.sync_get_tabela(nome_tabela)
                terminal_log(f"Finalizado Raster • getTabela {nome_tabela}: {qtd} registro(s)", "OK")
                st.success(f"{qtd} registro(s) salvo(s) em raster_tabelas.")

    with st.expander("2) Status viagem automático — getStatusViagem", expanded=False):
        st.caption("Consulta getStatusViagem sem preencher placa: o app coleta placas de SM abertas, viagens, checklist e WSTT. Não cria nada.")
        limite_status = st.number_input("Limite de placas para status viagem", min_value=1, max_value=500, value=50, step=10, key="limite_status_viagem")
        if st.button("Executar getStatusViagem automático", use_container_width=True):
            terminal_log("Iniciando Raster • getStatusViagem automático")
            with st.spinner("Consultando status das viagens na Raster..."):
                qtd = api_raster.sync_status_viagem(limite=int(limite_status))
                terminal_log(f"Finalizado Raster • getStatusViagem: {qtd} registro(s)", "OK")
                st.success(f"{qtd} registro(s) sincronizado(s) em raster_status_viagem.")

    with st.expander("3) Consultar checklists já existentes", expanded=True):
        st.markdown("<div class='info-box'><b>Importante:</b> esta tela não chama <code>setIncluirCheckList</code>. Ela só consulta checklists que já existem e que tenham <b>CodCheckList</b> salvo em <code>raster_checklist_solicitacoes</code> ou <code>raster_checklist_resultado</code>.</div>", unsafe_allow_html=True)
        f1, f2, f3, f4 = st.columns(4)
        with f1:
            consulta_filial = st.text_input("CodFilial", value=os.getenv("RASTER_COD_FILIAL", ""), key="consulta_auto_filial")
        with f2:
            consulta_perfil = st.text_input("CodPerfilSeguranca", value=os.getenv("RASTER_COD_PERFIL_SEGURANCA", ""), key="consulta_auto_perfil")
        with f3:
            tentativas = st.number_input("Tentativas", min_value=1, max_value=1, value=1, step=1, key="consulta_auto_tentativas", help="Modo seguro: uma passada por execução para evitar loop/travamento.")
        with f4:
            intervalo = st.number_input("Intervalo segundos", min_value=12, max_value=300, value=12, step=1, key="consulta_auto_intervalo", help="A Raster exige pelo menos 10s; usamos 12s por segurança.")

        if st.button("🔎 Consultar resultados existentes em lote", use_container_width=True):
            terminal_log("Iniciando Raster • consulta em lote de checklists já existentes")
            with st.spinner("Consultando getGerarResultadoCheckList sem criar solicitações. Modo seguro: 1 checklist por rodada e delay mínimo de 12s..."):
                res = api_raster.sync_resultado_checklist_ate_finalizar(
                    cod_filial=consulta_filial,
                    cod_perfil_seguranca=consulta_perfil,
                    tentativas=int(tentativas),
                    intervalo_segundos=int(intervalo),
                )
                terminal_log(f"Finalizado Raster • consulta de checklists existentes: {res}", "OK")
                st.success(f"Consulta concluída. Encontrados: {res.get('encontrados',0)} | Consultados: {res.get('consultados',0)} | Salvos: {res.get('salvos',0)} | Com datas: {res.get('validos',0)} | Status: {res.get('status',{})}. Nenhum checklist foi criado.")

        st.caption("Agora o dashboard mantém todos os status do checklist. DataGeracao e DataExpiracao aparecem quando a Raster devolver; os demais status também ficam visíveis para acompanhamento operacional.")

    with st.expander("4) Consulta manual — getGerarResultadoCheckList", expanded=False):
        st.caption("Depois que existir CodCheckList, consulte o resultado. Filial e perfil são necessários; Produtos será enviado automaticamente porque a Raster está exigindo esse campo na consulta.")
        f1, f2, f3 = st.columns(3)
        with f1:
            manual_cod = st.text_input("CodCheckList", key="raster_manual_cod_checklist")
            manual_veiculo = st.text_input("Veículo / placa", key="raster_manual_veiculo")
        with f2:
            manual_filial = st.text_input("CodFilial", value=os.getenv("RASTER_COD_FILIAL", ""), key="raster_manual_cod_filial")
            manual_perfil = st.text_input("CodPerfilSeguranca", value=os.getenv("RASTER_COD_PERFIL_SEGURANCA", ""), key="raster_manual_cod_perfil")
        with f3:
            manual_produtos = st.text_area("Produtos JSON (opcional; se vazio, usa automático)", value=os.getenv("RASTER_PRODUTOS", ""), height=90, key="raster_manual_produtos")
        if st.button("Executar getGerarResultadoCheckList", use_container_width=True):
            terminal_log(f"Iniciando Raster • getGerarResultadoCheckList CodCheckList={manual_cod or 'vazio'} Veiculo={manual_veiculo or 'vazio'}")
            with st.spinner("Consultando resultado oficial do checklist..."):
                qtd = api_raster.sync_resultado_checklist(
                    cod_checklist=manual_cod,
                    cod_filial=manual_filial,
                    cod_perfil_seguranca=manual_perfil,
                    produtos=manual_produtos,
                    veiculo=manual_veiculo,
                )
                terminal_log(f"Finalizado Raster • getGerarResultadoCheckList: {qtd} registro(s)", "OK")
                st.success(f"Consulta executada. Registros com DataGeracao/DataExpiracao: {qtd}. Confira a aba Resultado checklist para ver também os demais status.")

    r = api_raster.get_kpis()
    m = st.columns(6)
    with m[0]: metric_card("SM", r.get("sm_abertas", 0), "SM abertas")
    with m[1]: metric_card("Placas", r.get("placas", 0), "Placas únicas")
    with m[2]: metric_card("Aptos", r.get("aptos", 0), "Operacional")
    with m[3]: metric_card("Não aptos", r.get("nao_aptos", 0), "Operacional")
    with m[4]: metric_card("Pendentes", r.get("pendentes", 0), "Checklist")
    with m[5]: metric_card("Desvios", r.get("desvios", 0), "Rota")

    tabs = st.tabs(["Status por veículo", "Status viagem", "Viagens finalizadas", "SM abertas", "Tabelas Raster", "Solicitações checklist", "Resultado checklist", "Logs"])
    with tabs[0]:
        st.subheader("Situação atual por veículo")
        show_dataframe(get_raster_status_df(), height=500, style=True, plate_filter=plate_filter, search_text=global_search)
    with tabs[1]:
        st.subheader("Status viagem Raster — getStatusViagem")
        st.caption("Consulta automática por placa, sem preencher nada. A base usa placas já encontradas em SM, viagens, checklist e WSTT.")
        df_status_v = df_table("raster_status_viagem", "chave,cod_solicitacao,cod_pre_solicitacao,cod_filial,cod_perfil_seguranca,cod_rota,placa_veiculo,status_viagem,data_prev_inicio,data_prev_fim,data_real_inicio,data_hora_ult_posicao,latitude_ult_posicao,longitude_ult_posicao,ref_ult_posicao,qtd_documentos,documentos_resumo,synced_at", 20000, "synced_at")
        show_dataframe(df_status_v, height=430, plate_filter=plate_filter, search_text=global_search)
        st.subheader("Documentos vinculados ao status viagem")
        st.caption("Documentos retornados pela Raster no getStatusViagem. Sem preenchimento manual e sem criar nada.")
        df_docs_v = df_table("raster_status_viagem_documentos", "placa_veiculo,cod_solicitacao,cod_pre_solicitacao,tipo,numero,origem,synced_at", 20000, "synced_at")
        show_dataframe(df_docs_v, height=300, plate_filter=plate_filter, search_text=global_search)
    with tabs[2]:
        st.subheader("Viagens finalizadas Raster")
        df = df_table("raster_evento_fim_viagem", "cod_solicitacao,placa_veiculo,status_viagem,status_checklist,aptidao_operacional,dentro_prazo,velocidade_media,maior_velocidade,tempo_parado,desvios_rota,eventos_velocidade,data_real_fim,synced_at", 20000, "synced_at")
        show_dataframe(df, height=500, style=True, plate_filter=plate_filter, search_text=global_search)
    with tabs[3]:
        st.subheader("SM abertas")
        show_dataframe(df_table("raster_sm_geradas", "*", 20000, "synced_at"), height=500, plate_filter=plate_filter, search_text=global_search)
    with tabs[4]:
        st.subheader("Tabelas de apoio da Raster")
        st.caption("Dados vindos do método getTabela: FILIAIS, PERFIL_SEGURANCA, PRODUTOS e ERROS_WEBSERVICE.")
        show_dataframe(df_table("raster_tabelas", "tabela,codigo,descricao,dados,synced_at", 20000, "synced_at"), height=500, search_text=global_search)
    with tabs[5]:
        st.subheader("Solicitações de checklist")
        st.caption("Tabela de CodCheckList já existentes. O app apenas lê esses códigos para consultar resultado; não cria novas solicitações.")
        show_dataframe(df_table("raster_checklist_solicitacoes", "chave,cod_checklist,veiculo,cod_filial,tipo,vinculo,sensor_temperatura,synced_at", 20000, "synced_at"), height=500, plate_filter=plate_filter, search_text=global_search)
    with tabs[6]:
        st.subheader("Resultado oficial do checklist")
        st.caption("Tabela limpa operacional: mostra todos os status do checklist, sem raw, CodErro, MsgErro ou erro técnico. DataGeracao/DataExpiracao aparecem quando a Raster devolver esses campos.")
        df_resultado = df_table("raster_checklist_resultado", "cod_resultado,cod_checklist,veiculo,cod_filial,cod_perfil_seguranca,status,resultado,apto,data_geracao,data_expiracao,url_documento,synced_at", 20000, "synced_at")
        if not df_resultado.empty:
            df_resultado = add_checklist_status_desc(df_resultado)
            st.markdown("<div class='info-box'><b>Status exibidos:</b> ST = Sem teste, AI = Aguardando início, AE = Aguardando espelhamento, CV = Configurando veículo, ET = Teste em execução, FI = Finalizado, CA = Cancelado.</div>", unsafe_allow_html=True)
            checklist_status_summary(df_resultado)
            show_dataframe(df_resultado, height=500, plate_filter=plate_filter, search_text=global_search)
        else:
            st.info("Nenhum resultado de checklist encontrado.")
    with tabs[7]:
        st.subheader("Logs de integração — Raster")
        show_dataframe(df_table("integracao_execucoes", "origem,rotina,status,qtd_registros,executado_em", 200, "executado_em"), height=500, search_text="Raster" if not global_search else global_search)

elif page_key == "Omnilink/WSTT":
    render_sync_panel(
        "Omnilink/WSTT — Telemetria e eventos",
        "Rotinas separadas e organizadas por etapa. Use de cima para baixo: frota, viagens, telemetria e eventos.",
    )
    st.markdown(
        "<div class='info-box'><b>Conversão de distância:</b> a Omnilink retorna distância em metros. No dashboard, os valores são convertidos para KM apenas para visualização; o Supabase continua gravando o valor original.</div>",
        unsafe_allow_html=True,
    )

    st.markdown("### Central de sincronização")
    st.caption("Rotinas organizadas em etapas. Execute na ordem recomendada ou use a execução automática no menu lateral.")

    st.markdown("#### 1. Base da frota")
    frota_col, resumo_col = st.columns([0.38, 0.62])
    with frota_col:
        with st.container(border=True):
            st.markdown("<div class='sync-card-title'><span class='sync-number'>1</span>Frota</div>", unsafe_allow_html=True)
            st.markdown("<div class='sync-card-desc'>Atualiza placas e veículos disponíveis na Omnilink/WSTT. Rode essa rotina primeiro.</div>", unsafe_allow_html=True)
            if st.button("🚛 Sincronizar frota", use_container_width=True, key="btn_wstt_frota"):
                terminal_log("Iniciando WSTT • frota")
                with st.spinner("Buscando veículos na WSTT..."):
                    qtd = api_omnilink.sync_veiculos()
                    terminal_log(f"Finalizado WSTT • frota: {qtd} registro(s)", "OK")
                    st.success(f"{qtd} veículo(s) sincronizado(s).")
    with resumo_col:
        with st.container(border=True):
            st.markdown("<div class='sync-card-title'>Ordem recomendada</div>", unsafe_allow_html=True)
            st.markdown(
                "<div class='sync-card-desc'>"
                "1) Frota para carregar as placas • "
                "2) Viagens por placa • "
                "3) Telemetria por janela de 1 hora • "
                "4) Eventos tracker."
                "<br><br>Para rodar sem ficar clicando, use <b>Execução automática</b> no menu lateral."
                "</div>",
                unsafe_allow_html=True,
            )

    st.write("")
    st.markdown("#### 2. Rotinas por período")
    col_viagens, col_tele, col_eventos = st.columns(3)

    with col_viagens:
        with st.container(border=True):
            st.markdown("<div class='sync-card-title'><span class='sync-number'>2</span>Viagens</div>", unsafe_allow_html=True)
            st.markdown("<div class='sync-card-desc'>Histórico de viagens por placa. Use períodos maiores aqui e limite a quantidade de placas quando necessário.</div>", unsafe_allow_html=True)
            ini_v, fim_v = periodo_inputs("viagens", 7)
            limite = st.number_input("Limite de placas", min_value=1, max_value=500, value=50, step=10, key="limite_wstt_viagens")
            if st.button("🛣️ Sincronizar viagens", use_container_width=True, key="btn_wstt_viagens"):
                progress_bar = st.progress(0)
                status = st.empty()
                def p1(idx, total, placa, count):
                    progress_bar.progress(idx / max(total, 1))
                    status.caption(f"{idx}/{total} • {placa} • {count} viagem(ns)")
                terminal_log("Iniciando WSTT • viagens")
                with st.spinner("Buscando viagens por placa..."):
                    qtd = api_omnilink.sync_viagens(ini_v, fim_v, int(limite), p1)
                    terminal_log(f"Finalizado WSTT • viagens: {qtd} registro(s)", "OK")
                    st.success(f"{qtd} viagem(ns) sincronizada(s).")

    with col_tele:
        with st.container(border=True):
            st.markdown("<div class='sync-card-title'><span class='sync-number'>3</span>Telemetria</div>", unsafe_allow_html=True)
            st.markdown("<div class='sync-card-desc'>Leituras históricas. A integração quebra o período em janelas de 1 hora para evitar sobrecarga.</div>", unsafe_allow_html=True)
            ini_t, fim_t = periodo_inputs("tele", 1)
            if st.button("📡 Sincronizar telemetria", use_container_width=True, key="btn_wstt_telemetria"):
                progress_bar = st.progress(0)
                status = st.empty()
                def p2(idx, total, count):
                    progress_bar.progress(idx / max(total, 1))
                    status.caption(f"Janela {idx}/{total} • {count} leitura(s)")
                terminal_log("Iniciando WSTT • telemetria")
                with st.spinner("Buscando telemetria por janelas de 1 hora..."):
                    qtd = api_omnilink.sync_telemetria(ini_t, fim_t, p2)
                    terminal_log(f"Finalizado WSTT • telemetria: {qtd} registro(s)", "OK")
                    st.success(f"{qtd} leitura(s) sincronizada(s).")

    with col_eventos:
        with st.container(border=True):
            st.markdown("<div class='sync-card-title'><span class='sync-number'>4</span>Eventos</div>", unsafe_allow_html=True)
            st.markdown("<div class='sync-card-desc'>Eventos tracker e ocorrências de direção dentro do período selecionado.</div>", unsafe_allow_html=True)
            ini_e, fim_e = periodo_inputs("eventos", 1)
            versao2 = st.toggle("Usar versão 31.16", value=True, key="toggle_wstt_eventos_v2")
            if st.button("⚠️ Sincronizar eventos", use_container_width=True, key="btn_wstt_eventos"):
                progress_bar = st.progress(0)
                status = st.empty()
                def p3(idx, total, count):
                    progress_bar.progress(idx / max(total, 1))
                    status.caption(f"Janela {idx}/{total} • {count} evento(s)")
                terminal_log("Iniciando WSTT • eventos")
                with st.spinner("Buscando eventos tracker..."):
                    qtd = api_omnilink.sync_eventos(ini_e, fim_e, 2 if versao2 else 1, p3)
                    terminal_log(f"Finalizado WSTT • eventos: {qtd} registro(s)", "OK")
                    st.success(f"{qtd} evento(s) sincronizado(s).")
    st.write("")
    st.markdown("### Indicadores Omnilink/WSTT")
    o = api_omnilink.get_kpis()
    k1, k2, k3, k4 = st.columns(4)
    with k1: metric_card("Veículos", o.get("veiculos", 0), "Frota carregada")
    with k2: metric_card("Viagens", o.get("viagens", 0), "Histórico sincronizado")
    with k3: metric_card("Telemetria", o.get("telemetria", 0), "Leituras recebidas")
    with k4: metric_card("Eventos", o.get("eventos", 0), "Tracker/telemetria")
    k5, k6, k7 = st.columns(3)
    with k5: metric_card("Eventos direção", o.get("eventos_viagem", 0), "Excesso/freada/aceleração")
    with k6: metric_card("KM viagens", format_km(o.get("km_viagens", 0)), "Convertido de metros")
    with k7: metric_card("Vel. máxima", round(safe_float(o.get("velocidade_maxima", 0)), 2), "Registrada")

    st.write("")
    tabs = st.tabs(["Resumo por placa", "Veículos", "Viagens", "Telemetria", "Eventos", "Logs"])
    with tabs[0]:
        st.subheader("Resumo consolidado por placa")
        resumo_wstt = wstt_df_para_dashboard(get_wstt_resumo_df())
        show_dataframe(resumo_wstt, height=520, plate_filter=plate_filter, search_text=global_search)
    with tabs[1]:
        st.subheader("Cadastro de veículos")
        show_dataframe(df_table("wstt_veiculos", "*", 20000, "atualizado_em"), height=520, plate_filter=plate_filter, search_text=global_search)
    with tabs[2]:
        st.subheader("Viagens de telemetria")
        viagens_wstt = wstt_df_para_dashboard(df_table("wstt_viagens_telemetria", "*", 20000, "synced_at"))
        show_dataframe(viagens_wstt, height=520, plate_filter=plate_filter, search_text=global_search)
    with tabs[3]:
        st.subheader("Leituras de telemetria")
        telemetria_wstt = wstt_df_para_dashboard(df_table("wstt_dados_historico_telemetria", "*", 20000, "synced_at"))
        show_dataframe(telemetria_wstt, height=520, plate_filter=plate_filter, search_text=global_search)
    with tabs[4]:
        st.subheader("Eventos tracker")
        df_eventos = df_table("wstt_eventos_tracker_telemetria2", "*", 20000, "synced_at")
        if df_eventos.empty:
            df_eventos = df_table("wstt_eventos_tracker_telemetria", "*", 20000, "synced_at")
        show_dataframe(df_eventos, height=520, plate_filter=plate_filter, search_text=global_search)
    with tabs[5]:
        st.subheader("Logs de integração — WSTT")
        show_dataframe(df_table("integracao_execucoes", "origem,rotina,status,qtd_registros,executado_em", 200, "executado_em"), height=520, search_text="WSTT" if not global_search else global_search)

elif page_key == "Análises detalhadas":
    render_sync_panel("Análises detalhadas", "Cruze indicadores da Raster e da Omnilink/WSTT para enxergar risco, performance e situação operacional da frota.")
    raster = get_raster_status_df()
    wstt = wstt_df_para_dashboard(get_wstt_resumo_df())
    tab1, tab2, tab3, tab4 = st.tabs(["Operação Raster", "Performance WSTT", "Risco por placa", "Base consolidada"])

    with tab1:
        if not raster.empty:
            a, b = st.columns(2)
            with a:
                st.subheader("Aptidão operacional")
                chart = raster.groupby("aptidao_operacional", dropna=False).size().reset_index(name="qtd")
                fig = px.pie(chart, names="aptidao_operacional", values="qtd", hole=.52)
                fig.update_layout(margin=dict(l=10, r=10, t=20, b=10), height=360)
                st.plotly_chart(fig, use_container_width=True)
            with b:
                st.subheader("Prazo das viagens")
                if "dentro_prazo" in raster.columns:
                    prazo = raster.groupby("dentro_prazo", dropna=False).size().reset_index(name="qtd")
                    fig = px.bar(prazo, x="dentro_prazo", y="qtd", text="qtd")
                    fig.update_layout(margin=dict(l=10, r=10, t=20, b=10), height=360, xaxis_title="", yaxis_title="Qtd")
                    st.plotly_chart(fig, use_container_width=True)
            show_dataframe(raster, height=430, style=True, plate_filter=plate_filter, search_text=global_search)
        else:
            st.info("Sem dados Raster para análise.")

    with tab2:
        if not wstt.empty:
            a, b = st.columns(2)
            with a:
                st.subheader("Top KM por placa")
                top_km = wstt.sort_values("km_total_km" if "km_total_km" in wstt.columns else "km_total", ascending=False).head(20)
                y_km = "km_total_km" if "km_total_km" in top_km.columns else "km_total"
                fig = px.bar(top_km, x="placa", y=y_km, text=y_km)
                fig.update_layout(margin=dict(l=10, r=10, t=20, b=10), height=360, xaxis_title="", yaxis_title="KM")
                st.plotly_chart(fig, use_container_width=True)
            with b:
                st.subheader("Top eventos de direção")
                for col in ["excesso_velocidade", "freada_brusca", "aceleracao_brusca"]:
                    if col not in wstt.columns:
                        wstt[col] = 0
                wstt["eventos_direcao"] = wstt[["excesso_velocidade", "freada_brusca", "aceleracao_brusca"]].sum(axis=1)
                top_ev = wstt.sort_values("eventos_direcao", ascending=False).head(20)
                fig = px.bar(top_ev, x="placa", y="eventos_direcao", text="eventos_direcao")
                fig.update_layout(margin=dict(l=10, r=10, t=20, b=10), height=360, xaxis_title="", yaxis_title="Eventos")
                st.plotly_chart(fig, use_container_width=True)
            show_dataframe(wstt, height=430, plate_filter=plate_filter, search_text=global_search)
        else:
            st.info("Sem dados WSTT para análise.")

    with tab3:
        if not raster.empty or not wstt.empty:
            base = pd.merge(raster, wstt, on="placa", how="outer") if not raster.empty and not wstt.empty else (raster if not raster.empty else wstt)
            for col in ["desvios_rota", "eventos_velocidade", "excesso_velocidade", "freada_brusca", "aceleracao_brusca", "qtd_eventos_tracker"]:
                if col not in base.columns:
                    base[col] = 0
                base[col] = pd.to_numeric(base[col], errors="coerce").fillna(0)
            base["score_risco"] = (
                base["desvios_rota"] * 4 +
                base["eventos_velocidade"] * 3 +
                base["excesso_velocidade"] * 3 +
                base["freada_brusca"] * 2 +
                base["aceleracao_brusca"] * 2 +
                base["qtd_eventos_tracker"]
            )
            base = base.sort_values("score_risco", ascending=False)
            st.subheader("Score de risco por placa")
            fig = px.bar(base.head(25), x="placa", y="score_risco", text="score_risco")
            fig.update_layout(margin=dict(l=10, r=10, t=20, b=10), height=380, xaxis_title="", yaxis_title="Score")
            st.plotly_chart(fig, use_container_width=True)
            show_dataframe(base, height=430, style=True, plate_filter=plate_filter, search_text=global_search)
        else:
            st.info("Sem dados suficientes para consolidar risco por placa.")

    with tab4:
        st.subheader("Consolidação das integrações")
        show_dataframe(df_table("vw_analise_integracoes", "*", 50), height=320, search_text=global_search)
        if not wstt.empty:
            st.subheader("Mapa de intensidade — eventos x KM")
            plot_df = wstt.copy()
            if "qtd_eventos_tracker" not in plot_df.columns:
                plot_df["qtd_eventos_tracker"] = 0
            if "km_total_km" not in plot_df.columns:
                if "km_total" not in plot_df.columns:
                    plot_df["km_total"] = 0
                plot_df["km_total_km"] = pd.to_numeric(plot_df["km_total"], errors="coerce").fillna(0) / 1000
            fig = px.scatter(
                plot_df.head(300),
                x="km_total_km",
                y="qtd_eventos_tracker",
                hover_data=[c for c in ["placa", "velocidade_maxima"] if c in plot_df.columns],
                size="qtd_viagens" if "qtd_viagens" in plot_df.columns else None,
            )
            fig.update_layout(margin=dict(l=10, r=10, t=20, b=10), height=380, xaxis_title="KM total", yaxis_title="Eventos tracker")
            st.plotly_chart(fig, use_container_width=True)

elif page_key == "Terminal":
    render_sync_panel("Terminal das integrações", "Acompanhe em tempo real o que o dashboard executou e os últimos logs gravados no Supabase.")
    c1, c2, c3 = st.columns([0.2, 0.2, 0.6])
    with c1:
        if st.button("Limpar terminal", use_container_width=True, key="btn_clear_terminal_page"):
            st.session_state.terminal_logs = []
            st.rerun()
    with c2:
        if st.button("Atualizar logs", use_container_width=True, key="btn_refresh_terminal_page"):
            st.rerun()
    st.write("")
    render_terminal_block(height=520, include_db_logs=True)
    st.write("")
    st.subheader("Tabela de execuções")
    show_dataframe(df_table("integracao_execucoes", "origem,rotina,status,qtd_registros,executado_em", 500, "executado_em"), height=420, search_text=global_search)

    with st.expander("Diagnóstico técnico do último erro Raster", expanded=False):
        st.caption("Essa área não aparece nas tabelas operacionais. Use apenas para copiar o erro real quando a Raster retornar HTTP_ERROR.")
        diag = df_table("integracao_execucoes", "origem,rotina,status,qtd_registros,erro,executado_em", 50, "executado_em")
        if not diag.empty:
            diag = diag[(diag.get("origem") == "Raster") & (diag.get("status") == "erro")] if "origem" in diag.columns and "status" in diag.columns else diag
        show_dataframe(diag, height=360, search_text=global_search)

elif page_key == "Supabase / SQL":
    render_sync_panel("Estrutura Supabase", "Consulta de referência da estrutura. Se suas tabelas já existem no Supabase, não precisa recriar; o app usa as tabelas existentes e faz upsert nos dados.")
    st.markdown("<div class='warn-box'><b>Observação:</b> como a tabela <code>raster_checklist_resultado</code> já existe no seu Supabase, não precisa criar de novo. Esta aba é só referência/conferência.</div>", unsafe_allow_html=True)
    with open("supabase_schema.sql", encoding="utf-8") as f:
        sql = f.read()
    st.download_button("Baixar SQL", sql.encode("utf-8"), file_name="supabase_schema.sql", mime="text/plain", key="download_sql_schema")
    st.code(sql, language="sql")
