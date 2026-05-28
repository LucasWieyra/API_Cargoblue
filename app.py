import os
import json
import time
from datetime import date, timedelta, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
import streamlit as st
from dateutil import parser


def cfg(name: str, default: str = "") -> str:
    try:
        if name in st.secrets:
            return str(st.secrets[name]).strip().strip('"')
    except Exception:
        pass
    return str(os.getenv(name, default) or default).strip().strip('"')


def base_payload() -> Dict[str, Any]:
    login = cfg("RASTER_LOGIN")
    senha = cfg("RASTER_SENHA")
    if not login or not senha:
        raise RuntimeError("Configure RASTER_LOGIN e RASTER_SENHA nos Secrets do Streamlit.")
    return {
        "Ambiente": cfg("RASTER_AMBIENTE", "Producao") or "Producao",
        "Login": login,
        "Senha": senha,
        "TipoRetorno": cfg("RASTER_TIPO_RETORNO", "JSON") or "JSON",
    }


def base_url() -> str:
    return cfg("RASTER_BASE_URL", "https://integra.logae.com.br/datasnap/rest/TWebService").rstrip("/")


def parse_date(value: Any) -> Optional[str]:
    if value in (None, "", "null", "None"):
        return None
    try:
        return parser.parse(str(value)).isoformat()
    except Exception:
        return str(value)


def to_int(value: Any) -> Optional[int]:
    if value in (None, "", "null", "None"):
        return None
    try:
        return int(float(str(value).replace(",", ".")))
    except Exception:
        return None


def pick(data: Dict[str, Any], *names: str) -> Any:
    if not isinstance(data, dict):
        return None
    lower = {str(k).lower(): v for k, v in data.items()}
    for name in names:
        if name in data:
            return data[name]
        val = lower.get(name.lower())
        if val is not None:
            return val
    return None


def call_raster(method: str, body: Optional[Dict[str, Any]] = None, timeout: Optional[int] = None) -> Dict[str, Any]:
    payload = base_payload()
    if body:
        payload.update({k: v for k, v in body.items() if v not in (None, "", [], {})})

    timeout = timeout or int(cfg("RASTER_TIMEOUT_SECONDS", "25") or 25)
    urls = [f'{base_url()}/"{method}"', f"{base_url()}/{method}"]
    errors: List[Dict[str, Any]] = []

    for url in urls:
        try:
            r = requests.post(url, json=payload, timeout=timeout)
            body_text = r.text[:2000]
            if r.status_code >= 400:
                errors.append({"url": url, "status": r.status_code, "body": body_text})
                continue
            data = r.json()
            if isinstance(data, dict) and isinstance(data.get("result"), list) and data["result"]:
                result = data["result"][0]
                if isinstance(result, dict):
                    result["_payload_enviado"] = payload
                    result["_url_usada"] = url
                    return result
                return {"retorno": result, "_payload_enviado": payload, "_url_usada": url}
            if isinstance(data, dict):
                data["_payload_enviado"] = payload
                data["_url_usada"] = url
                return data
            return {"retorno": data, "_payload_enviado": payload, "_url_usada": url}
        except Exception as exc:
            errors.append({"url": url, "erro": str(exc)})

    return {
        "CodErro": "HTTP_ERROR",
        "MsgErro": f"Erro ao chamar Raster {method}",
        "tentativas_http": errors,
        "_payload_enviado": payload,
    }


def ok(data: Dict[str, Any]) -> bool:
    code = str(data.get("CodErro", "0")).strip()
    return code in ("0", "", "None", "none")


def previous_and_current_month() -> Tuple[str, str]:
    today = date.today()
    first_current = today.replace(day=1)
    last_prev = first_current - timedelta(days=1)
    first_prev = last_prev.replace(day=1)
    return first_prev.isoformat(), today.isoformat()


def find_list(data: Dict[str, Any], preferred: Tuple[str, ...]) -> List[Dict[str, Any]]:
    for key in preferred:
        v = data.get(key)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
        if isinstance(v, dict):
            for sub in v.values():
                if isinstance(sub, list):
                    return [x for x in sub if isinstance(x, dict)]
    for v in data.values():
        if isinstance(v, list) and (not v or isinstance(v[0], dict)):
            return [x for x in v if isinstance(x, dict)]
    return []


def normalize_doc_type(t: Any) -> Optional[str]:
    if t in (None, ""):
        return None
    txt = str(t).upper().strip().replace(" ", "")
    aliases = {
        "CT-E": "CTE",
        "CTE": "CTE",
        "CARGA": "CARGA",
        "LOADNUMBER": "CARGA",
        "LOAD_NUMBER": "CARGA",
        "SHIPMENT": "SHIPMENT",
    }
    return aliases.get(txt, txt)


def extract_documents(obj: Any) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []

    def add(doc: Any, origem: str = ""):
        if not isinstance(doc, dict):
            return
        tipo = normalize_doc_type(pick(doc, "Tipo", "tipo", "TipoDocumento", "TipoDoc"))
        numero = pick(doc, "Numero", "Número", "numero", "NumDocumento", "Documento", "documento", "Chave")
        if numero in (None, ""):
            return
        docs.append({
            "tipo_documento": tipo,
            "numero_documento": str(numero).strip(),
            "valor_documento": pick(doc, "Valor", "valor"),
            "peso": pick(doc, "Peso", "peso"),
            "origem_documento": origem or None,
            "raw_documento": doc,
        })

    def walk(x: Any, origem: str = ""):
        if isinstance(x, dict):
            if any(k in x for k in ("Tipo", "tipo", "TipoDocumento", "TipoDoc")) and any(k in x for k in ("Numero", "Número", "numero", "Documento", "documento", "Chave")):
                add(x, origem or "Documento")
            for key, val in x.items():
                if key.lower() in ("raw", "payload", "tentativas_http"):
                    continue
                if isinstance(val, list):
                    if key.lower() in ("documentos", "documento", "docs", "cargas", "carga", "ctes", "cte", "conhecimentos", "notas"):
                        for item in val:
                            add(item, key)
                    for item in val:
                        walk(item, key)
                elif isinstance(val, dict):
                    if key.lower() in ("documentos", "documento", "carga", "cte", "conhecimento"):
                        add(val, key)
                    walk(val, key)
        elif isinstance(x, list):
            for item in x:
                walk(item, origem)

    walk(obj)

    seen = set()
    unique = []
    for d in docs:
        key = (d.get("tipo_documento"), d.get("numero_documento"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(d)
    return unique


def preferred_docs(docs: List[Dict[str, Any]], only_operational: bool = True) -> List[Dict[str, Any]]:
    allowed = {"CARGA", "CTE"} if only_operational else {"CARGA", "CTE", "SHIPMENT", "OUTROS"}
    filtered = [d for d in docs if d.get("tipo_documento") in allowed]
    priority = {"CARGA": 1, "CTE": 2, "SHIPMENT": 3, "OUTROS": 4}
    return sorted(filtered, key=lambda d: (priority.get(d.get("tipo_documento"), 9), str(d.get("numero_documento"))))


def get_evento_fim_viagem(data_inicial: Optional[str] = None, data_final: Optional[str] = None, status: str = "T") -> Dict[str, Any]:
    if not data_inicial or not data_final:
        data_inicial, data_final = previous_and_current_month()
    return call_raster("getEventoFimViagem", {
        "DataInicial": data_inicial,
        "DataFinal": data_final,
        "StatusViagem": status or "T",
    })


def rows_sm_documentos(data: Dict[str, Any], only_operational: bool = True) -> List[Dict[str, Any]]:
    viagens = find_list(data, ("Viagens", "Viagem", "Dados"))
    rows: List[Dict[str, Any]] = []
    for viagem in viagens:
        docs = preferred_docs(extract_documents(viagem), only_operational=only_operational)
        for doc in docs:
            rows.append({
                "sm": pick(viagem, "CodSolicitacao", "cod_solicitacao"),
                "cod_pre_solicitacao": pick(viagem, "CodPreSolicitacao", "cod_pre_solicitacao"),
                "tipo_documento": doc.get("tipo_documento"),
                "numero_documento": doc.get("numero_documento"),
                "documento_prioridade": 1 if doc.get("tipo_documento") == "CARGA" else 2,
                "placa_veiculo_api": pick(viagem, "PlacaVeiculo", "Placa", "placa"),
                "status_viagem": pick(viagem, "StatusViagem"),
                "status_checklist_viagem": pick(viagem, "StatusChecklist"),
                "data_prev_inicio": parse_date(pick(viagem, "DataHoraPrevIni", "DataPrevInicio")),
                "data_prev_fim": parse_date(pick(viagem, "DataHoraPrevFim", "DataPrevFim")),
                "data_real_inicio": parse_date(pick(viagem, "DataHoraRealIni", "DataRealInicio")),
                "data_real_fim": parse_date(pick(viagem, "DataHoraRealFim", "DataRealFim")),
                "origem": "getEventoFimViagem",
            })
    return rows


def get_status_viagem_by_document(tipo: str, numero: str) -> Dict[str, Any]:
    return call_raster("getStatusViagem", {"Documentos": [{"Tipo": tipo, "Numero": numero}]})


def rows_status_by_documents(sm_doc_rows: List[Dict[str, Any]], limit: int = 25) -> List[Dict[str, Any]]:
    rows = []
    seen = set()
    delay = float(cfg("RASTER_DELAY_STATUS_VIAGEM_SECONDS", "1") or 1)
    for r in sm_doc_rows[:limit]:
        tipo = r.get("tipo_documento")
        numero = r.get("numero_documento")
        if not tipo or not numero:
            continue
        key = (tipo, numero)
        if key in seen:
            continue
        seen.add(key)
        data = get_status_viagem_by_document(tipo, numero)
        status_rows = find_list(data, ("Viagens", "Viagem", "StatusViagem", "Dados")) or ([data] if isinstance(data, dict) else [])
        for item in status_rows:
            rows.append({
                "tipo_documento": tipo,
                "numero_documento": numero,
                "sm": pick(item, "CodSolicitacao", "cod_solicitacao") or r.get("sm"),
                "cod_pre_solicitacao": pick(item, "CodPreSolicitacao", "cod_pre_solicitacao") or r.get("cod_pre_solicitacao"),
                "placa_veiculo_api": pick(item, "PlacaVeiculo", "Placa", "placa") or r.get("placa_veiculo_api"),
                "status_viagem": pick(item, "StatusViagem") or r.get("status_viagem"),
                "status_checklist_viagem": pick(item, "StatusChecklist") or r.get("status_checklist_viagem"),
                "cod_erro": data.get("CodErro"),
                "msg_erro": data.get("MsgErro"),
                "origem": "getStatusViagem(Documentos)",
            })
        if delay:
            time.sleep(delay)
    return rows


def get_historico_testes(veiculo: str) -> Dict[str, Any]:
    return call_raster("getHistoricoTestes", {"Veiculo": veiculo})


def get_resultado_checklist(cod_checklist: Optional[int] = None, veiculo: Optional[str] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "CodFilial": to_int(cfg("RASTER_COD_FILIAL", "6278")),
        "CodPerfilSeguranca": to_int(cfg("RASTER_COD_PERFIL_SEGURANCA", "14341")),
    }
    produtos = cfg("RASTER_PRODUTOS", '[{"CodProduto":2134,"Valor":1}]')
    try:
        body["Produtos"] = json.loads(produtos)
    except Exception:
        body["Produtos"] = [{"CodProduto": 2134, "Valor": 1}]
    if cod_checklist:
        body["CodCheckList"] = cod_checklist
    elif veiculo:
        body["Veiculo"] = veiculo
    else:
        raise RuntimeError("Informe CodCheckList ou Veiculo para consultar resultado de checklist.")
    return call_raster("getGerarResultadoCheckList", body)


def checklist_rows_by_documents(status_rows: List[Dict[str, Any]], limit_docs: int = 10, limit_checklists_per_doc: int = 3) -> List[Dict[str, Any]]:
    """Busca checklist via API partindo do documento.

    Observação: a Raster não possui método de checklist por CARGA/CTE. Por isso o fluxo é:
    CARGA/CTE -> getStatusViagem(Documentos) -> viagem/veículo -> getHistoricoTestes/getGerarResultadoCheckList.
    A saída fica vinculada ao documento e à SM, não a uma tabela do Supabase.
    """
    rows: List[Dict[str, Any]] = []
    seen_docs = set()
    delay = float(cfg("RASTER_DELAY_CHECKLIST_SECONDS", "12") or 12)

    for s in status_rows:
        doc_key = (s.get("tipo_documento"), s.get("numero_documento"))
        if doc_key in seen_docs:
            continue
        seen_docs.add(doc_key)
        if len(seen_docs) > limit_docs:
            break

        veiculo = s.get("placa_veiculo_api")
        if not veiculo:
            rows.append({**s, "cod_checklist": None, "status_checklist": None, "observacao": "API não retornou veículo para consultar histórico de checklist"})
            continue

        hist = get_historico_testes(str(veiculo).replace("-", ""))
        testes = find_list(hist, ("Testes", "Historico", "HistoricoTestes", "CheckLists", "CheckList", "Dados"))
        if not testes and ok(hist):
            testes = [hist]
        count = 0
        for teste in testes:
            cod = to_int(pick(teste, "CodCheckList", "CodChecklist", "cod_checklist", "Codigo", "Cod"))
            if not cod:
                continue
            result = get_resultado_checklist(cod_checklist=cod)
            rec = result
            status = pick(rec, "Status", "status")
            resultado = pick(rec, "Resultado", "resultado")
            rows.append({
                "sm": s.get("sm"),
                "cod_pre_solicitacao": s.get("cod_pre_solicitacao"),
                "tipo_documento": s.get("tipo_documento"),
                "numero_documento": s.get("numero_documento"),
                "placa_veiculo_api": veiculo,
                "cod_checklist": cod,
                "status_checklist": status,
                "resultado": resultado,
                "apto": True if str(resultado).upper() in ("A", "APTO", "APROVADO") else False if str(resultado).upper() in ("R", "REPROVADO") else None,
                "data_geracao": parse_date(pick(rec, "DataGeracao", "data_geracao")),
                "data_expiracao": parse_date(pick(rec, "DataExpiracao", "data_expiracao")),
                "url_documento": pick(rec, "UrlDocumento", "URLDocumento", "url_documento"),
                "cod_erro": result.get("CodErro"),
                "msg_erro": result.get("MsgErro"),
                "origem": "Documento -> getStatusViagem -> getHistoricoTestes -> getGerarResultadoCheckList",
            })
            count += 1
            if delay:
                time.sleep(delay)
            if count >= limit_checklists_per_doc:
                break
        if count == 0:
            rows.append({**s, "cod_checklist": None, "status_checklist": None, "observacao": "Nenhum CodCheckList encontrado no histórico retornado pela API"})
    return rows
