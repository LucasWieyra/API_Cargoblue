import os
import json
import time
from datetime import datetime, timezone, date, timedelta
from typing import Any

import requests
import streamlit as st
from dateutil import parser
from dotenv import load_dotenv

from supabase_db import insert_rows, select_distinct_values, upsert_rows, select_rows

load_dotenv()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, None)
        if value is not None:
            return str(value).strip().strip('"')
    except Exception:
        pass
    return (os.getenv(name, default) or default).strip().strip('"')


def _base_url() -> str:
    return _env("RASTER_BASE_URL", "https://integra.logae.com.br/datasnap/rest/TWebService").rstrip("/")


def _ambiente() -> str:
    return _env("RASTER_AMBIENTE", "Producao") or "Producao"


def _tipo_retorno() -> str:
    return _env("RASTER_TIPO_RETORNO", "JSON") or "JSON"


def _credentials() -> tuple[str, str]:
    login = _env("RASTER_LOGIN")
    senha = _env("RASTER_SENHA")
    if not login or not senha or senha == "COLOQUE_A_SENHA_DA_RASTER_AQUI":
        raise RuntimeError("Coloque a senha real da Raster no arquivo .env em RASTER_SENHA.")
    return login, senha


def parse_ts(value: Any) -> str | None:
    if value in (None, "", "null", "None"):
        return None
    text = str(value).strip()
    if not text or text.startswith("1900-01-01"):
        return None
    try:
        return parser.parse(text).isoformat()
    except Exception:
        return None


def to_int(value: Any) -> int | None:
    if value in (None, "", "null", "None"):
        return None
    try:
        return int(float(str(value).replace(",", ".")))
    except Exception:
        return None


def to_float(value: Any) -> float | None:
    if value in (None, "", "null", "None"):
        return None
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return None


def normalize_placa(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).upper().replace("-", "").replace(" ", "").strip() or None


def _extract_documentos_status_viagem(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extrai documentos retornados no getStatusViagem em formatos variados.

    A Raster pode devolver Documentos diretamente ou documentos dentro de
    coletas/entregas/paradas. Mantemos uma lista padronizada para exibição e
    uma tabela filha para consulta simples no Supabase.
    """
    encontrados: list[dict[str, Any]] = []

    def add_doc(doc: Any, origem: str = "") -> None:
        if not isinstance(doc, dict):
            return
        tipo = _pick(doc, "Tipo", "tipo", "TipoDocumento", "TipoDoc")
        numero = _pick(doc, "Numero", "Número", "numero", "NumDocumento", "Documento", "documento", "Chave")
        if tipo is None and numero is None and not doc:
            return
        encontrados.append({
            "tipo": str(tipo).strip() if tipo not in (None, "") else None,
            "numero": str(numero).strip() if numero not in (None, "") else None,
            "origem": origem or None,
            "raw": doc,
        })

    def walk(obj: Any, origem: str = "") -> None:
        if isinstance(obj, dict):
            # Se o próprio objeto já for documento, captura direto.
            # Ex.: {"Tipo":"CTE", "Numero":"1234"} ou {"Tipo":"CARGA", "Numero":"4192"}
            if any(k in obj for k in ("Tipo", "tipo", "TipoDocumento", "TipoDoc")) and any(k in obj for k in ("Numero", "Número", "numero", "NumDocumento", "Documento", "documento", "Chave")):
                add_doc(obj, origem or "Documento")

            # Chaves diretas comuns no método getStatusViagem
            for key in ("Documentos", "Documento", "Docs", "CTes", "CTE", "Conhecimentos", "Conhecimento", "Cargas", "Carga", "Notas", "NFs"):
                val = obj.get(key)
                if isinstance(val, list):
                    for item in val:
                        add_doc(item, key)
                elif isinstance(val, dict):
                    add_doc(val, key)
            # Também varre estruturas de coleta/entrega que podem conter docs
            for key, val in obj.items():
                if key in ("raw", "payload", "tentativas_http"):
                    continue
                if isinstance(val, (dict, list)):
                    walk(val, key)
        elif isinstance(obj, list):
            for item in obj:
                walk(item, origem)

    walk(data)

    # Remove duplicados por Tipo + Numero mantendo o raw primeiro encontrado.
    # Tipo fica padronizado em maiúsculo: CTE, CARGA, SHIPMENT, OUTROS etc.
    unicos: list[dict[str, Any]] = []
    vistos: set[tuple[str | None, str | None]] = set()
    for d in encontrados:
        tipo = str(d.get("tipo") or "").upper().strip() or None
        numero = str(d.get("numero") or "").strip() or None
        if not numero:
            continue
        chave = (tipo, numero)
        if chave in vistos:
            continue
        vistos.add(chave)
        d["tipo"] = tipo
        d["numero"] = numero
        unicos.append(d)
    return unicos


def _documentos_resumo(documentos: list[dict[str, Any]]) -> str | None:
    partes = []
    for d in documentos[:20]:
        tipo = d.get("tipo") or "DOC"
        numero = d.get("numero") or "SEM_NUMERO"
        partes.append(f"{tipo}:{numero}")
    return ", ".join(partes) if partes else None


def _periodo_mes_anterior_atual() -> tuple[str, str]:
    """Retorna do 1º dia do mês anterior até hoje.

    Uso padrão para rotinas Raster por período sem precisar preencher nada.
    """
    hoje = date.today()
    primeiro_mes_atual = hoje.replace(day=1)
    ultimo_mes_anterior = primeiro_mes_atual - timedelta(days=1)
    primeiro_mes_anterior = ultimo_mes_anterior.replace(day=1)
    return primeiro_mes_anterior.isoformat(), hoje.isoformat()


def _periodo_raster_evento_fim() -> tuple[str, str]:
    """Período automático para getEventoFimViagem.

    Padrão: mês anterior + mês atual. Se quiser usar janela curta, configure
    RASTER_EVENTO_FIM_DIAS no .env/Secrets.
    """
    dias_txt = _env("RASTER_EVENTO_FIM_DIAS", "")
    if dias_txt:
        dias = to_int(dias_txt) or 1
        dias = max(1, min(dias, 62))
        hoje = date.today()
        return (hoje - timedelta(days=dias - 1)).isoformat(), hoje.isoformat()
    return _periodo_mes_anterior_atual()


def _safe_key(*parts: Any) -> str:
    text = "-".join(str(p) for p in parts if p not in (None, "", "None"))
    return text[:180] if text else f"sem-chave-{int(time.time())}"


def call_raster(metodo: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    login, senha = _credentials()
    payload = {
        "Ambiente": _ambiente(),
        "Login": login,
        "Senha": senha,
        "TipoRetorno": _tipo_retorno(),
    }
    if body:
        payload.update(body)

    urls = [f'{_base_url()}/"{metodo}"', f"{_base_url()}/{metodo}"]
    last_error: Exception | None = None

    for url in urls:
        try:
            response = requests.post(url, json=payload, timeout=int(_env("RASTER_TIMEOUT_SECONDS", "20") or 20))
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and isinstance(data.get("result"), list) and data["result"]:
                item = data["result"][0]
                return item if isinstance(item, dict) else {"raw": item}
            if isinstance(data, dict):
                return data
            return {"raw": data}
        except Exception as exc:
            last_error = exc
            continue

    raise RuntimeError(f"Erro ao chamar Raster {metodo}: {last_error}")


def _ok(data: dict[str, Any]) -> bool:
    return data.get("CodErro") in (0, "0", None)


def _list_from(data: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return [v for v in value if isinstance(v, dict)]
        if isinstance(value, dict):
            nested: list[dict[str, Any]] = []
            for sub in value.values():
                if isinstance(sub, list):
                    nested.extend([v for v in sub if isinstance(v, dict)])
                elif isinstance(sub, dict):
                    nested.append(sub)
            if nested:
                return nested
    return []


def log_execucao(rotina: str, status: str, qtd: int = 0, erro: str | None = None) -> None:
    try:
        insert_rows("integracao_execucoes", [{
            "origem": "Raster",
            "rotina": rotina,
            "status": status,
            "qtd_registros": qtd,
            "erro": erro[:3000] if erro else None,
            "executado_em": now_iso(),
        }])
    except Exception as exc:
        print("Erro ao gravar log Raster:", exc)


def classificar_aptidao(status_checklist: Any, resultado: Any = None) -> str:
    status = str(status_checklist or "").upper().strip()
    resultado = str(resultado or "").upper().strip()

    if resultado == "A" or status == "S":
        return "APTO"
    if resultado == "R" or status == "N":
        return "NAO_APTO"
    if status in ("I", "", "ST", "AI", "AE", "CV", "ET"):
        return "PENDENTE"
    return "INDEFINIDO"


def sync_sm_abertas() -> int:
    rotina = "SM abertas"
    try:
        data = call_raster("getConsultaPreSMAberta", {})
        if not _ok(data):
            raise RuntimeError(f"Raster retornou erro: {data.get('MsgErro')} / {data.get('CodErro')}")

        presms = _list_from(data, "PreSMs", "PreSM", "Solicitacoes", "Solicitacao", "Viagens", "Viagem")
        rows: list[dict[str, Any]] = []

        for sm in presms:
            codigo = to_int(sm.get("Codigo") or sm.get("CodSolicitacao") or sm.get("CodPreSM"))
            if not codigo:
                continue
            rows.append({
                "codigo": codigo,
                "placa": normalize_placa(sm.get("Placa") or sm.get("PlacaVeiculo") or sm.get("Veiculo")),
                "data": parse_ts(sm.get("Data") or sm.get("DataHora")),
                "data_prev_inicio": parse_ts(sm.get("DataPrevInicio") or sm.get("DataHoraPrevIni") or sm.get("DataHoraPrevInicio")),
                "data_prev_fim": parse_ts(sm.get("DataPrevFim") or sm.get("DataHoraPrevFim")),
                "cod_ibge_origem": to_int(sm.get("CodIBGEOrigem") or sm.get("CodIBGECidadeOrig") or sm.get("CodIBGECidadeOrigem")),
                "cidade_origem": sm.get("CidadeOrigem"),
                "cod_ibge_destino": to_int(sm.get("CodIBGEDestino") or sm.get("CodIBGECidadeDest") or sm.get("CodIBGECidadeDestino")),
                "cidade_destino": sm.get("CidadeDestino"),
                "cnpj_cliente_orig": sm.get("CNPJClienteOrig"),
                "razao_cliente_orig": sm.get("RazaoClienteOrig"),
                "cnpj_cliente_dest": sm.get("CNPJClienteDest"),
                "razao_cliente_dest": sm.get("RazaoClienteDest"),
                "synced_at": now_iso(),
            })

        total = upsert_rows("raster_sm_geradas", rows, "codigo")
        log_execucao(rotina, "sucesso", total)
        return total
    except Exception as exc:
        log_execucao(rotina, "erro", 0, str(exc))
        raise


def _evento_fim_payload() -> dict[str, Any]:
    """Payload seguro para getEventoFimViagem.

    Padrão automático: mês anterior + mês atual, sem precisar preencher nada.
    O manual permite DataInicial/DataFinal/StatusViagem/Placa como filtros opcionais.
    """
    data_inicial, data_final = _periodo_raster_evento_fim()
    payload: dict[str, Any] = {
        "DataInicial": data_inicial,
        "DataFinal": data_final,
    }

    status = _env("RASTER_EVENTO_FIM_STATUS", "T")
    if status:
        payload["StatusViagem"] = status

    placa = normalize_placa(_env("RASTER_EVENTO_FIM_PLACA", ""))
    if placa:
        payload["Placa"] = placa

    return payload


def _resumo_erro_raster(data: dict[str, Any]) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, default=str)[:6000]
    except Exception:
        return str(data)[:6000]


def sync_evento_fim_viagem() -> int:
    rotina = "Evento fim viagem"
    try:
        payload = _evento_fim_payload()
        data = call_raster("getEventoFimViagem", payload)
        if not _ok(data):
            erro = _resumo_erro_raster({
                "mensagem": "Raster retornou erro em getEventoFimViagem",
                "payload_enviado": payload,
                "retorno_raster": data,
            })
            log_execucao(rotina, "erro", 0, erro)
            print(erro)
            return 0

        viagens = _list_from(data, "Viagens", "Viagem")
        rows: list[dict[str, Any]] = []
        doc_rows: list[dict[str, Any]] = []

        for v in viagens:
            cod = to_int(v.get("CodSolicitacao"))
            if not cod:
                continue
            status_checklist = str(v.get("StatusChecklist") or "").upper().strip() or None
            placa_norm = normalize_placa(v.get("PlacaVeiculo"))
            cod_pre = to_int(v.get("CodPreSolicitacao"))
            chave_status = _safe_key("getEventoFimViagem", cod, cod_pre, placa_norm)

            # Parser oficial dos documentos de viagem.
            # A Raster confirmou que CARGA/CTE ficam aninhados em:
            # SM -> ColetasEntregas -> Produtos -> Documentos.
            # A função _extract_documentos_status_viagem varre recursivamente
            # todo o retorno e captura Documentos em qualquer profundidade.
            documentos_viagem = _extract_documentos_status_viagem(v)
            for idx, doc in enumerate(documentos_viagem, start=1):
                tipo_doc = str(doc.get("tipo") or "").upper().strip() or None
                numero_doc = str(doc.get("numero") or "").strip() or None
                if not numero_doc:
                    continue
                doc_rows.append({
                    "chave": _safe_key("getEventoFimViagem", cod, cod_pre, placa_norm, tipo_doc, numero_doc, idx),
                    "chave_status_viagem": chave_status,
                    "cod_solicitacao": cod,
                    "cod_pre_solicitacao": cod_pre,
                    "placa_veiculo": placa_norm,
                    "tipo": tipo_doc,
                    "numero": numero_doc,
                    "origem": doc.get("origem") or "getEventoFimViagem:ColetasEntregas.Produtos.Documentos",
                    "raw": doc.get("raw") or doc,
                    "synced_at": now_iso(),
                })

            rows.append({
                "cod_solicitacao": cod,
                "cod_filial": to_int(v.get("CodFilial")),
                "placa_veiculo": normalize_placa(v.get("PlacaVeiculo")),
                "placa_carreta1": normalize_placa(v.get("PlacaCarreta1")),
                "cpf_motorista1": v.get("CPFMotorista1"),
                "status_viagem": v.get("StatusViagem"),
                "status_checklist": status_checklist,
                "aptidao_operacional": classificar_aptidao(status_checklist),
                "status_engate": v.get("StatusEngate"),
                "status_detalhamento": v.get("StatusDetalhamento"),
                "status_rota": v.get("StatusRota"),
                "status_liberacao_engate": v.get("StatusLiberacaoEngate"),
                "dentro_prazo": v.get("DentroPrazo"),
                "data_prev_inicio": parse_ts(v.get("DataHoraPrevIni")),
                "data_prev_fim": parse_ts(v.get("DataHoraPrevFim")),
                "data_real_inicio": parse_ts(v.get("DataHoraRealIni")),
                "data_real_fim": parse_ts(v.get("DataHoraRealFim")),
                "velocidade_media": to_float(v.get("VelocidadeMedia")),
                "maior_velocidade": to_float(v.get("MaiorVelocidade")),
                "tempo_total_viagem": to_float(v.get("TempoTotalViagem")),
                "tempo_parado": to_float(v.get("TempoParado")),
                "tempo_movimentando": to_float(v.get("TempoMovimentando")),
                "percentual_atraso": to_float(v.get("PercentualAtraso")),
                "desvios_rota": to_int(v.get("DesviosDeRota")),
                "eventos_velocidade": to_int(v.get("EventosVelocidade")),
                "link_timeline": v.get("LinkTimeLine"),
                "synced_at": now_iso(),
            })

        total = upsert_rows("raster_evento_fim_viagem", rows, "cod_solicitacao")

        # Salva também os documentos vinculados à viagem/SM encontrados no retorno
        # do getEventoFimViagem. Isso permite montar base por CARGA/CTE sem depender
        # de vínculo manual e sem criar/alterar nada na Raster.
        total_docs = 0
        if doc_rows:
            try:
                total_docs = upsert_rows("raster_status_viagem_documentos", doc_rows, "chave")
            except Exception as exc_docs:
                log_execucao("Evento fim viagem documentos", "erro", 0, str(exc_docs))
                print("Erro ao salvar documentos do getEventoFimViagem:", exc_docs)

        log_execucao(rotina, "sucesso", total + total_docs)
        return total + total_docs
    except Exception as exc:
        erro = _resumo_erro_raster({
            "mensagem": "Exception em getEventoFimViagem",
            "payload_enviado": _evento_fim_payload(),
            "erro": str(exc),
        })
        log_execucao(rotina, "erro", 0, erro)
        print(erro)
        return 0


def _coletar_placas_raster_status(limite: int = 50) -> list[str]:
    """Coleta placas automaticamente de várias bases já sincronizadas."""
    placas: list[str] = []
    vistos: set[str] = set()

    fontes = [
        ("raster_sm_geradas", "placa"),
        ("raster_evento_fim_viagem", "placa_veiculo"),
        ("raster_checklist_resultado", "veiculo"),
        ("wstt_veiculos", "placa"),
        ("wstt_viagens_telemetria", "placa"),
    ]
    for tabela, coluna in fontes:
        try:
            for p in select_distinct_values(tabela, coluna):
                placa = normalize_placa(p)
                if placa and placa not in vistos:
                    vistos.add(placa)
                    placas.append(placa)
                    if len(placas) >= limite:
                        return placas
        except Exception:
            continue
    return placas


def _coletar_documentos_status_viagem(limite: int = 50) -> list[dict[str, Any]]:
    """Coleta documentos já conhecidos para consultar getStatusViagem por Documentos.

    Não cria nada na Raster. Usa somente documentos já retornados/salvos no Supabase.
    Por padrão prioriza CTE e CARGA, porque são os documentos operacionais pedidos.
    Para alterar: RASTER_STATUS_DOCUMENTOS_TIPOS="CTE,CARGA,SHIPMENT,OUTROS".
    """
    tipos_permitidos = {
        t.strip().upper()
        for t in str(_env("RASTER_STATUS_DOCUMENTOS_TIPOS", "CTE,CARGA") or "CTE,CARGA").split(",")
        if t.strip()
    }
    fontes = [
        ("raster_status_viagem_documentos", "tipo", "numero"),
        ("raster_status_viagem_documentos", "tipo_documento", "numero_documento"),
    ]
    docs: list[dict[str, Any]] = []
    vistos: set[tuple[str, str]] = set()

    for tabela, col_tipo, col_numero in fontes:
        try:
            linhas = select_rows(tabela, f"{col_tipo},{col_numero}", limit=20000, order_by="synced_at")
        except Exception:
            continue
        for row in linhas:
            tipo = str(row.get(col_tipo) or "").upper().strip()
            numero = str(row.get(col_numero) or "").strip()
            if not tipo or not numero:
                continue
            if tipos_permitidos and tipo not in tipos_permitidos:
                continue
            chave = (tipo, numero)
            if chave in vistos:
                continue
            vistos.add(chave)
            docs.append({"Tipo": tipo, "Numero": numero})
            if len(docs) >= limite:
                return docs
    return docs


def _row_status_viagem(data: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    placa = normalize_placa(data.get("PlacaVeiculo") or payload.get("Placa"))
    cod_solicitacao = to_int(data.get("CodSolicitacao") or payload.get("CodSolicitacao"))
    cod_pre = to_int(data.get("CodPreSolicitacao") or payload.get("CodPreSolicitacao"))
    documentos = _extract_documentos_status_viagem(data)
    chave = _safe_key(cod_solicitacao, cod_pre, placa, data.get("StatusViagem"), payload.get("Placa"))
    return {
        "chave": chave,
        "cod_solicitacao": cod_solicitacao,
        "cod_pre_solicitacao": cod_pre,
        "cod_filial": to_int(data.get("CodFilial")),
        "cod_perfil_seguranca": to_int(data.get("CodPerfilSeguranca")),
        "cod_rota": to_int(data.get("CodRota")),
        "placa_veiculo": placa,
        "placa_carreta1_original": normalize_placa(data.get("PlacaCarreta1Original")),
        "placa_carreta1_atual": normalize_placa(data.get("PlacaCarreta1Atual")),
        "cpf_motorista1_original": data.get("CpfMotorista1Original"),
        "cpf_motorista1_atual": data.get("CpfMotorista1Atual"),
        "cnpj_transportador": data.get("CnpjTransportador") or data.get("CNPJTransportador"),
        "cnpj_cliente_orig": data.get("CnpjClienteOrig") or data.get("CNPJClienteOrig"),
        "cnpj_cliente_dest": data.get("CnpjClienteDest") or data.get("CNPJClienteDest"),
        "status_viagem": data.get("StatusViagem"),
        "data_prev_inicio": parse_ts(data.get("DataHoraPrevIni")),
        "data_prev_fim": parse_ts(data.get("DataHoraPrevFim")),
        "data_real_inicio": parse_ts(data.get("DataHoraRealIni")),
        "data_hora_ult_posicao": parse_ts(data.get("DataHoraUltPosicao")),
        "latitude_ult_posicao": to_float(data.get("LatitudeUltPosicao")),
        "longitude_ult_posicao": to_float(data.get("LongitudeUltPosicao")),
        "ref_ult_posicao": data.get("RefUltPosicao"),
        "documentos": documentos,
        "documentos_resumo": _documentos_resumo(documentos),
        "qtd_documentos": len(documentos),
        "raw": data,
        "payload": payload,
        "synced_at": now_iso(),
    }



def _rows_status_viagem_documentos(status_row: dict[str, Any]) -> list[dict[str, Any]]:
    docs = status_row.get("documentos") or []
    if not isinstance(docs, list):
        return []
    rows: list[dict[str, Any]] = []
    for idx, doc in enumerate(docs, start=1):
        if not isinstance(doc, dict):
            continue
        tipo = doc.get("tipo")
        numero = doc.get("numero")
        chave_doc = _safe_key(status_row.get("chave"), tipo, numero, idx)
        rows.append({
            "chave": chave_doc,
            "chave_status_viagem": status_row.get("chave"),
            "cod_solicitacao": status_row.get("cod_solicitacao"),
            "cod_pre_solicitacao": status_row.get("cod_pre_solicitacao"),
            "placa_veiculo": status_row.get("placa_veiculo"),
            "tipo": tipo,
            "numero": numero,
            "origem": doc.get("origem"),
            "raw": doc.get("raw") or doc,
            "synced_at": now_iso(),
        })
    return rows

def sync_status_viagem(limite: int | None = None) -> int:
    """Consulta getStatusViagem automaticamente, sem preencher nada.

    Não cria nada na Raster. Estratégia:
    1) consulta por Placa usando placas já existentes;
    2) consulta por Documentos já conhecidos, priorizando CTE e CARGA.

    Payload por documento conforme o manual:
    {"Documentos": [{"Tipo": "CTE", "Numero": "1234"}]}
    """
    rotina = "Status viagem"
    try:
        limite_real = limite or to_int(_env("RASTER_STATUS_VIAGEM_LIMITE", "50")) or 50
        limite_real = max(1, min(int(limite_real), 500))

        placas = _coletar_placas_raster_status(limite_real)
        documentos = _coletar_documentos_status_viagem(limite_real)

        if not placas and not documentos:
            log_execucao(rotina, "sucesso", 0, "Nenhuma placa/documento disponível para getStatusViagem.")
            return 0

        delay = to_float(_env("RASTER_DELAY_STATUS_VIAGEM_SECONDS", "1")) or 1
        rows: list[dict[str, Any]] = []
        erros: list[str] = []

        consultas: list[dict[str, Any]] = []
        for placa in placas:
            consultas.append({"Placa": placa})
        for doc in documentos:
            consultas.append({"Documentos": [doc]})

        consultas_unicas: list[dict[str, Any]] = []
        vistos_payload: set[str] = set()
        for payload in consultas:
            chave_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            if chave_payload in vistos_payload:
                continue
            vistos_payload.add(chave_payload)
            consultas_unicas.append(payload)

        for idx, payload in enumerate(consultas_unicas, start=1):
            label = payload.get("Placa") or payload.get("Documentos")
            try:
                data = call_raster("getStatusViagem", payload)
                if not _ok(data):
                    erros.append(f"{label}: {data.get('CodErro')} {data.get('MsgErro')}")
                    if payload.get("Placa"):
                        data = {**data, "PlacaVeiculo": payload.get("Placa")}
                rows.append(_row_status_viagem(data, payload))
            except Exception as exc:
                erros.append(f"{label}: {exc}")
            if idx < len(consultas_unicas) and delay > 0:
                time.sleep(delay)

        total = upsert_rows("raster_status_viagem", rows, "chave") if rows else 0
        doc_rows: list[dict[str, Any]] = []
        for row in rows:
            doc_rows.extend(_rows_status_viagem_documentos(row))
        if doc_rows:
            upsert_rows("raster_status_viagem_documentos", doc_rows, "chave")

        resumo = f"placas={len(placas)} docs_cte_carga={len(documentos)} consultas={len(consultas_unicas)}"
        if erros:
            resumo += " | " + " | ".join(erros[:20])
        log_execucao(rotina, "sucesso" if not erros else "parcial", total, resumo)
        return total
    except Exception as exc:
        log_execucao(rotina, "erro", 0, str(exc))
        return 0


def sync_historico_testes() -> int:
    rotina = "Histórico checklist"
    try:
        placas = select_distinct_values("raster_evento_fim_viagem", "placa_veiculo")
        for p in select_distinct_values("raster_sm_geradas", "placa"):
            if p and p not in placas:
                placas.append(p)
        placas = [p for p in placas if p]

        if not placas:
            raise RuntimeError("Nenhuma placa encontrada. Sincronize viagens finalizadas ou SM abertas primeiro.")

        rows: list[dict[str, Any]] = []
        erros: list[str] = []

        for placa in placas:
            try:
                data = call_raster("getHistoricoTestes", {"Veiculo": placa})
                if not _ok(data):
                    erros.append(f"{placa}: {data.get('MsgErro') or data.get('CodErro')}")
                    continue

                testes = _list_from(data, "Testes", "Teste", "CheckLists", "CheckList")
                for t in testes:
                    codigo = t.get("Codigo") or t.get("CodCheckList") or f"{placa}-{t.get('DataSol') or now_iso()}"
                    rows.append({
                        "codigo": str(codigo),
                        "veiculo": normalize_placa(t.get("Veiculo") or placa),
                        "carreta01": normalize_placa(t.get("Carreta01")),
                        "carreta02": normalize_placa(t.get("Carreta02")),
                        "carreta03": normalize_placa(t.get("Carreta03")),
                        "data_sol": t.get("DataSol"),
                        "teste_temp": t.get("TesteTemp"),
                        "tipo": t.get("Tipo"),
                        "synced_at": now_iso(),
                    })
            except Exception as exc:
                erros.append(f"{placa}: {exc}")

        total = upsert_rows("raster_checklist", rows, "codigo")
        log_execucao(rotina, "sucesso" if total else "alerta", total, " | ".join(erros[:15]) if erros else None)
        return total
    except Exception as exc:
        log_execucao(rotina, "erro", 0, str(exc))
        raise


def _pick(data: dict[str, Any], *names: str) -> Any:
    """Busca uma chave no retorno da Raster aceitando variações de maiúsculas/minúsculas."""
    if not isinstance(data, dict):
        return None
    lower = {str(k).lower(): v for k, v in data.items()}
    for name in names:
        if name in data:
            return data.get(name)
        value = lower.get(str(name).lower())
        if value is not None:
            return value
    return None


def _first_result_record(data: dict[str, Any]) -> dict[str, Any]:
    """Tenta localizar o registro principal de resultado dentro do retorno da Raster."""
    if not isinstance(data, dict):
        return {}
    for key in ("Resultados", "ResultadoCheckList", "ResultadoChecklist", "CheckList", "CheckLists", "Resultado", "Dados"):
        value = data.get(key)
        if isinstance(value, list) and value:
            return value[0] if isinstance(value[0], dict) else {"valor": value[0]}
        if isinstance(value, dict):
            # Se o dict tiver uma lista dentro, pega o primeiro item dessa lista.
            for sub in value.values():
                if isinstance(sub, list) and sub:
                    return sub[0] if isinstance(sub[0], dict) else {"valor": sub[0]}
            return value
    return data


def _to_bool_apto(resultado: Any, status: Any = None) -> bool | None:
    txt = str(resultado or status or "").strip().upper()
    if txt in ("A", "APROVADO", "APTA", "APTO", "S", "SIM", "OK", "LIBERADO"):
        return True
    if txt in ("R", "REPROVADO", "NAO_APTO", "NÃO APTO", "NAO APTA", "N", "NAO", "NÃO", "BLOQUEADO"):
        return False
    return None


def _parse_produtos(value: Any) -> Any:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (list, dict)):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return text


def _safe_select_rows(table: str, columns: str = "*", limit: int = 20000, order_by: str | None = None) -> list[dict[str, Any]]:
    try:
        return select_rows(table, columns, limit, order_by=order_by)
    except Exception as exc:
        print(f"Aviso: não foi possível consultar {table}: {exc}")
        return []


def _ensure_tabela(nome_tabela: str) -> None:
    """Garante que a tabela de apoio foi carregada ao menos uma vez."""
    nome = str(nome_tabela or "").strip().upper()
    if not nome:
        return
    existentes = _safe_select_rows("raster_tabelas", "tabela,codigo,descricao,dados", 5)
    if not any(str(x.get("tabela") or "").upper() == nome for x in existentes):
        try:
            sync_get_tabela(nome)
        except Exception as exc:
            print(f"Não foi possível sincronizar getTabela({nome}): {exc}")


def _linhas_tabela(nome_tabela: str) -> list[dict[str, Any]]:
    nome = str(nome_tabela or "").strip().upper()
    if not nome:
        return []
    linhas = _safe_select_rows("raster_tabelas", "tabela,codigo,descricao,dados", 20000)
    filtradas = [x for x in linhas if str(x.get("tabela") or "").upper() == nome and str(x.get("codigo") or "").upper() != "RAW"]
    if not filtradas:
        _ensure_tabela(nome)
        linhas = _safe_select_rows("raster_tabelas", "tabela,codigo,descricao,dados", 20000)
        filtradas = [x for x in linhas if str(x.get("tabela") or "").upper() == nome and str(x.get("codigo") or "").upper() != "RAW"]
    return filtradas


def _primeiro_codigo_tabela(nome_tabela: str) -> int | None:
    linhas = _linhas_tabela(nome_tabela)
    for row in linhas:
        cod = to_int(row.get("codigo"))
        if cod:
            return cod
        dados = row.get("dados") or {}
        if isinstance(dados, dict):
            cod = to_int(_pick(dados, "Codigo", "CodFilial", "CodPerfilSeguranca", "CodProduto", "CodigoProduto", "Cod"))
            if cod:
                return cod
    return None


def get_default_cod_filial(cod_filial: Any = None) -> int | None:
    return to_int(cod_filial) or to_int(_env("RASTER_COD_FILIAL")) or _primeiro_codigo_tabela("FILIAIS")


def get_default_cod_perfil(cod_perfil: Any = None) -> int | None:
    return to_int(cod_perfil) or to_int(_env("RASTER_COD_PERFIL_SEGURANCA")) or _primeiro_codigo_tabela("PERFIL_SEGURANCA")


def _produto_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Monta um item de Produtos a partir do getTabela(PRODUTOS).

    Na teoria o manual marca Produtos como N no retorno/layout, porém no ambiente
    da Raster pode haver validação por apólice/perfil exigindo a tag Produtos.
    Quando isso ocorre, o retorno vem com CodErro 105 e MsgErro: Campo obrigatório Produtos.
    """
    dados = row.get("dados") if isinstance(row, dict) else None
    if not isinstance(dados, dict):
        dados = row if isinstance(row, dict) else {}

    cod = to_int(_pick(dados, "CodProduto", "CodigoProduto", "Codigo", "Código", "Cod", "ID", "Id") or row.get("codigo"))
    if not cod:
        return None

    # Valor precisa existir quando Produtos é enviado. Use .env para controlar valor real,
    # senão assume 1.00 somente para a consulta passar pela validação da API.
    valor = to_float(_env("RASTER_VALOR_PRODUTO", "1")) or 1.0
    return {"CodProduto": cod, "Valor": valor}


def get_default_produtos(produtos: Any = None) -> Any:
    """Retorna Produtos para getGerarResultadoCheckList.

    Ordem de prioridade:
    1) Produtos informados na tela/função;
    2) RASTER_PRODUTOS no .env;
    3) primeiro produto retornado pelo getTabela(PRODUTOS), salvo em raster_tabelas;
    4) fallback de viagem vazia CodProduto 999999999, conforme padrão do manual para sem produto.
    """
    parsed = _parse_produtos(produtos) or _parse_produtos(_env("RASTER_PRODUTOS", ""))
    if parsed:
        # Se usuário passou um dict único, transforma em lista.
        return parsed if isinstance(parsed, list) else [parsed]

    # Tenta carregar PRODUTOS automaticamente via getTabela e usar o primeiro código válido.
    linhas = _linhas_tabela("PRODUTOS")
    for row in linhas:
        produto = _produto_from_row(row)
        if produto:
            return [produto]

    # Fallback: manual cita código para solicitação sem produto/viagem vazia em alguns fluxos.
    valor = to_float(_env("RASTER_VALOR_PRODUTO", "1")) or 1.0
    return [{"CodProduto": 999999999, "Valor": valor}]


def listar_placas_para_checklist(limite: int = 500) -> list[str]:
    """Lista placas disponíveis para rodar checklist em lote sem digitar uma por uma."""
    placas: list[str] = []
    vistos: set[str] = set()

    fontes = [
        ("raster_evento_fim_viagem", "placa_veiculo"),
        ("raster_sm_geradas", "placa"),
        ("wstt_veiculos", "placa"),
        ("vw_wstt_resumo_placa", "placa"),
    ]
    for tabela, coluna in fontes:
        for row in _safe_select_rows(tabela, coluna, 20000, order_by=None):
            placa = normalize_placa(row.get(coluna))
            if placa and placa not in vistos:
                vistos.add(placa)
                placas.append(placa)
                if len(placas) >= limite:
                    return placas
    return placas


def _extract_lista_generica(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extrai listas genéricas retornadas pelo getTabela.

    A Raster pode mudar o nome do nó conforme a tabela: Tabelas, Dados, Itens,
    FILIAIS, PERFIL_SEGURANCA, PRODUTOS etc. Essa função procura qualquer lista
    de dicionários dentro do retorno para evitar retorno zero silencioso.
    """
    if not isinstance(data, dict):
        return []

    preferidos = (
        "Tabelas", "Tabela", "Dados", "Itens", "Registros", "Filiais", "FILIAIS",
        "PerfilSeguranca", "PERFIL_SEGURANCA", "Produtos", "PRODUTOS",
        "Erros", "ERROS_WEBSERVICE"
    )
    for key in preferidos:
        value = data.get(key)
        if isinstance(value, list):
            return [v for v in value if isinstance(v, dict)]
        if isinstance(value, dict):
            for sub in value.values():
                if isinstance(sub, list):
                    return [v for v in sub if isinstance(v, dict)]

    # fallback: qualquer lista de dict encontrada em primeiro nível
    for value in data.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
        if isinstance(value, dict):
            for sub in value.values():
                if isinstance(sub, list) and sub and isinstance(sub[0], dict):
                    return sub
    return []


def _codigo_generico(item: dict[str, Any], fallback: str) -> str:
    for key in (
        "Codigo", "Código", "Cod", "ID", "Id",
        "CodFilial", "CodigoFilial",
        "CodPerfilSeguranca", "CodigoPerfilSeguranca",
        "CodProduto", "CodigoProduto",
        "CodErro", "NomeTabela", "Nome", "Descricao", "Descrição"
    ):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return fallback


def _descricao_generica(item: dict[str, Any]) -> str | None:
    for key in ("Descricao", "Descrição", "Nome", "RazaoSocial", "Fantasia", "Tabela", "Produto", "Perfil"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def sync_get_tabela(nome_tabela: str) -> int:
    """Consulta uma tabela de cadastro da Raster via getTabela e salva em raster_tabelas.

    Usado para FILIAIS, PERFIL_SEGURANCA, PRODUTOS e ERROS_WEBSERVICE.
    """
    nome = str(nome_tabela or "").strip().upper()
    if not nome:
        raise RuntimeError("Informe o NomeTabela para consultar a Raster.")

    rotina = f"getTabela {nome}"
    try:
        data = call_raster("getTabela", {"NomeTabela": nome})
        if not _ok(data):
            # mesmo com erro, grava log para aparecer no terminal
            raise RuntimeError(f"Raster retornou erro: {data.get('MsgErro')} / {data.get('CodErro')}")

        itens = _extract_lista_generica(data)
        rows: list[dict[str, Any]] = []

        # Se não vier lista, salva um registro RAW para diagnóstico.
        if not itens:
            rows.append({
                "tabela": nome,
                "codigo": "RAW",
                "descricao": "Retorno sem lista identificada",
                "dados": data,
                "synced_at": now_iso(),
            })
        else:
            for idx, item in enumerate(itens, start=1):
                rows.append({
                    "tabela": nome,
                    "codigo": _codigo_generico(item, str(idx)),
                    "descricao": _descricao_generica(item),
                    "dados": item,
                    "synced_at": now_iso(),
                })

        total = upsert_rows("raster_tabelas", rows, "tabela,codigo")
        log_execucao(rotina, "sucesso", total)
        return total
    except Exception as exc:
        log_execucao(rotina, "erro", 0, str(exc))
        raise


def sync_tabelas_checklist() -> int:
    """Consulta as tabelas necessárias ao fluxo de checklist."""
    total = 0
    for nome in ["FILIAIS", "PERFIL_SEGURANCA", "PRODUTOS", "ERROS_WEBSERVICE"]:
        total += sync_get_tabela(nome)
    return total


def _row_solicitacao_checklist(data: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    rec = _first_result_record(data) if isinstance(data, dict) else {"raw_value": data}
    cod = to_int(_pick(rec, "CodCheckList", "cod_checklist") or _pick(data, "CodCheckList", "cod_checklist"))
    cod_erro = _pick(rec, "CodErro", "cod_erro") or _pick(data, "CodErro", "cod_erro")
    msg_erro = _pick(rec, "MsgErro", "msg_erro") or _pick(data, "MsgErro", "msg_erro")
    placa = normalize_placa(payload.get("PlacaVeiculo"))
    chave = str(cod or f"{placa or 'SEM_PLACA'}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}")
    raw = dict(data) if isinstance(data, dict) else {"raw_value": data}
    raw["payload_enviado"] = payload
    return {
        "chave": chave,
        "cod_checklist": cod,
        "veiculo": placa,
        "cod_filial": to_int(payload.get("CodFilial")),
        "placa_carreta1": normalize_placa(payload.get("PlacaCarreta1")),
        "placa_carreta2": normalize_placa(payload.get("PlacaCarreta2")),
        "placa_carreta3": normalize_placa(payload.get("PlacaCarreta3")),
        "vinculo": payload.get("Vinculo"),
        "tipo": payload.get("Tipo"),
        "sensor_temperatura": payload.get("SensorTemperatura"),
        "responsavel": payload.get("Responsavel"),
        "celular1": payload.get("Celular1"),
        "celular2": payload.get("Celular2"),
        "data_hora_agendada": payload.get("DataHoraAgendada"),
        "cod_erro": str(cod_erro) if cod_erro is not None else None,
        "msg_erro": msg_erro,
        "raw": raw,
        "synced_at": now_iso(),
    }


def set_incluir_checklist(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Bloqueio de segurança: este projeto NÃO cria checklist na Raster."""
    raise RuntimeError(
        "Criação de checklist desativada. Este app só consulta checklists já existentes via getGerarResultadoCheckList."
    )


def set_incluir_checklist_e_consultar_resultado(*args: Any, **kwargs: Any) -> int:
    """Bloqueio de segurança: este projeto NÃO cria checklist na Raster."""
    raise RuntimeError(
        "Criação de checklist desativada. Este app só consulta checklists já existentes via getGerarResultadoCheckList."
    )


def sync_incluir_checklist_todos_veiculos(*args: Any, **kwargs: Any) -> int:
    """Bloqueio de segurança: este projeto NÃO cria checklist em lote na Raster."""
    raise RuntimeError(
        "Criação de checklist em lote desativada. Este app só consulta CodCheckList já existente."
    )

def _contar_status_checklist_resultado() -> dict[str, int]:
    """Conta os status atuais salvos em raster_checklist_resultado."""
    rows = _safe_select_rows("raster_checklist_resultado", "status", 20000, order_by=None)
    out: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "SEM_STATUS").upper().strip()
        out[status] = out.get(status, 0) + 1
    return out


def sync_resultado_checklist_ate_finalizar(
    cod_filial: Any = None,
    cod_perfil_seguranca: Any = None,
    produtos: Any = None,
    tentativas: int = 4,
    intervalo_segundos: int = 30,
) -> dict[str, Any]:
    """Reconsulta getGerarResultadoCheckList algumas vezes até sair de AI/ST/AE/CV/ET.

    DataGeracao, DataExpiracao, Resultado e UrlDocumento só vêm quando o
    status estiver FI (Finalizado). Quando a Raster devolve AI, significa
    Aguardando Início; nesse momento ainda é normal esses campos ficarem vazios.
    """
    rotina = "Reconsulta resultado checklist até finalizar"
    pendentes = {"ST", "AI", "AE", "CV", "ET", "SEM_STATUS", ""}
    tentativas = max(1, int(tentativas or 1))
    intervalo_segundos = max(0, int(intervalo_segundos or 0))
    resumo = {"tentativas": 0, "resultados": 0, "status": {}}

    try:
        for tentativa in range(1, tentativas + 1):
            qtd = sync_resultado_checklist(
                cod_filial=cod_filial,
                cod_perfil_seguranca=cod_perfil_seguranca,
                produtos=produtos,
            )
            status_count = _contar_status_checklist_resultado()
            resumo = {"tentativas": tentativa, "resultados": qtd, "status": status_count}
            ainda_pendente = sum(qtd for status, qtd in status_count.items() if str(status).upper() in pendentes)

            log_execucao(
                rotina,
                "sucesso" if ainda_pendente == 0 else "aguardando",
                qtd,
                f"tentativa={tentativa}/{tentativas} status={status_count}",
            )

            if ainda_pendente == 0:
                break
            if tentativa < tentativas and intervalo_segundos > 0:
                time.sleep(intervalo_segundos)

        return resumo
    except Exception as exc:
        log_execucao(rotina, "erro", 0, str(exc))
        raise


def sync_checklist_fluxo_automatico(
    cod_filial: Any = None,
    cod_perfil_seguranca: Any = None,
    limite: int = 500,
    tipo: str = "NORMAL",
    pular_ja_solicitados: bool = True,
    tentativas_resultado: int = 4,
    intervalo_resultado_segundos: int = 30,
) -> dict[str, Any]:
    """Consulta automática de resultados SEM criar checklist.

    Importante: esta função NÃO chama setIncluirCheckList.
    Ela apenas:
    1) Atualiza tabelas de apoio via getTabela.
    2) Reconsulta getGerarResultadoCheckList usando CodCheckList já existente
       em raster_checklist_solicitacoes ou raster_checklist_resultado.

    Use esta rotina quando você quer apenas consultar checklists já criados
    pela Raster/sistema, sem gerar novas solicitações.
    """
    rotina = "Consulta automática checklist sem criação"
    resumo = {"tabelas": 0, "checklists_solicitados": 0, "resultados": 0, "tentativas_resultado": 0, "status_resultado": {}}
    try:
        resumo["tabelas"] = sync_tabelas_checklist()
        filial = get_default_cod_filial(cod_filial)
        perfil = get_default_cod_perfil(cod_perfil_seguranca)

        if not filial:
            raise RuntimeError("Não encontrei CodFilial. Rode getTabela FILIAIS ou configure RASTER_COD_FILIAL.")
        if not perfil:
            raise RuntimeError("Não encontrei CodPerfilSeguranca. Rode getTabela PERFIL_SEGURANCA ou configure RASTER_COD_PERFIL_SEGURANCA.")

        reconsulta = sync_resultado_checklist_ate_finalizar(
            cod_filial=filial,
            cod_perfil_seguranca=perfil,
            produtos=None,  # None = montar Produtos automaticamente via getTabela/RASTER_PRODUTOS
            tentativas=tentativas_resultado,
            intervalo_segundos=intervalo_resultado_segundos,
        )
        resumo["resultados"] = int(reconsulta.get("resultados") or 0)
        resumo["tentativas_resultado"] = int(reconsulta.get("tentativas") or 0)
        resumo["status_resultado"] = reconsulta.get("status") or {}
        log_execucao(
            rotina,
            "sucesso",
            int(resumo.get("resultados") or 0),
            f"tabelas={resumo['tabelas']} consultas={resumo['resultados']} status={resumo['status_resultado']} sem_criar_checklist=True",
        )
        return resumo
    except Exception as exc:
        log_execucao(rotina, "erro", 0, str(exc))
        raise

def _normalizar_payload_resultado_checklist(
    cod_checklist: Any = None,
    cod_filial: Any = None,
    cod_perfil_seguranca: Any = None,
    produtos: Any = None,
    veiculo: Any = None,
) -> dict[str, Any]:
    """Monta o payload do getGerarResultadoCheckList conforme manual página 159.

    Embora o layout indique Produtos como lista não obrigatória em alguns trechos,
    o ambiente de produção pode retornar CodErro 105 exigindo Produtos. Por isso
    o sistema agora monta Produtos automaticamente via getTabela(PRODUTOS) ou fallback.
    """
    payload: dict[str, Any] = {}
    cod = to_int(cod_checklist)
    placa = normalize_placa(veiculo)

    # Conforme manual: pode enviar CodCheckList OU Veiculo.
    # Quando CodCheckList for informado, a placa deixa de ser obrigatória.
    # Quando Veiculo for informado, CodCheckList deixa de ser obrigatório.
    if cod:
        payload["CodCheckList"] = cod
    elif placa:
        payload["Veiculo"] = placa

    filial = get_default_cod_filial(cod_filial)
    if filial:
        payload["CodFilial"] = filial

    perfil = get_default_cod_perfil(cod_perfil_seguranca)
    if perfil:
        payload["CodPerfilSeguranca"] = perfil

    produtos_final = get_default_produtos(produtos)
    if produtos_final:
        payload["Produtos"] = produtos_final

    return payload


def _row_resultado_checklist(data: dict[str, Any], payload: dict[str, Any], veiculo: Any = None) -> dict[str, Any]:
    """Normaliza QUALQUER resposta do getGerarResultadoCheckList.

    Importante: a Raster pode responder CodErro/MsgErro, ou apenas Status sem CodResultado.
    Antes o sistema só gravava quando havia retorno "completo", por isso parecia que trouxe 0.
    Agora gravamos também respostas parciais/erros no raw para diagnóstico no dashboard.
    """
    if not isinstance(data, dict):
        data = {"raw_value": data}

    rec = _first_result_record(data)
    resultado = _pick(rec, "Resultado", "resultado") or _pick(data, "Resultado", "resultado")
    status = _pick(rec, "Status", "status") or _pick(data, "Status", "status")
    cod_erro = _pick(rec, "CodErro", "cod_erro") or _pick(data, "CodErro", "cod_erro")
    msg_erro = _pick(rec, "MsgErro", "msg_erro") or _pick(data, "MsgErro", "msg_erro")

    if not status:
        if str(cod_erro or "").strip() not in ("", "0"):
            status = f"ERRO_{cod_erro}"
        else:
            status = "SEM_STATUS"

    ident = (
        _pick(rec, "CodCheckList", "cod_checklist")
        or payload.get("CodCheckList")
        or _pick(rec, "Veiculo", "Placa", "PlacaVeiculo")
        or payload.get("Veiculo")
        or veiculo
        or "SEM_IDENTIFICADOR"
    )
    ident_norm = str(normalize_placa(ident) or ident).replace(" ", "_").replace("/", "_")

    cod_resultado = (
        _pick(rec, "CodResultado", "CodigoResultado", "Codigo", "cod_resultado")
        or _pick(data, "CodResultado", "CodigoResultado", "Codigo", "cod_resultado")
        or f"CHK-{ident_norm}"
    )

    raw = dict(data)
    raw["payload_enviado"] = payload
    if msg_erro:
        raw["msg_erro_normalizada"] = msg_erro

    return {
        "cod_resultado": str(cod_resultado),
        "cod_checklist": to_int(_pick(rec, "CodCheckList", "cod_checklist") or payload.get("CodCheckList")),
        "veiculo": normalize_placa(_pick(rec, "Veiculo", "Placa", "PlacaVeiculo") or payload.get("Veiculo") or veiculo),
        "cod_filial": to_int(_pick(rec, "CodFilial", "cod_filial") or payload.get("CodFilial")),
        "cod_perfil_seguranca": to_int(_pick(rec, "CodPerfilSeguranca", "cod_perfil_seguranca") or payload.get("CodPerfilSeguranca")),
        "status": status,
        "resultado": resultado,
        "apto": _to_bool_apto(resultado, status),
        "data_geracao": parse_ts(_pick(rec, "DataGeracao", "data_geracao") or _pick(data, "DataGeracao")),
        "data_expiracao": parse_ts(_pick(rec, "DataExpiracao", "data_expiracao") or _pick(data, "DataExpiracao")),
        "url_documento": _pick(rec, "UrlDocumento", "URLDocumento", "LinkDocumento", "url_documento") or _pick(data, "UrlDocumento"),
        "produtos": _pick(rec, "Produtos", "produtos") or payload.get("Produtos"),
        "raw": raw,
        "synced_at": now_iso(),
    }


def sync_resultado_checklist(
    cod_checklist: Any = None,
    cod_filial: Any = None,
    cod_perfil_seguranca: Any = None,
    produtos: Any = None,
    veiculo: Any = None,
) -> int:
    """Executa o método Raster getGerarResultadoCheckList e grava em raster_checklist_resultado.

    Substitui a rotina antiga baseada em getHistoricoTestes. Pode rodar de duas formas:
    1) Manual, informando CodCheckList/filial/perfil/produtos pela tela.
    2) Em lote, lendo registros já existentes em raster_checklist_resultado que tenham cod_checklist.
    """
    rotina = "getGerarResultadoCheckList"
    try:
        from supabase_db import select_rows

        itens: list[dict[str, Any]] = []
        if cod_checklist or normalize_placa(veiculo):
            itens.append({
                "cod_checklist": cod_checklist,
                "cod_filial": cod_filial,
                "cod_perfil_seguranca": cod_perfil_seguranca,
                "produtos": produtos,
                "veiculo": veiculo,
            })
        else:
            # Usa fontes existentes como fila de processamento.
            # Prioridade 1: solicitações geradas pelo setIncluirCheckList, porque elas têm CodCheckList válido.
            solicitacoes = select_rows(
                "raster_checklist_solicitacoes",
                "cod_checklist,veiculo,cod_filial",
                20000,
                order_by="synced_at",
            )
            itens = [
                {
                    "cod_checklist": x.get("cod_checklist"),
                    "veiculo": x.get("veiculo"),
                    "cod_filial": x.get("cod_filial"),
                    "cod_perfil_seguranca": cod_perfil_seguranca,
                    "produtos": produtos,
                }
                for x in solicitacoes
                if to_int(x.get("cod_checklist"))
            ]

            # Prioridade 2: tabela de resultado já existente, quando tiver CodCheckList OU Veiculo.
            if not itens:
                base = select_rows(
                    "raster_checklist_resultado",
                    "cod_checklist,veiculo,cod_filial,cod_perfil_seguranca,produtos",
                    20000,
                    order_by="synced_at",
                )
                itens = [x for x in base if to_int(x.get("cod_checklist")) or normalize_placa(x.get("veiculo"))]

            # Prioridade 3: viagens finalizadas Raster, usando a placa do veículo.
            # O método getGerarResultadoCheckList permite consultar por Veiculo quando não há CodCheckList.
            if not itens:
                viagens = select_rows(
                    "raster_evento_fim_viagem",
                    "placa_veiculo,cod_filial",
                    20000,
                    order_by="synced_at",
                )
                placas_vistas = set()
                for v in viagens:
                    placa = normalize_placa(v.get("placa_veiculo"))
                    if placa and placa not in placas_vistas:
                        placas_vistas.add(placa)
                        itens.append({
                            "veiculo": placa,
                            "cod_filial": v.get("cod_filial"),
                            "cod_perfil_seguranca": cod_perfil_seguranca,
                            "produtos": produtos,
                        })

            # Prioridade 3: SM abertas, usando a placa.
            if not itens:
                sms = select_rows("raster_sm_geradas", "placa", 20000, order_by="synced_at")
                placas_vistas = set()
                for sm in sms:
                    placa = normalize_placa(sm.get("placa"))
                    if placa and placa not in placas_vistas:
                        placas_vistas.add(placa)
                        itens.append({"veiculo": placa, "cod_filial": cod_filial, "cod_perfil_seguranca": cod_perfil_seguranca, "produtos": produtos})

            if not itens:
                raise RuntimeError(
                    "Nenhum CodCheckList ou Veiculo encontrado para consultar o getGerarResultadoCheckList. "
                    "Sincronize viagens/SM abertas primeiro ou informe manualmente uma placa na tela Raster."
                )

        rows: list[dict[str, Any]] = []
        erros: list[str] = []
        for item in itens:
            payload = _normalizar_payload_resultado_checklist(
                cod_checklist=item.get("cod_checklist"),
                cod_filial=item.get("cod_filial"),
                cod_perfil_seguranca=item.get("cod_perfil_seguranca"),
                produtos=item.get("produtos"),
                veiculo=item.get("veiculo"),
            )

            ident = payload.get("CodCheckList") or payload.get("Veiculo") or item.get("veiculo") or "SEM_IDENTIFICADOR"

            if not payload.get("CodCheckList") and not payload.get("Veiculo"):
                erros.append(f"{ident}: sem CodCheckList e sem Veiculo")
                continue
            if not payload.get("CodFilial"):
                erros.append(f"{ident}: sem CodFilial")
                continue
            if not payload.get("CodPerfilSeguranca"):
                erros.append(f"{ident}: sem CodPerfilSeguranca")
                continue
            try:
                data = call_raster("getGerarResultadoCheckList", payload)
                # Mesmo quando CodErro != 0, gravamos o raw e o status ERRO_xxx.
                # Assim o dashboard mostra o motivo real em vez de retornar 0 silenciosamente.
                if not _ok(data):
                    erros.append(f"{ident}: CodErro={data.get('CodErro')} MsgErro={data.get('MsgErro')}")
                rows.append(_row_resultado_checklist(data, payload, item.get("veiculo")))
            except Exception as exc:
                erros.append(f"{ident}: {exc}")
                rows.append(_row_resultado_checklist({
                    "CodErro": "EXCEPTION",
                    "MsgErro": str(exc),
                    "Metodo": "getGerarResultadoCheckList",
                }, payload, item.get("veiculo")))

        total = upsert_rows("raster_checklist_resultado", rows, "cod_resultado")
        status_log = "sucesso" if total and not erros else ("alerta" if total else "erro")
        log_execucao(rotina, status_log, total, " | ".join(erros[:20]) if erros else None)
        return total
    except Exception as exc:
        log_execucao(rotina, "erro", 0, str(exc))
        raise


def get_kpis() -> dict[str, Any]:
    from supabase_db import select_rows

    try:
        status = select_rows("vw_raster_status_veiculo", "placa,aptidao_operacional,dentro_prazo,desvios_rota", 20000)
        sm = select_rows("raster_sm_geradas", "codigo,placa", 20000)
        return {
            "sm_abertas": len(sm),
            "placas": len({x.get("placa") for x in status if x.get("placa")}),
            "aptos": sum(1 for x in status if x.get("aptidao_operacional") == "APTO"),
            "nao_aptos": sum(1 for x in status if x.get("aptidao_operacional") == "NAO_APTO"),
            "pendentes": sum(1 for x in status if x.get("aptidao_operacional") in ("PENDENTE", "INDEFINIDO", "SEM_STATUS")),
            "fora_prazo": sum(1 for x in status if x.get("dentro_prazo") == "N"),
            "desvios": sum(int(x.get("desvios_rota") or 0) for x in status),
        }
    except Exception:
        return {"sm_abertas": 0, "placas": 0, "aptos": 0, "nao_aptos": 0, "pendentes": 0, "fora_prazo": 0, "desvios": 0}

# ============================================================
# OVERRIDES FINAIS - CHECKLIST SOMENTE CONSULTA, COM HISTÓRICO
# ============================================================
# Importante: nada abaixo chama setIncluirCheckList. O fluxo correto para
# consultar datas obrigatórias é:
# 1) getHistoricoTestes por placa para achar checklists existentes (Codigo/CodCheckList)
# 2) getGerarResultadoCheckList com CodCheckList + CodFilial + CodPerfilSeguranca + Produtos
# 3) considerar válido somente quando vier DataGeracao e DataExpiracao.

PREFERRED_PERFIL_PRODUTOS = {
    14341: [2134],  # DDR SHOPEE - LINE HAUL OWN FLEET - FROTA - ESSOR
    19902: [2134],  # DDR SHOPEE - LINE HAUL OWN FLEET - FROTA - CARGA EXPRESS
    19882: [2134],  # DDR SHOPEE LINE HAUL OWN FLEET - AGREGADOS E TERCEIROS - CARGA EXPRESS
    17967: [2134],  # DDR SHOPEE LINE HAUL OWN FLEET - AGREGADOS/TERCEIROS - ESSOR
}


def _dados_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except Exception:
            return {}
    return {}


def _produtos_do_perfil(cod_perfil: Any) -> list[dict[str, Any]]:
    perfil = to_int(cod_perfil) or to_int(_env("RASTER_COD_PERFIL_SEGURANCA")) or 14341
    valor = to_float(_env("RASTER_VALOR_PRODUTO", "1")) or 1.0

    # 1) Primeiro tenta localizar os produtos associados ao perfil na raster_tabelas.
    for row in _linhas_tabela("PERFIL_SEGURANCA"):
        if to_int(row.get("codigo")) != perfil:
            continue
        dados = _dados_to_dict(row.get("dados"))
        produtos = dados.get("Produtos") if isinstance(dados, dict) else None
        if isinstance(produtos, list) and produtos:
            saida = []
            for p in produtos:
                cod_prod = to_int(_pick(p, "CodProduto", "CodigoProduto", "Codigo", "Cod")) if isinstance(p, dict) else None
                if cod_prod:
                    saida.append({"CodProduto": cod_prod, "Valor": valor})
            if saida:
                return saida

    # 2) Fallback inteligente com base nos perfis que você mandou.
    if perfil in PREFERRED_PERFIL_PRODUTOS:
        return [{"CodProduto": p, "Valor": valor} for p in PREFERRED_PERFIL_PRODUTOS[perfil]]

    # 3) Fallback final: Produto diversos, usado nos perfis Shopee enviados.
    return [{"CodProduto": 2134, "Valor": valor}]


def get_default_cod_perfil(cod_perfil: Any = None) -> int | None:  # type: ignore[override]
    # Prioridade: tela/função > .env > perfil Shopee/Frota enviado pelo usuário > primeiro perfil disponível.
    cod = to_int(cod_perfil) or to_int(_env("RASTER_COD_PERFIL_SEGURANCA"))
    if cod:
        return cod
    # Preferência operacional pelos dados enviados: FROTA ESSOR.
    return 14341


def get_default_produtos(produtos: Any = None) -> Any:  # type: ignore[override]
    parsed = _parse_produtos(produtos) or _parse_produtos(_env("RASTER_PRODUTOS", ""))
    if parsed:
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    perfil = get_default_cod_perfil(None)
    return _produtos_do_perfil(perfil)


def _normalizar_payload_resultado_checklist(
    cod_checklist: Any = None,
    cod_filial: Any = None,
    cod_perfil_seguranca: Any = None,
    produtos: Any = None,
    veiculo: Any = None,
) -> dict[str, Any]:  # type: ignore[override]
    payload: dict[str, Any] = {}
    cod = to_int(cod_checklist)
    placa = normalize_placa(veiculo)

    if cod:
        payload["CodCheckList"] = cod
    elif placa:
        payload["Veiculo"] = placa

    filial = get_default_cod_filial(cod_filial)
    perfil = get_default_cod_perfil(cod_perfil_seguranca)
    produtos_final = get_default_produtos(produtos)

    if filial:
        payload["CodFilial"] = filial
    if perfil:
        payload["CodPerfilSeguranca"] = perfil
    if produtos_final:
        payload["Produtos"] = produtos_final

    return payload


def _codigo_checklist_from_teste(teste: dict[str, Any]) -> int | None:
    return to_int(
        _pick(teste, "CodCheckList", "CodigoCheckList", "Codigo", "Código", "Cod", "ID", "Id")
    )


def _placas_base_para_historico(limite: int = 500) -> list[str]:
    placas: list[str] = []
    vistos: set[str] = set()
    fontes = [
        ("raster_evento_fim_viagem", "placa_veiculo"),
        ("raster_sm_geradas", "placa"),
        ("wstt_veiculos", "placa"),
        ("vw_wstt_resumo_placa", "placa"),
    ]
    for tabela, coluna in fontes:
        for row in _safe_select_rows(tabela, coluna, 20000, order_by=None):
            placa = normalize_placa(row.get(coluna))
            if placa and placa not in vistos:
                vistos.add(placa)
                placas.append(placa)
                if len(placas) >= limite:
                    return placas
    return placas


def sync_historico_testes(limite: int = 500) -> int:  # type: ignore[override]
    """Consulta getHistoricoTestes e salva CodCheckList existentes.

    Não cria checklist. Apenas encontra histórico já existente por placa.
    """
    rotina = "getHistoricoTestes - descobrir CodCheckList existentes"
    try:
        placas = _placas_base_para_historico(limite)
        if not placas:
            raise RuntimeError("Nenhuma placa encontrada. Sincronize viagens Raster, SM abertas ou frota WSTT primeiro.")

        cod_filial_default = get_default_cod_filial(None)
        rows_hist: list[dict[str, Any]] = []
        rows_sol: list[dict[str, Any]] = []
        erros: list[str] = []

        for placa in placas:
            try:
                data = call_raster("getHistoricoTestes", {"Veiculo": placa})
                if not _ok(data):
                    erros.append(f"{placa}: CodErro={data.get('CodErro')} MsgErro={data.get('MsgErro')}")
                    continue

                testes = _list_from(data, "Testes", "Teste", "CheckLists", "CheckList")
                if not testes:
                    erros.append(f"{placa}: sem testes no histórico")
                    continue

                for t in testes:
                    cod = _codigo_checklist_from_teste(t)
                    codigo_hist = str(cod or _pick(t, "Codigo") or f"{placa}-{_pick(t, 'DataSol') or now_iso()}")
                    veic = normalize_placa(_pick(t, "Veiculo", "Placa", "PlacaVeiculo") or placa)
                    rows_hist.append({
                        "codigo": codigo_hist,
                        "veiculo": veic,
                        "carreta01": normalize_placa(_pick(t, "Carreta01", "Carreta1")),
                        "carreta02": normalize_placa(_pick(t, "Carreta02", "Carreta2")),
                        "carreta03": normalize_placa(_pick(t, "Carreta03", "Carreta3")),
                        "data_sol": _pick(t, "DataSol", "DataSolicitacao", "Data"),
                        "teste_temp": _pick(t, "TesteTemp"),
                        "tipo": _pick(t, "Tipo"),
                        "synced_at": now_iso(),
                    })
                    if cod:
                        rows_sol.append({
                            "chave": f"HIST-{cod}",
                            "cod_checklist": cod,
                            "veiculo": veic,
                            "cod_filial": cod_filial_default,
                            "tipo": _pick(t, "Tipo"),
                            "vinculo": "getHistoricoTestes",
                            "sensor_temperatura": _pick(t, "TesteTemp"),
                            "cod_erro": to_int(data.get("CodErro")),
                            "msg_erro": data.get("MsgErro"),
                            "raw": {"historico": t, "retorno": data},
                            "synced_at": now_iso(),
                        })
            except Exception as exc:
                erros.append(f"{placa}: {exc}")

        total_hist = upsert_rows("raster_checklist", rows_hist, "codigo")
        total_sol = upsert_rows("raster_checklist_solicitacoes", rows_sol, "chave")
        total = total_sol or total_hist
        msg = f"placas={len(placas)} historico={total_hist} codchecklist={total_sol}"
        if erros:
            msg += " | " + " | ".join(erros[:15])
        log_execucao(rotina, "sucesso" if total else "alerta", total, msg)
        return total
    except Exception as exc:
        log_execucao(rotina, "erro", 0, str(exc))
        raise


def _item_has_valid_dates(row: dict[str, Any]) -> bool:
    return bool(row.get("data_geracao") and row.get("data_expiracao"))


def sync_resultado_checklist(
    cod_checklist: Any = None,
    cod_filial: Any = None,
    cod_perfil_seguranca: Any = None,
    produtos: Any = None,
    veiculo: Any = None,
) -> int:  # type: ignore[override]
    """Consulta getGerarResultadoCheckList sem criar checklist.

    Retorna a quantidade de resultados VÁLIDOS, ou seja, com DataGeracao e
    DataExpiracao preenchidas. Mesmo respostas inválidas/erro são gravadas no raw
    para diagnóstico, mas não entram no contador de válidos.
    """
    rotina = "getGerarResultadoCheckList - somente consulta válida"
    try:
        itens: list[dict[str, Any]] = []
        if cod_checklist or normalize_placa(veiculo):
            itens.append({
                "cod_checklist": cod_checklist,
                "cod_filial": cod_filial,
                "cod_perfil_seguranca": cod_perfil_seguranca,
                "produtos": produtos,
                "veiculo": veiculo,
            })
        else:
            solicitacoes = _safe_select_rows(
                "raster_checklist_solicitacoes",
                "cod_checklist,veiculo,cod_filial",
                20000,
                order_by="synced_at",
            )
            itens = [
                {
                    "cod_checklist": x.get("cod_checklist"),
                    "veiculo": x.get("veiculo"),
                    "cod_filial": x.get("cod_filial") or cod_filial,
                    "cod_perfil_seguranca": cod_perfil_seguranca,
                    "produtos": produtos,
                }
                for x in solicitacoes
                if to_int(x.get("cod_checklist"))
            ]

            if not itens:
                # Tenta descobrir checklists existentes via histórico, sem criar nada.
                try:
                    sync_historico_testes(limite=500)
                    solicitacoes = _safe_select_rows(
                        "raster_checklist_solicitacoes",
                        "cod_checklist,veiculo,cod_filial",
                        20000,
                        order_by="synced_at",
                    )
                    itens = [
                        {
                            "cod_checklist": x.get("cod_checklist"),
                            "veiculo": x.get("veiculo"),
                            "cod_filial": x.get("cod_filial") or cod_filial,
                            "cod_perfil_seguranca": cod_perfil_seguranca,
                            "produtos": produtos,
                        }
                        for x in solicitacoes
                        if to_int(x.get("cod_checklist"))
                    ]
                except Exception as exc:
                    print("Aviso: não foi possível buscar histórico antes do resultado:", exc)

            if not itens:
                base = _safe_select_rows(
                    "raster_checklist_resultado",
                    "cod_checklist,veiculo,cod_filial,cod_perfil_seguranca,produtos",
                    20000,
                    order_by="synced_at",
                )
                itens = [x for x in base if to_int(x.get("cod_checklist"))]

            if not itens:
                raise RuntimeError(
                    "Nenhum CodCheckList existente encontrado. Como a criação está bloqueada, "
                    "rode primeiro getHistoricoTestes ou importe CodCheckList existentes."
                )

        rows: list[dict[str, Any]] = []
        erros: list[str] = []
        validos = 0

        for item in itens:
            payload = _normalizar_payload_resultado_checklist(
                cod_checklist=item.get("cod_checklist"),
                cod_filial=item.get("cod_filial") or cod_filial,
                cod_perfil_seguranca=item.get("cod_perfil_seguranca") or cod_perfil_seguranca,
                produtos=item.get("produtos") or produtos,
                veiculo=item.get("veiculo"),
            )
            ident = payload.get("CodCheckList") or payload.get("Veiculo") or item.get("veiculo") or "SEM_IDENTIFICADOR"

            if not payload.get("CodCheckList"):
                erros.append(f"{ident}: sem CodCheckList válido")
                continue
            if not payload.get("CodFilial"):
                erros.append(f"{ident}: sem CodFilial")
                continue
            if not payload.get("CodPerfilSeguranca"):
                erros.append(f"{ident}: sem CodPerfilSeguranca")
                continue
            if not payload.get("Produtos"):
                erros.append(f"{ident}: sem Produtos")
                continue

            try:
                data = call_raster("getGerarResultadoCheckList", payload)
                if not _ok(data):
                    erros.append(f"{ident}: CodErro={data.get('CodErro')} MsgErro={data.get('MsgErro')}")
                row = _row_resultado_checklist(data, payload, item.get("veiculo"))
                if _item_has_valid_dates(row):
                    validos += 1
                else:
                    status = row.get("status")
                    erros.append(f"{ident}: sem DataGeracao/DataExpiracao status={status}")
                rows.append(row)
            except Exception as exc:
                erros.append(f"{ident}: {exc}")
                rows.append(_row_resultado_checklist({
                    "CodErro": "EXCEPTION",
                    "MsgErro": str(exc),
                    "Metodo": "getGerarResultadoCheckList",
                }, payload, item.get("veiculo")))

        salvos = upsert_rows("raster_checklist_resultado", rows, "cod_resultado")
        status_log = "sucesso" if validos else ("alerta" if salvos else "erro")
        log_execucao(rotina, status_log, validos, f"validos={validos} salvos={salvos} consultados={len(rows)} | " + " | ".join(erros[:20]) if erros else f"validos={validos} salvos={salvos} consultados={len(rows)}")
        return validos
    except Exception as exc:
        log_execucao(rotina, "erro", 0, str(exc))
        raise


def sync_resultado_checklist_ate_finalizar(
    cod_filial: Any = None,
    cod_perfil_seguranca: Any = None,
    produtos: Any = None,
    tentativas: int = 4,
    intervalo_segundos: int = 30,
) -> dict[str, Any]:  # type: ignore[override]
    rotina = "Reconsulta resultado checklist até datas obrigatórias"
    resumo = {"tentativas": 0, "resultados_validos": 0, "status": {}}
    for tentativa in range(1, int(tentativas) + 1):
        qtd = sync_resultado_checklist(
            cod_filial=cod_filial,
            cod_perfil_seguranca=cod_perfil_seguranca,
            produtos=produtos,
        )
        status_count = _contar_status_checklist_resultado()
        resumo = {"tentativas": tentativa, "resultados_validos": qtd, "status": status_count}
        if qtd:
            log_execucao(rotina, "sucesso", qtd, str(resumo))
            return resumo
        if tentativa < int(tentativas):
            time.sleep(int(intervalo_segundos))
    log_execucao(rotina, "alerta", 0, str(resumo))
    return resumo


def sync_checklist_fluxo_automatico(
    limite: int = 500,
    tentativas_resultado: int = 4,
    intervalo_resultado_segundos: int = 30,
) -> dict[str, Any]:  # type: ignore[override]
    """Fluxo automático SEM criação de checklist.

    1) Atualiza getTabela de apoio.
    2) Consulta getHistoricoTestes para descobrir CodCheckList existentes.
    3) Consulta getGerarResultadoCheckList.
    4) Só conta como resultado válido se DataGeracao e DataExpiracao vierem preenchidas.
    """
    rotina = "Checklist automático somente consulta"
    resumo = {"tabelas": 0, "historico_codchecklist": 0, "resultados_validos": 0, "tentativas_resultado": 0, "status_resultado": {}}
    try:
        resumo["tabelas"] = sync_tabelas_checklist()
        resumo["historico_codchecklist"] = sync_historico_testes(limite=limite)
        reconsulta = sync_resultado_checklist_ate_finalizar(
            tentativas=tentativas_resultado,
            intervalo_segundos=intervalo_resultado_segundos,
        )
        resumo["resultados_validos"] = int(reconsulta.get("resultados_validos") or 0)
        resumo["tentativas_resultado"] = int(reconsulta.get("tentativas") or 0)
        resumo["status_resultado"] = reconsulta.get("status") or {}
        log_execucao(rotina, "sucesso" if resumo["resultados_validos"] else "alerta", int(resumo["resultados_validos"]), str(resumo) + " sem_criar_checklist=True")
        return resumo
    except Exception as exc:
        log_execucao(rotina, "erro", 0, str(exc))
        raise

# =====================================================================
# PATCH FINAL - 27/05/2026
# Consulta segura de checklist Raster SEM criar checklist.
# Regras:
# - Nunca chama setIncluirCheckList.
# - Usa getHistoricoTestes para descobrir CodCheckList já existente.
# - Usa getGerarResultadoCheckList para consultar resultado.
# - Envia Produtos porque a Raster em produção está exigindo.
# - Respeita intervalo mínimo entre chamadas para evitar CodErro 102.
# - HTTP 500 não trava o app: grava raw, pula e segue.
# - Resultado válido somente quando DataGeracao e DataExpiracao vierem preenchidas.
# =====================================================================

_LAST_RASTER_CHECKLIST_CALL_TS = 0.0


def _raster_timeout_seconds() -> int:
    return max(5, to_int(_env("RASTER_TIMEOUT_SECONDS", "20")) or 20)


def _raster_delay_checklist_seconds() -> int:
    # A Raster retornou CodErro 102: "CONSUMO INDEVIDO. 10 segundos".
    # Usamos 12 para ter margem.
    return max(12, to_int(_env("RASTER_DELAY_CHECKLIST_SECONDS", "12")) or 12)


def _max_checklists_por_rodada() -> int:
    return max(1, min(to_int(_env("RASTER_MAX_CHECKLIST_POR_RODADA", "1")) or 1, 20))


def _wait_rate_limit_checklist() -> None:
    global _LAST_RASTER_CHECKLIST_CALL_TS
    delay = _raster_delay_checklist_seconds()
    now = time.time()
    elapsed = now - _LAST_RASTER_CHECKLIST_CALL_TS
    if _LAST_RASTER_CHECKLIST_CALL_TS and elapsed < delay:
        time.sleep(delay - elapsed)
    _LAST_RASTER_CHECKLIST_CALL_TS = time.time()


# Sobrescreve o call_raster anterior para usar timeout por .env, URL correta do DataSnap
# e não cair no endpoint sem aspas que gera erro: updategetGerarResultadoCheckList method not found.
def _raster_url_variants(metodo: str) -> list[str]:
    """Monta URLs corretas para o DataSnap REST da Raster/Logae.

    O manual mostra os métodos no formato /"metodo". Em POST, quando usamos
    /metodo sem aspas, alguns servidores DataSnap tentam resolver como operação
    update + metodo e retornam:
      TWebService.updategetGerarResultadoCheckList method not found

    Por isso, por padrão, NÃO usamos mais a URL sem aspas. Ela só será usada se
    RASTER_ALLOW_UNQUOTED_URL="1" no .env.
    """
    base = _base_url()
    urls = [
        f"{base}/%22{metodo}%22",   # aspas codificadas, mais seguro no Windows/requests/proxy
        f'{base}/"{metodo}"',       # formato literal exibido no manual
    ]
    if _env("RASTER_ALLOW_UNQUOTED_URL", "0") == "1":
        urls.append(f"{base}/{metodo}")
    return urls


def call_raster(metodo: str, body: dict[str, Any] | None = None) -> dict[str, Any]:  # type: ignore[override]
    login, senha = _credentials()
    payload = {
        "Ambiente": _ambiente(),
        "Login": login,
        "Senha": senha,
        "TipoRetorno": _tipo_retorno(),
    }
    if body:
        payload.update(body)

    tentativas: list[dict[str, Any]] = []
    last_error: Exception | None = None

    for url in _raster_url_variants(metodo):
        try:
            response = requests.post(url, json=payload, timeout=_raster_timeout_seconds())
            body_preview: Any
            try:
                body_preview = response.json()
            except Exception:
                body_preview = response.text[:2000]

            tentativa = {
                "url": url,
                "status_code": response.status_code,
                "body": body_preview,
            }
            tentativas.append(tentativa)

            # Se o servidor retornou 500 de método inexistente por URL sem aspas,
            # registra e tenta a próxima variante. Não trava a tela.
            if response.status_code >= 500:
                continue

            response.raise_for_status()
            data = body_preview
            if isinstance(data, dict) and isinstance(data.get("result"), list) and data["result"]:
                item = data["result"][0]
                return item if isinstance(item, dict) else {"raw": item}
            if isinstance(data, dict):
                return data
            return {"raw": data}
        except Exception as exc:
            last_error = exc
            tentativas.append({"url": url, "exception": str(exc)})
            continue

    return {
        "Metodo": metodo,
        "CodErro": "HTTP_ERROR",
        "MsgErro": f"Erro ao chamar Raster {metodo}. Verifique as tentativas em raw/tentativas_http.",
        "Ambiente": _ambiente(),
        "payload_enviado": body or {},
        "tentativas_http": tentativas,
        "ultima_exception": str(last_error) if last_error else None,
        "msg_erro_normalizada": f"Erro ao chamar Raster {metodo}",
    }


def _produtos_do_perfil(cod_perfil: Any = None) -> list[dict[str, Any]]:
    perfil = get_default_cod_perfil(cod_perfil)
    valor = to_float(_env("RASTER_VALOR_PRODUTO", "1")) or 1.0
    if not perfil:
        return []
    linhas = _linhas_tabela("PERFIL_SEGURANCA")
    for row in linhas:
        if to_int(row.get("codigo")) != to_int(perfil):
            continue
        dados = row.get("dados") or {}
        if isinstance(dados, str):
            try:
                dados = json.loads(dados)
            except Exception:
                dados = {}
        produtos = dados.get("Produtos") if isinstance(dados, dict) else None
        if isinstance(produtos, list):
            saida = []
            for p in produtos:
                cod_prod = to_int(_pick(p, "CodProduto", "Codigo", "Código", "Cod")) if isinstance(p, dict) else None
                if cod_prod:
                    saida.append({"CodProduto": cod_prod, "Valor": valor})
            if saida:
                return saida
    return []


def get_default_produtos(produtos: Any = None) -> Any:  # type: ignore[override]
    """Produtos usados no getGerarResultadoCheckList.

    Prioridade:
    1) valor informado manualmente;
    2) RASTER_PRODUTOS no .env;
    3) produtos vinculados ao perfil de segurança escolhido;
    4) produto 2134, porque nos perfis Shopee enviados o produto vinculado é 2134.
    """
    parsed = _parse_produtos(produtos) or _parse_produtos(_env("RASTER_PRODUTOS", ""))
    if parsed:
        return parsed if isinstance(parsed, list) else [parsed]

    por_perfil = _produtos_do_perfil(_env("RASTER_COD_PERFIL_SEGURANCA", ""))
    if por_perfil:
        return por_perfil

    valor = to_float(_env("RASTER_VALOR_PRODUTO", "1")) or 1.0
    return [{"CodProduto": 2134, "Valor": valor}]


def _coletar_itens_checklist_existentes(
    cod_checklist: Any = None,
    cod_filial: Any = None,
    cod_perfil_seguranca: Any = None,
    produtos: Any = None,
    veiculo: Any = None,
    limite: int | None = None,
) -> list[dict[str, Any]]:
    limite_final = int(limite or _max_checklists_por_rodada())
    itens: list[dict[str, Any]] = []

    if cod_checklist:
        return [{
            "cod_checklist": cod_checklist,
            "cod_filial": cod_filial,
            "cod_perfil_seguranca": cod_perfil_seguranca,
            "produtos": produtos,
            "veiculo": veiculo,
        }]

    # 1) Primeiro usa checklists descobertos via getHistoricoTestes e salvos na tabela de solicitações.
    solicitacoes = _safe_select_rows(
        "raster_checklist_solicitacoes",
        "cod_checklist,veiculo,cod_filial",
        20000,
        order_by="synced_at",
    )

    # 2) Remove os que já estão válidos, para não consultar à toa.
    resultados = _safe_select_rows(
        "raster_checklist_resultado",
        "cod_checklist,data_geracao,data_expiracao,status,synced_at",
        20000,
        order_by="synced_at",
    )
    validos = {to_int(r.get("cod_checklist")) for r in resultados if to_int(r.get("cod_checklist")) and r.get("data_geracao") and r.get("data_expiracao")}

    vistos: set[int] = set()
    for x in solicitacoes:
        cod = to_int(x.get("cod_checklist"))
        if not cod or cod in vistos or cod in validos:
            continue
        vistos.add(cod)
        itens.append({
            "cod_checklist": cod,
            "veiculo": x.get("veiculo"),
            "cod_filial": x.get("cod_filial") or cod_filial,
            "cod_perfil_seguranca": cod_perfil_seguranca,
            "produtos": produtos,
        })
        if len(itens) >= limite_final:
            return itens

    # 3) Se não houver solicitações, usa a tabela resultado como fila, desde que tenha CodCheckList.
    base = _safe_select_rows(
        "raster_checklist_resultado",
        "cod_checklist,veiculo,cod_filial,cod_perfil_seguranca,produtos,data_geracao,data_expiracao",
        20000,
        order_by="synced_at",
    )
    for x in base:
        cod = to_int(x.get("cod_checklist"))
        if not cod or cod in vistos or cod in validos:
            continue
        vistos.add(cod)
        itens.append({
            "cod_checklist": cod,
            "veiculo": x.get("veiculo"),
            "cod_filial": x.get("cod_filial") or cod_filial,
            "cod_perfil_seguranca": x.get("cod_perfil_seguranca") or cod_perfil_seguranca,
            "produtos": x.get("produtos") or produtos,
        })
        if len(itens) >= limite_final:
            return itens

    return itens[:limite_final]


def sync_resultado_checklist(
    cod_checklist: Any = None,
    cod_filial: Any = None,
    cod_perfil_seguranca: Any = None,
    produtos: Any = None,
    veiculo: Any = None,
    limite: int | None = None,
) -> int:  # type: ignore[override]
    """Consulta getGerarResultadoCheckList SEM criar checklist.

    Retorna apenas a quantidade de resultados válidos, ou seja, com DataGeracao e
    DataExpiracao preenchidas. Erros HTTP 500, CodErro 102, CodErro 105 etc. são
    salvos no raw e não travam a aplicação.
    """
    rotina = "getGerarResultadoCheckList - somente consulta segura"
    try:
        # Garante apoio sem depender do usuário apertar getTabela manualmente.
        try:
            _ensure_tabela("PERFIL_SEGURANCA")
            _ensure_tabela("PRODUTOS")
            _ensure_tabela("FILIAIS")
        except Exception as exc:
            print("Aviso getTabela apoio:", exc)

        itens = _coletar_itens_checklist_existentes(
            cod_checklist=cod_checklist,
            cod_filial=cod_filial,
            cod_perfil_seguranca=cod_perfil_seguranca,
            produtos=produtos,
            veiculo=veiculo,
            limite=limite,
        )

        if not itens:
            raise RuntimeError(
                "Nenhum CodCheckList existente encontrado para consulta. "
                "O app não cria checklist. Rode getHistoricoTestes para descobrir checklists existentes ou importe CodCheckList."
            )

        rows: list[dict[str, Any]] = []
        erros: list[str] = []
        validos = 0

        for item in itens:
            payload = _normalizar_payload_resultado_checklist(
                cod_checklist=item.get("cod_checklist"),
                cod_filial=item.get("cod_filial") or cod_filial,
                cod_perfil_seguranca=item.get("cod_perfil_seguranca") or cod_perfil_seguranca,
                produtos=item.get("produtos") or produtos,
                veiculo=item.get("veiculo"),
            )
            ident = payload.get("CodCheckList") or item.get("veiculo") or "SEM_IDENTIFICADOR"

            if not payload.get("CodCheckList"):
                erros.append(f"{ident}: sem CodCheckList")
                continue
            if not payload.get("CodFilial"):
                erros.append(f"{ident}: sem CodFilial")
                continue
            if not payload.get("CodPerfilSeguranca"):
                erros.append(f"{ident}: sem CodPerfilSeguranca")
                continue
            if not payload.get("Produtos"):
                erros.append(f"{ident}: sem Produtos")
                continue

            # Rate limit obrigatório da Raster para evitar CodErro 102.
            _wait_rate_limit_checklist()
            data = call_raster("getGerarResultadoCheckList", payload)
            if not _ok(data):
                erros.append(f"{ident}: CodErro={data.get('CodErro')} MsgErro={data.get('MsgErro')}")

            row = _row_resultado_checklist(data, payload, item.get("veiculo"))
            if _item_has_valid_dates(row):
                validos += 1
            else:
                erros.append(f"{ident}: sem DataGeracao/DataExpiracao status={row.get('status')}")
            rows.append(row)

        salvos = upsert_rows("raster_checklist_resultado", rows, "cod_resultado") if rows else 0
        status_log = "sucesso" if validos else ("alerta" if salvos else "erro")
        detalhe = f"validos={validos} salvos={salvos} consultados={len(rows)} limite={len(itens)} delay={_raster_delay_checklist_seconds()}s | " + " | ".join(erros[:20])
        log_execucao(rotina, status_log, validos, detalhe[:3000])
        return validos
    except Exception as exc:
        log_execucao(rotina, "erro", 0, str(exc))
        raise


def sync_resultado_checklist_ate_finalizar(
    cod_filial: Any = None,
    cod_perfil_seguranca: Any = None,
    produtos: Any = None,
    tentativas: int = 1,
    intervalo_segundos: int = 12,
) -> dict[str, Any]:  # type: ignore[override]
    """Modo seguro: uma passada por execução, sem loop infinito."""
    qtd = sync_resultado_checklist(
        cod_filial=cod_filial,
        cod_perfil_seguranca=cod_perfil_seguranca,
        produtos=produtos,
        limite=_max_checklists_por_rodada(),
    )
    status_count = _contar_status_checklist_resultado()
    resumo = {"tentativas": 1, "resultados_validos": qtd, "status": status_count, "modo": "passada_unica_sem_loop"}
    log_execucao("Consulta resultado checklist passada única", "sucesso" if qtd else "alerta", qtd, str(resumo))
    return resumo


def sync_checklist_fluxo_automatico(
    limite: int = 100,
    tentativas_resultado: int = 1,
    intervalo_resultado_segundos: int = 12,
) -> dict[str, Any]:  # type: ignore[override]
    """Automático seguro, SEM criar checklist e SEM loop infinito.

    1) getTabela apoio;
    2) getHistoricoTestes para descobrir CodCheckList existentes;
    3) getGerarResultadoCheckList em lote pequeno, respeitando 12s entre chamadas.
    """
    rotina = "Checklist automático somente consulta seguro"
    resumo = {"tabelas": 0, "historico_codchecklist": 0, "resultados_validos": 0, "status_resultado": {}, "sem_criar_checklist": True}
    try:
        resumo["tabelas"] = sync_tabelas_checklist()
        resumo["historico_codchecklist"] = sync_historico_testes(limite=min(int(limite or 100), 100))
        resumo["resultados_validos"] = sync_resultado_checklist(limite=_max_checklists_por_rodada())
        resumo["status_resultado"] = _contar_status_checklist_resultado()
        log_execucao(rotina, "sucesso" if resumo["resultados_validos"] else "alerta", int(resumo["resultados_validos"]), str(resumo)[:3000])
        return resumo
    except Exception as exc:
        log_execucao(rotina, "erro", 0, str(exc))
        raise

# ============================================================
# OVERRIDE FINAL - CONSULTA CHECKLIST SEM CRIAR NADA
# ============================================================
# Objetivo:
# - Nunca chamar setIncluirCheckList.
# - Primeiro descobrir CodCheckList existente via getHistoricoTestes.
# - Depois consultar getGerarResultadoCheckList.
# - Não retornar mais "0 consulta" quando houve consulta mas não veio DataGeracao/DataExpiracao.
# - Separar contadores: encontrados, consultados, salvos, válidos.


def _safe_int_env(name: str, default: int) -> int:
    try:
        return int(float(_env(name, str(default))))
    except Exception:
        return default


def _consultar_historico_se_preciso(limite: int = 50) -> int:
    """Descobre CodCheckList existentes via getHistoricoTestes, sem criar checklist."""
    try:
        return int(sync_historico_testes(limite=limite) or 0)
    except Exception as exc:
        log_execucao("getHistoricoTestes automático", "alerta", 0, str(exc)[:3000])
        return 0


def _coletar_itens_checklist_existentes_v2(
    cod_checklist: Any = None,
    cod_filial: Any = None,
    cod_perfil_seguranca: Any = None,
    produtos: Any = None,
    veiculo: Any = None,
    limite: int | None = None,
    incluir_ja_validos: bool = False,
) -> list[dict[str, Any]]:
    limite_final = int(limite or _max_checklists_por_rodada() or 1)
    itens: list[dict[str, Any]] = []
    vistos: set[int] = set()

    if cod_checklist:
        return [{
            "cod_checklist": cod_checklist,
            "cod_filial": cod_filial,
            "cod_perfil_seguranca": cod_perfil_seguranca,
            "produtos": produtos,
            "veiculo": veiculo,
        }]

    resultados = _safe_select_rows(
        "raster_checklist_resultado",
        "cod_checklist,data_geracao,data_expiracao,status,synced_at",
        20000,
        order_by="synced_at",
    )
    validos = set()
    if not incluir_ja_validos:
        validos = {
            to_int(r.get("cod_checklist"))
            for r in resultados
            if to_int(r.get("cod_checklist")) and r.get("data_geracao") and r.get("data_expiracao")
        }

    # Prioridade 1: solicitações/históricos descobertos por getHistoricoTestes.
    solicitacoes = _safe_select_rows(
        "raster_checklist_solicitacoes",
        "cod_checklist,veiculo,cod_filial,synced_at",
        20000,
        order_by="synced_at",
    )
    for x in solicitacoes:
        cod = to_int(x.get("cod_checklist"))
        if not cod or cod in vistos or cod in validos:
            continue
        vistos.add(cod)
        itens.append({
            "cod_checklist": cod,
            "veiculo": x.get("veiculo"),
            "cod_filial": x.get("cod_filial") or cod_filial,
            "cod_perfil_seguranca": cod_perfil_seguranca,
            "produtos": produtos,
        })
        if len(itens) >= limite_final:
            return itens

    # Prioridade 2: tabela de resultado, caso já tenha CodCheckList salvo ali.
    base = _safe_select_rows(
        "raster_checklist_resultado",
        "cod_checklist,veiculo,cod_filial,cod_perfil_seguranca,produtos,data_geracao,data_expiracao,synced_at",
        20000,
        order_by="synced_at",
    )
    for x in base:
        cod = to_int(x.get("cod_checklist"))
        if not cod or cod in vistos or cod in validos:
            continue
        vistos.add(cod)
        itens.append({
            "cod_checklist": cod,
            "veiculo": x.get("veiculo"),
            "cod_filial": x.get("cod_filial") or cod_filial,
            "cod_perfil_seguranca": x.get("cod_perfil_seguranca") or cod_perfil_seguranca,
            "produtos": x.get("produtos") or produtos,
        })
        if len(itens) >= limite_final:
            return itens

    return itens[:limite_final]


def sync_resultado_checklist_detalhado(
    cod_checklist: Any = None,
    cod_filial: Any = None,
    cod_perfil_seguranca: Any = None,
    produtos: Any = None,
    veiculo: Any = None,
    limite: int | None = None,
    descobrir_historico: bool = True,
) -> dict[str, Any]:
    """Consulta checklist existente com diagnóstico completo.

    Retorna contadores separados para a tela não mostrar "0 consulta" quando
    houve consulta, mas a Raster não devolveu DataGeracao/DataExpiracao.
    """
    rotina = "getGerarResultadoCheckList - diagnóstico seguro"
    limite_final = int(limite or _max_checklists_por_rodada() or 1)
    resumo: dict[str, Any] = {
        "encontrados": 0,
        "historico_descoberto": 0,
        "consultados": 0,
        "salvos": 0,
        "validos": 0,
        "erros": [],
        "status": {},
        "sem_criar_checklist": True,
        "limite": limite_final,
    }

    try:
        # Apoio: não cria nada, só consulta tabelas de cadastro.
        for tabela in ("PERFIL_SEGURANCA", "PRODUTOS", "FILIAIS"):
            try:
                _ensure_tabela(tabela)
            except Exception as exc:
                resumo["erros"].append(f"getTabela {tabela}: {exc}")

        itens = _coletar_itens_checklist_existentes_v2(
            cod_checklist=cod_checklist,
            cod_filial=cod_filial,
            cod_perfil_seguranca=cod_perfil_seguranca,
            produtos=produtos,
            veiculo=veiculo,
            limite=limite_final,
        )

        if not itens and descobrir_historico:
            # Descobre históricos existentes por placa, SEM criar checklist.
            hist_limite = _safe_int_env("RASTER_LIMITE_HISTORICO_PLACAS", 20)
            resumo["historico_descoberto"] = _consultar_historico_se_preciso(hist_limite)
            itens = _coletar_itens_checklist_existentes_v2(
                cod_checklist=cod_checklist,
                cod_filial=cod_filial,
                cod_perfil_seguranca=cod_perfil_seguranca,
                produtos=produtos,
                veiculo=veiculo,
                limite=limite_final,
            )

        resumo["encontrados"] = len(itens)

        if not itens:
            msg = (
                "Nenhum CodCheckList existente encontrado. O app NÃO cria checklist. "
                "Sincronize placas/viagens/frota e rode getHistoricoTestes, ou informe um CodCheckList manual."
            )
            resumo["erros"].append(msg)
            log_execucao(rotina, "alerta", 0, str(resumo)[:3000])
            return resumo

        rows: list[dict[str, Any]] = []
        for item in itens:
            payload = _normalizar_payload_resultado_checklist(
                cod_checklist=item.get("cod_checklist"),
                cod_filial=item.get("cod_filial") or cod_filial,
                cod_perfil_seguranca=item.get("cod_perfil_seguranca") or cod_perfil_seguranca,
                produtos=item.get("produtos") or produtos,
                veiculo=item.get("veiculo") or veiculo,
            )
            ident = payload.get("CodCheckList") or payload.get("Veiculo") or item.get("veiculo") or "SEM_IDENTIFICADOR"

            faltas = [k for k in ("CodCheckList", "CodFilial", "CodPerfilSeguranca", "Produtos") if not payload.get(k)]
            if faltas:
                resumo["erros"].append(f"{ident}: faltando {', '.join(faltas)}")
                rows.append(_row_resultado_checklist({
                    "Metodo": "getGerarResultadoCheckList",
                    "CodErro": "VALIDACAO_LOCAL",
                    "MsgErro": f"Campos faltando: {', '.join(faltas)}",
                }, payload, item.get("veiculo")))
                continue

            _wait_rate_limit_checklist()
            data = call_raster("getGerarResultadoCheckList", payload)
            resumo["consultados"] += 1

            if not _ok(data):
                resumo["erros"].append(f"{ident}: CodErro={data.get('CodErro')} MsgErro={data.get('MsgErro')}")

            row = _row_resultado_checklist(data, payload, item.get("veiculo"))
            status = str(row.get("status") or "SEM_STATUS")
            resumo["status"][status] = int(resumo["status"].get(status, 0)) + 1

            if _item_has_valid_dates(row):
                resumo["validos"] += 1
            else:
                resumo["erros"].append(f"{ident}: consultado, porém sem DataGeracao/DataExpiracao. Status={status}")

            rows.append(row)

        if rows:
            resumo["salvos"] = upsert_rows("raster_checklist_resultado", rows, "cod_resultado")

        status_log = "sucesso" if resumo["validos"] else ("alerta" if resumo["consultados"] or resumo["salvos"] else "erro")
        log_execucao(rotina, status_log, int(resumo["validos"]), str(resumo)[:3000])
        return resumo
    except Exception as exc:
        resumo["erros"].append(str(exc))
        log_execucao(rotina, "erro", 0, str(resumo)[:3000])
        return resumo


def sync_resultado_checklist(
    cod_checklist: Any = None,
    cod_filial: Any = None,
    cod_perfil_seguranca: Any = None,
    produtos: Any = None,
    veiculo: Any = None,
    limite: int | None = None,
) -> int:  # type: ignore[override]
    """Compatibilidade: retorna válidos, mas grava diagnóstico completo no log/raw."""
    res = sync_resultado_checklist_detalhado(
        cod_checklist=cod_checklist,
        cod_filial=cod_filial,
        cod_perfil_seguranca=cod_perfil_seguranca,
        produtos=produtos,
        veiculo=veiculo,
        limite=limite,
    )
    return int(res.get("validos") or 0)


def sync_resultado_checklist_ate_finalizar(
    cod_filial: Any = None,
    cod_perfil_seguranca: Any = None,
    produtos: Any = None,
    tentativas: int = 1,
    intervalo_segundos: int = 12,
) -> dict[str, Any]:  # type: ignore[override]
    """Sem loop: uma passada com resumo completo."""
    return sync_resultado_checklist_detalhado(
        cod_filial=cod_filial,
        cod_perfil_seguranca=cod_perfil_seguranca,
        produtos=produtos,
        limite=_max_checklists_por_rodada(),
        descobrir_historico=True,
    )


def sync_checklist_fluxo_automatico(
    limite: int = 100,
    tentativas_resultado: int = 1,
    intervalo_resultado_segundos: int = 12,
) -> dict[str, Any]:  # type: ignore[override]
    """Fluxo automático somente consulta, sem criação de checklist."""
    rotina = "Checklist automático somente consulta diagnóstico"
    resumo: dict[str, Any] = {"tabelas": 0, "historico_codchecklist": 0, "resultado": {}, "sem_criar_checklist": True}
    try:
        resumo["tabelas"] = sync_tabelas_checklist()
        resumo["historico_codchecklist"] = sync_historico_testes(limite=min(int(limite or 100), _safe_int_env("RASTER_LIMITE_HISTORICO_PLACAS", 20)))
        resumo["resultado"] = sync_resultado_checklist_detalhado(limite=_max_checklists_por_rodada(), descobrir_historico=False)
        log_execucao(rotina, "sucesso" if (resumo["resultado"].get("validos") or 0) else "alerta", int(resumo["resultado"].get("validos") or 0), str(resumo)[:3000])
        return resumo
    except Exception as exc:
        resumo["erro"] = str(exc)
        log_execucao(rotina, "erro", 0, str(resumo)[:3000])
        return resumo
