import json
import os
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    import streamlit as st
except Exception:  # pragma: no cover
    st = None


def get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    if st is not None:
        try:
            if name in st.secrets:
                return str(st.secrets[name])
        except Exception:
            pass
    return os.getenv(name, default)


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except Exception:
        return default


def normalize_response(data: Any) -> Dict[str, Any]:
    """DataSnap costuma retornar {result:[{...}]}. Padroniza para um dict."""
    if isinstance(data, dict) and "result" in data:
        result = data.get("result")
        if isinstance(result, list) and result:
            if isinstance(result[0], dict):
                return result[0]
        return {"result": result}
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict):
        return data
    return {"raw": data}


class RasterClient:
    def __init__(self):
        self.base_url = (get_secret("RASTER_BASE_URL", "https://integra.logae.com.br/datasnap/rest/TWebService") or "").rstrip("/")
        self.login = get_secret("RASTER_LOGIN", "") or ""
        self.senha = get_secret("RASTER_SENHA", "") or ""
        self.ambiente = get_secret("RASTER_AMBIENTE", "Producao") or "Producao"
        self.tipo_retorno = get_secret("RASTER_TIPO_RETORNO", "JSON") or "JSON"
        self.timeout = as_int(get_secret("RASTER_TIMEOUT_SECONDS", "25"), 25)
        self.allow_unquoted = (get_secret("RASTER_ALLOW_UNQUOTED_URL", "1") or "1") == "1"

    def base_payload(self) -> Dict[str, Any]:
        return {
            "Ambiente": self.ambiente,
            "Login": self.login,
            "Senha": self.senha,
            "TipoRetorno": self.tipo_retorno,
        }

    def method_urls(self, method: str) -> List[str]:
        # Manual DataSnap mostra /"metodo"/. Algumas instalações aceitam sem aspas.
        urls = [f'{self.base_url}/%22{method}%22/']
        if self.allow_unquoted:
            urls.append(f"{self.base_url}/{method}")
            urls.append(f"{self.base_url}/{method}/")
        return urls

    def post(self, method: str, payload_extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = self.base_payload()
        if payload_extra:
            payload.update({k: v for k, v in payload_extra.items() if v not in (None, "")})
        attempts = []
        last_error = None
        for url in self.method_urls(method):
            try:
                r = requests.post(url, json=payload, timeout=self.timeout)
                body_text = r.text[:5000]
                attempts.append({"url": url, "status": r.status_code, "body": body_text, "payload": payload})
                r.raise_for_status()
                try:
                    data = r.json()
                except Exception:
                    data = {"raw_text": body_text}
                normalized = normalize_response(data)
                normalized["_payload_enviado"] = payload
                normalized["_tentativas_http"] = attempts
                return normalized
            except Exception as exc:
                last_error = exc
                continue
        return {
            "CodErro": "HTTP_ERROR",
            "MsgErro": f"Erro ao chamar Raster {method}: {last_error}",
            "Metodo": method,
            "_payload_enviado": payload,
            "_tentativas_http": attempts,
        }


def previous_month_start(today: Optional[date] = None) -> date:
    today = today or date.today()
    first_this = today.replace(day=1)
    last_prev = first_this - timedelta(days=1)
    return last_prev.replace(day=1)


def today_iso() -> str:
    return date.today().isoformat()


def period_previous_current_month() -> Tuple[str, str]:
    return previous_month_start().isoformat(), today_iso()


GET_TABELA_NOMES = [
    "ERROS_WEBSERVICE", "TIPOS_VEICULO", "TIPOS_CARRETA", "MARCAS_VEICULO", "MARCAS_CARRETA",
    "TECNOLOGIAS", "MODELOS_TECNOLOGIA", "DISPOSITIVOS_VEICULO", "DISPOSITIVOS_CARRETAS", "CORES",
    "PROFISSOES", "FAIXAS_TEMPERATURA", "FILIAIS", "PERFIL_SEGURANCA", "PRODUTOS", "MODELOS_PRESM",
    "MOTIVOS_PARADA", "CIDADES", "SUBTIPOS_VEICULO", "SUB_TIPOS_CARRETA", "TIPOS_EIXOS",
    "TIPOS_EIXOS_VEICULOS", "EQUIPAMENTOS_FRIGORIFICO", "ESTADO_CIVIL", "ESCOLARIDADE", "TIPOS_CARGA",
    "INFORMACOES_ADICIONAIS_PRE_SM", "CARACTERISTICA_CARROCERIA", "STATUS_CARGA_VIAGEM",
]

# Métodos somente consulta/get. NÃO inclui set* para evitar criação/alteração na Raster.
METHOD_REGISTRY: Dict[str, Dict[str, Any]] = {
    "getPosicoes": {"grupo": "Posições", "auto_payload": {"TipoConsulta": "Ultimas", "CodUltPosicao": 0}},
    "getPosicoesCliente": {"grupo": "Posições", "campos": ["CNPJ"]},
    "getMensagens": {"grupo": "Posições", "auto_payload": {"TipoConsulta": "Primeiras", "CodUltMensagem": 0}},

    "getTabela": {"grupo": "Cadastros", "campos": ["NomeTabela"]},
    "getCidades": {"grupo": "Cadastros", "campos": ["Nome", "UF", "CodIBGE"]},
    "getProprietario": {"grupo": "Cadastros", "campos": ["CNPJCPF"]},
    "getCliente": {"grupo": "Cadastros", "campos": ["CNPJCPF"]},
    "getVeiculo": {"grupo": "Cadastros", "campos": ["Placa"]},
    "getCarreta": {"grupo": "Cadastros", "campos": ["Placa"]},
    "getMotorista": {"grupo": "Cadastros", "campos": ["CPF"]},
    "getCadLocalizadores": {"grupo": "Cadastros", "auto_payload": {}},

    "getRotas": {"grupo": "Rotas", "campos": ["CodRota", "CidadeOrigem", "CidadeDestino"]},
    "GetRotograma": {"grupo": "Rotas", "campos": ["CodRota"]},
    "getRotograma": {"grupo": "Rotas", "campos": ["CodRota"]},

    "getPreSM": {"grupo": "Viagens", "campos": ["CodPreSolicitacao"]},
    "getStatusViagem": {"grupo": "Viagens", "campos": ["Documentos", "CodSolicitacao", "CodPreSolicitacao", "Placa"]},
    "getConsultaPreSMAberta": {"grupo": "Viagens", "auto_payload": {}},
    "getStatusPreSM": {"grupo": "Viagens", "campos": ["CodPreSolicitacao", "Placa"]},
    "getStatusColetas": {"grupo": "Viagens", "campos": ["CodPreSolicitacao", "CodSolicitacao", "Placa"]},
    "getEventoFimViagem": {"grupo": "Viagens", "campos": ["CodPreSolicitacao", "CodSolicitacao", "DataInicial", "DataFinal", "StatusViagem", "CNPJRemDest", "Placa"]},
    "getImpressaoSM": {"grupo": "Viagens", "campos": ["CodSolicitacao"]},
    "getModelosPreSM": {"grupo": "Viagens de Modelo", "auto_payload": {}},

    "getResultadoPesquisaConsulta": {"grupo": "Pesquisa", "campos": ["CodPesquisa"]},
    "getResultadoPesquisaConsultaConjunto": {"grupo": "Pesquisa", "campos": ["CodPesquisa"]},
    "getDocumentoPesquisaConsulta": {"grupo": "Pesquisa", "campos": ["CodPesquisa"]},

    "getHistoricoTestes": {"grupo": "CheckList", "campos": ["Veiculo"]},
    "getGerarResultadoCheckList": {"grupo": "CheckList", "campos": ["CodCheckList", "Veiculo", "CodFilial", "CodPerfilSeguranca", "Produtos"]},

    "getOcorrenciasLogisticas": {"grupo": "Logístico", "campos": ["CodSolicitacao", "CodPreSolicitacao", "DataInicial", "DataFinal"]},
    "getProgramacaoCargas": {"grupo": "Logístico", "campos": ["CodProgramacao", "IdentificadorExterno"]},
    "getListaProgramacaoCargas": {"grupo": "Logístico", "campos": ["DataInicial", "DataFinal", "Status"]},
    "getKMRodado": {"grupo": "Logístico", "campos": ["DataInicial", "DataFinal", "Placa"]},
}


def find_lists(obj: Any, path: str = "") -> List[Tuple[str, List[Any]]]:
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{path}.{k}" if path else k
            if isinstance(v, list):
                out.append((new_path, v))
            out.extend(find_lists(v, new_path))
    elif isinstance(obj, list):
        out.append((path or "lista", obj))
        for i, v in enumerate(obj[:5]):
            out.extend(find_lists(v, f"{path}[{i}]"))
    return out


def flatten_record(record: Dict[str, Any]) -> Dict[str, Any]:
    flat = {}
    for k, v in record.items():
        if k.startswith("_"):
            continue
        if isinstance(v, (dict, list)):
            flat[k] = json.dumps(v, ensure_ascii=False)
        else:
            flat[k] = v
    return flat


def records_from_response(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    lists = find_lists(data)
    best: List[Any] = []
    for _, lst in lists:
        if len(lst) > len(best) and all(isinstance(x, dict) for x in lst[: min(len(lst), 5)]):
            best = lst
    if best:
        return [flatten_record(x) if isinstance(x, dict) else {"valor": x} for x in best]
    return [flatten_record(data)]


def extract_documents(data: Any) -> List[Dict[str, Any]]:
    docs = []
    def walk(obj: Any):
        if isinstance(obj, dict):
            tipo = obj.get("Tipo") or obj.get("tipo") or obj.get("TipoDocumento") or obj.get("tipo_documento")
            numero = obj.get("Numero") or obj.get("numero") or obj.get("NumeroDocumento") or obj.get("numero_documento")
            if tipo and numero:
                docs.append({"Tipo": str(tipo).upper().strip(), "Numero": str(numero).strip()})
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    walk(data)
    # remove duplicados
    seen = set()
    unique = []
    for d in docs:
        key = (d["Tipo"], d["Numero"])
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique


def extract_values(data: Any, keys: List[str]) -> List[Any]:
    values = []
    wanted = {k.lower() for k in keys}
    def walk(obj: Any):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k.lower() in wanted and v not in (None, ""):
                    values.append(v)
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    walk(data)
    unique = []
    seen = set()
    for v in values:
        sv = str(v)
        if sv not in seen:
            seen.add(sv)
            unique.append(v)
    return unique


def make_download_json(results: Dict[str, Any]) -> str:
    return json.dumps(results, ensure_ascii=False, indent=2, default=str)
