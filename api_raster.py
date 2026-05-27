import hashlib
import html
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import requests
import xmltodict
from dateutil import parser as dt_parser
from dotenv import load_dotenv

from supabase_db import insert_rows, select_rows, upsert_rows

load_dotenv()

WSTT_NS = "http://microsoft.com/webservices/"
RATE_LIMIT_SECONDS = 1.2
_LAST_CALL = 0.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or default).strip().strip('"')


def _wstt_url() -> str:
    return _env("WSTT_URL", "https://wstt.omnilink.com.br/iasws/iasws.asmx")


def _credentials() -> tuple[str, str]:
    usuario = _env("WSTT_USUARIO")
    senha = _env("WSTT_SENHA")
    if not usuario or not senha:
        raise RuntimeError("Configure WSTT_USUARIO e WSTT_SENHA no arquivo .env")
    senha_md5 = hashlib.md5(senha.encode("utf-8")).hexdigest()
    return usuario, senha_md5


def _auth_xml(usuario: str, senha_md5: str) -> str:
    return f"<Usuario>{usuario}</Usuario><Senha>{senha_md5}</Senha>"


def _rate_limited() -> None:
    global _LAST_CALL
    wait = RATE_LIMIT_SECONDS - (time.time() - _LAST_CALL)
    if wait > 0:
        time.sleep(wait)
    _LAST_CALL = time.time()


def fmt_br(dt: datetime) -> str:
    return dt.strftime("%d/%m/%Y %H:%M:%S")


def fmt_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_date_input(value: date | datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return datetime.fromisoformat(str(value)[:10])




def normalize_timestamp(value: Any) -> str | None:
    """Normaliza datas da Omnilink para formato aceito pelo PostgreSQL/Supabase.

    A Omnilink às vezes retorna milissegundos com dois-pontos, exemplo:
    2026-05-25 00:59:47:161. O PostgreSQL espera 2026-05-25 00:59:47.161.
    """
    if value in (None, "", "None", "null", "NULL"):
        return None

    text = str(value).strip()
    if not text:
        return None

    # Corrige yyyy-mm-dd hh:mm:ss:SSS para yyyy-mm-dd hh:mm:ss.SSS
    text = re.sub(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}):(\d{1,6})$", r"\1.\2", text)

    # Corrige quando vem com T e milissegundo com dois-pontos
    text = re.sub(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}):(\d{1,6})([-+]\d{2}:?\d{2})?$", r"\1.\2\3", text)

    try:
        return dt_parser.parse(text, dayfirst=False).isoformat(sep=" ")
    except Exception:
        try:
            return datetime.fromisoformat(text).isoformat(sep=" ")
        except Exception:
            return text


def hourly_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    now = datetime.now()
    if end > now:
        end = now
    cur = start.replace(minute=0, second=0, microsecond=0)
    windows: list[tuple[datetime, datetime]] = []
    while cur < end:
        nxt = cur + timedelta(hours=1)
        fim = min(nxt - timedelta(seconds=1), end)
        windows.append((cur, fim))
        cur = nxt
    return windows


def soap_call(action: str, body_inner: str, timeout: int = 120) -> str:
    _rate_limited()
    usuario, senha_md5 = _credentials()
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:tns="{WSTT_NS}">'
        '<soap:Header><tns:Auth>'
        f'<tns:Usuario>{usuario}</tns:Usuario><tns:Senha>{senha_md5}</tns:Senha>'
        '</tns:Auth></soap:Header>'
        f'<soap:Body><tns:{action}>{body_inner}</tns:{action}></soap:Body>'
        '</soap:Envelope>'
    )
    response = requests.post(
        _wstt_url(),
        data=envelope.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"{WSTT_NS}{action}"'},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.text


def has_soap_fault(soap_response: str) -> str | None:
    if "Fault" not in soap_response:
        return None
    match = re.search(r"<faultstring[^>]*>([\s\S]*?)</faultstring>", soap_response)
    return match.group(1).strip() if match else "SOAP Fault desconhecido"


def extract_return_xml(soap_response: str) -> str | None:
    match = re.search(r"<return[^>]*>([\s\S]*?)</return>", soap_response)
    if not match:
        return None
    raw = match.group(1).strip()
    if not raw:
        return None
    return html.unescape(raw)


def parse_inner_xml(xml_text: str) -> dict[str, Any]:
    try:
        parsed = xmltodict.parse(xml_text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def find_all(obj: Any, tag: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if isinstance(obj, list):
        for item in obj:
            result.extend(find_all(item, tag))
        return result
    if not isinstance(obj, dict):
        return result
    for key, value in obj.items():
        clean_key = key.split(":")[-1]
        if clean_key == tag:
            if isinstance(value, list):
                result.extend([x for x in value if isinstance(x, dict)])
            elif isinstance(value, dict):
                result.append(value)
        else:
            result.extend(find_all(value, tag))
    return result


def pick(d: dict[str, Any], *keys: str) -> str:
    variants = list(keys)
    variants += [k[:1].lower() + k[1:] for k in keys if k]
    variants += [k.upper() for k in keys]
    variants += [k.lower() for k in keys]
    for key in variants:
        if key in d and d[key] not in (None, ""):
            return str(d[key]).strip()
    return ""


def to_num(value: Any) -> float | None:
    if value in (None, "", "None", "null"):
        return None
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return None


def to_int(value: Any) -> int | None:
    num = to_num(value)
    return int(num) if num is not None else None


def log_execucao(rotina: str, status: str, qtd: int = 0, erro: str | None = None) -> None:
    try:
        insert_rows("integracao_execucoes", [{
            "origem": "Omnilink/WSTT",
            "rotina": rotina,
            "status": status,
            "qtd_registros": qtd,
            "erro": erro[:3000] if erro else None,
            "executado_em": now_iso(),
        }])
    except Exception as exc:
        print("Erro ao gravar log WSTT:", exc)


def listar_veiculos() -> list[dict[str, Any]]:
    usuario, senha_md5 = _credentials()
    raw = soap_call("ListarVeiculoTodos", _auth_xml(usuario, senha_md5), timeout=120)
    fault = has_soap_fault(raw)
    if fault:
        raise RuntimeError(f"WSTT ListarVeiculoTodos: {fault}")
    inner = extract_return_xml(raw)
    if not inner:
        return []
    parsed = parse_inner_xml(inner)
    items = find_all(parsed, "Veiculo")
    seen: dict[str, dict[str, Any]] = {}
    for item in items:
        placa = pick(item, "Placa", "PLACA").upper().replace("-", "").replace(" ", "")
        if placa:
            seen[placa] = {"placa": placa, "frota": pick(item, "Terminal", "IdTerminal", "Frota"), "atualizado_em": now_iso()}
    return list(seen.values())


def sync_veiculos() -> int:
    rotina = "Veículos"
    try:
        rows = listar_veiculos()
        total = upsert_rows("wstt_veiculos", rows, "placa")
        log_execucao(rotina, "sucesso", total)
        return total
    except Exception as exc:
        log_execucao(rotina, "erro", 0, str(exc))
        raise


def coletar_historico_telemetria(ini: datetime, fim: datetime, progress: Callable[[int, int, int], None] | None = None) -> list[dict[str, Any]]:
    usuario, senha_md5 = _credentials()
    rows: list[dict[str, Any]] = []
    windows = hourly_windows(ini, fim)
    for idx, (h_ini, h_fim) in enumerate(windows, start=1):
        body = _auth_xml(usuario, senha_md5) + f"<dataInicio>{fmt_br(h_ini)}</dataInicio><dataFim>{fmt_br(h_fim)}</dataFim>"
        try:
            raw = soap_call("ListarDadosHistoricoTelemetria", body, timeout=180)
            if has_soap_fault(raw):
                if progress:
                    progress(idx, len(windows), 0)
                continue
            inner = extract_return_xml(raw)
            if not inner:
                if progress:
                    progress(idx, len(windows), 0)
                continue
            parsed = parse_inner_xml(inner)
            items = find_all(parsed, "HistoricoTelemetria")
            for d in items:
                rows.append({
                    "placa": pick(d, "placa", "Placa").upper().replace("-", "").replace(" ", ""),
                    "serial": pick(d, "serial", "Serial") or None,
                    "data_hora": normalize_timestamp(pick(d, "dataHora", "DataHora")),
                    "data_sys": normalize_timestamp(pick(d, "dataSys", "DataSys")),
                    "id_cliente": pick(d, "idCliente", "IdCliente") or None,
                    "id_contrato": pick(d, "idContrato", "IdContrato") or None,
                    "chassis": pick(d, "chassis", "Chassis") or None,
                    "altitude": to_num(pick(d, "altitude", "Altitude")),
                    "azimute": to_num(pick(d, "azimute", "Azimute")),
                    "consumo_combustivel": to_num(pick(d, "consumoCombustivel", "ConsumoCombustivel")),
                    "distancia_total": to_num(pick(d, "distanciaTotal", "DistanciaTotal")),
                    "ignicao": pick(d, "ignicao", "Ignicao") or None,
                    "latitude": to_num(pick(d, "latitude", "Latitude")),
                    "longitude": to_num(pick(d, "longitude", "Longitude")),
                    "nivel_adblue": to_num(pick(d, "nivelAdBlue", "nivelAdblue")),
                    "nivel_combustivel_litros": to_num(pick(d, "nivelCombustivelLitros")),
                    "nivel_combustivel_percentual": to_num(pick(d, "nivelCombustivelPercentual")),
                    "rpm": to_num(pick(d, "rpm", "RPM")),
                    "rpm_max": to_num(pick(d, "rpmMax", "RpmMax")),
                    "rpm_media": to_num(pick(d, "rpmMedia", "RpmMedia")),
                    "velocidade_can": to_num(pick(d, "velocidadeCan", "VelocidadeCan")),
                    "velocidade_gps": to_num(pick(d, "velocidadeGps", "VelocidadeGps")),
                    "velocidade_maxima": to_num(pick(d, "velocidadeMaxima", "VelocidadeMaxima")),
                    "velocidade_media": to_num(pick(d, "velocidadeMedia", "VelocidadeMedia")),
                    "synced_at": now_iso(),
                })
            if progress:
                progress(idx, len(windows), len(items))
        except Exception:
            if progress:
                progress(idx, len(windows), 0)
            continue
    return rows


def sync_telemetria(data_inicio: date | datetime | str, data_fim: date | datetime | str, progress: Callable[[int, int, int], None] | None = None) -> int:
    rotina = "Telemetria histórica"
    try:
        ini = parse_date_input(data_inicio)
        fim = parse_date_input(data_fim) + timedelta(days=1) - timedelta(seconds=1)
        if len(hourly_windows(ini, fim)) > 72:
            raise RuntimeError("Período muito longo para a WSTT. Use no máximo 3 dias por chamada.")
        rows = coletar_historico_telemetria(ini, fim, progress)
        total = upsert_rows("wstt_dados_historico_telemetria", rows, "placa,data_hora,serial")
        log_execucao(rotina, "sucesso", total)
        return total
    except Exception as exc:
        log_execucao(rotina, "erro", 0, str(exc))
        raise


def coletar_viagens(veiculos: list[dict[str, Any]], ini: datetime, fim: datetime, progress: Callable[[int, int, str, int], None] | None = None) -> list[dict[str, Any]]:
    usuario, senha_md5 = _credentials()
    rows: list[dict[str, Any]] = []
    di, df = fmt_iso(ini), fmt_iso(fim)
    for idx, veic in enumerate(veiculos, start=1):
        placa = str(veic.get("placa") or "").upper().replace("-", "").replace(" ", "")
        if not placa:
            continue
        body = _auth_xml(usuario, senha_md5) + f"<Placa>{placa}</Placa><dataInicio>{di}</dataInicio><dataFim>{df}</dataFim>"
        count = 0
        try:
            raw = soap_call("ListarHistoricoViagemTelemetria", body, timeout=180)
            if not has_soap_fault(raw):
                inner = extract_return_xml(raw)
                if inner:
                    parsed = parse_inner_xml(inner)
                    items = find_all(parsed, "historicoViagemTelemetria")
                    for v in items:
                        data_ini = normalize_timestamp(pick(v, "data_inicio_viagem", "dataInicioViagem"))
                        if not data_ini:
                            continue
                        rows.append({
                            "viagem_id": pick(v, "id", "Id") or None,
                            "placa": pick(v, "placa", "Placa").upper().replace("-", "").replace(" ", "") or placa,
                            "serial": pick(v, "serial", "Serial") or None,
                            "driver_id": pick(v, "driver_id", "driverId") or None,
                            "data_inicio_viagem": data_ini,
                            "data_fim_viagem": normalize_timestamp(pick(v, "data_fim_viagem", "dataFimViagem")),
                            "duracao_da_viagem": pick(v, "duracao_da_viagem") or None,
                            "distancia_total_percorrida": to_num(pick(v, "distancia_total_percorrida")),
                            "odometro_inicial": to_num(pick(v, "odometro_inicial")),
                            "odometro_final": to_num(pick(v, "odometro_final")),
                            "latitude_inicial": to_num(pick(v, "latitude_inicial")),
                            "longitude_inicial": to_num(pick(v, "longitude_inicial")),
                            "latitude_final": to_num(pick(v, "latitude_final")),
                            "longitude_final": to_num(pick(v, "longitude_final")),
                            "media_consumo_viagem": to_num(pick(v, "media_consumo_viagem")),
                            "nivel_combustivel_inicial": to_num(pick(v, "nivel_combustivel_inicial")),
                            "nivel_combustivel_final": to_num(pick(v, "nivel_combustivel_final")),
                            "quantidade_aceleracao_brusca": to_int(pick(v, "quantidade_aceleracao_brusca")),
                            "quantidade_freada_brusca": to_int(pick(v, "quantidade_freada_brusca")),
                            "quantidade_excesso_velocidade": to_int(pick(v, "quantidade_excesso_velocidade")),
                            "velocidade": pick(v, "velocidade") or None,
                            "acelerador": pick(v, "acelerador") or None,
                            "synced_at": now_iso(),
                        })
                        count += 1
        except Exception:
            pass
        if progress:
            progress(idx, len(veiculos), placa, count)
    return rows


def sync_viagens(data_inicio: date | datetime | str, data_fim: date | datetime | str, limite_placas: int = 50, progress: Callable[[int, int, str, int], None] | None = None) -> int:
    rotina = "Viagens telemetria"
    try:
        frota = select_rows("wstt_veiculos", "placa", limit=max(limite_placas, 1))
        if not frota:
            sync_veiculos()
            frota = select_rows("wstt_veiculos", "placa", limit=max(limite_placas, 1))
        ini = parse_date_input(data_inicio)
        fim = parse_date_input(data_fim) + timedelta(days=1) - timedelta(seconds=1)
        rows = coletar_viagens(frota[:limite_placas], ini, fim, progress)
        total = upsert_rows("wstt_viagens_telemetria", rows, "placa,data_inicio_viagem")
        log_execucao(rotina, "sucesso", total)
        return total
    except Exception as exc:
        log_execucao(rotina, "erro", 0, str(exc))
        raise


def coletar_eventos(ini: datetime, fim: datetime, versao: int = 2, progress: Callable[[int, int, int], None] | None = None) -> list[dict[str, Any]]:
    usuario, senha_md5 = _credentials()
    action = "ListarEventosTrackerTelemetria2" if versao == 2 else "ListarEventosTrackerTelemetria"
    rows: list[dict[str, Any]] = []
    windows = hourly_windows(ini, fim)
    for idx, (h_ini, h_fim) in enumerate(windows, start=1):
        body = _auth_xml(usuario, senha_md5) + f"<DataHoraInicial>{fmt_br(h_ini)}</DataHoraInicial><DataHoraFinal>{fmt_br(h_fim)}</DataHoraFinal>"
        try:
            raw = soap_call(action, body, timeout=180)
            if has_soap_fault(raw):
                if progress:
                    progress(idx, len(windows), 0)
                continue
            inner = extract_return_xml(raw)
            if not inner:
                if progress:
                    progress(idx, len(windows), 0)
                continue
            parsed = parse_inner_xml(inner)
            items = find_all(parsed, "EventoTelemetria")
            for ev in items:
                evento_id = pick(ev, "Id")
                data_evento = normalize_timestamp(pick(ev, "DataEvento"))
                if not evento_id and not data_evento:
                    continue
                row = {
                    "evento_id": evento_id or f"{pick(ev, 'Placa')}-{data_evento}",
                    "cod_evento": pick(ev, "CodEvento") or None,
                    "placa": pick(ev, "Placa").upper().replace("-", "").replace(" ", "") or None,
                    "serial": pick(ev, "Serial") or None,
                    "data_evento": data_evento,
                    "data_cadastro": normalize_timestamp(pick(ev, "DataCadastro")),
                    "endereco": pick(ev, "Endereco") or None,
                    "latitude_inicial": to_num(pick(ev, "LatitudeInicial")),
                    "longitude_inicial": to_num(pick(ev, "LongitudeInicial")),
                    "latitude_final": to_num(pick(ev, "LatitudeFinal")),
                    "longitude_final": to_num(pick(ev, "LongitudeFinal")),
                    "duracao_evento": to_num(pick(ev, "DuracaoEvento")),
                    "velocidade": to_num(pick(ev, "Velocidade")),
                    "velocidade_maxima": to_num(pick(ev, "VelocidadeMaxima")),
                    "velocidade_limite_configurado": to_num(pick(ev, "VelocidadeLimiteConfigurado")),
                    "rpm_maximo": to_num(pick(ev, "RpmMaximo")),
                    "aceleracao_maxima": to_num(pick(ev, "AceleracaoMaxima")),
                    "desaceleracao_maxima": to_num(pick(ev, "DesaceleracaoMaxima")),
                    "status": pick(ev, "Status") or None,
                    "id_viagem": pick(ev, "IdViagem") or None,
                    "synced_at": now_iso(),
                }
                if versao == 2:
                    row["descricao_evento"] = pick(ev, "DescricaoEvento") or None
                rows.append(row)
            if progress:
                progress(idx, len(windows), len(items))
        except Exception:
            if progress:
                progress(idx, len(windows), 0)
            continue
    return rows


def sync_eventos(data_inicio: date | datetime | str, data_fim: date | datetime | str, versao: int = 2, progress: Callable[[int, int, int], None] | None = None) -> int:
    rotina = "Eventos tracker"
    try:
        ini = parse_date_input(data_inicio)
        fim = parse_date_input(data_fim) + timedelta(days=1) - timedelta(seconds=1)
        if len(hourly_windows(ini, fim)) > 72:
            raise RuntimeError("Período muito longo para a WSTT. Use no máximo 3 dias por chamada.")
        rows = coletar_eventos(ini, fim, versao, progress)
        table = "wstt_eventos_tracker_telemetria2" if versao == 2 else "wstt_eventos_tracker_telemetria"
        total = upsert_rows(table, rows, "evento_id,data_evento")
        log_execucao(rotina, "sucesso", total)
        return total
    except Exception as exc:
        log_execucao(rotina, "erro", 0, str(exc))
        raise


def get_kpis() -> dict[str, Any]:
    try:
        veic = select_rows("wstt_veiculos", "placa", 20000)
        viagens = select_rows("wstt_viagens_telemetria", "placa,distancia_total_percorrida,quantidade_excesso_velocidade,quantidade_freada_brusca,quantidade_aceleracao_brusca", 20000)
        tele = select_rows("wstt_dados_historico_telemetria", "placa,velocidade_maxima,distancia_total,nivel_combustivel_litros", 20000)
        ev = select_rows("wstt_eventos_tracker_telemetria2", "evento_id,placa,velocidade_maxima", 20000)

        def _safe_float(v: Any) -> float:
            try:
                return float(v) if v not in (None, "", "None", "null") else 0.0
            except (TypeError, ValueError):
                return 0.0

        def _safe_int_field(v: Any) -> int:
            try:
                return int(float(v)) if v not in (None, "", "None", "null") else 0
            except (TypeError, ValueError):
                return 0

        eventos_viagem = sum(
            _safe_int_field(x.get("quantidade_excesso_velocidade")) +
            _safe_int_field(x.get("quantidade_freada_brusca")) +
            _safe_int_field(x.get("quantidade_aceleracao_brusca"))
            for x in viagens
        )
        velocidades = [_safe_float(x.get("velocidade_maxima")) for x in tele + ev]
        return {
            "veiculos": len(veic),
            "viagens": len(viagens),
            "telemetria": len(tele),
            "eventos": len(ev),
            "eventos_viagem": eventos_viagem,
            "km_viagens": round(sum(_safe_float(x.get("distancia_total_percorrida")) for x in viagens), 2),
            "velocidade_maxima": max(velocidades) if velocidades else 0.0,
        }
    except Exception:
        return {"veiculos": 0, "viagens": 0, "telemetria": 0, "eventos": 0, "eventos_viagem": 0, "km_viagens": 0, "velocidade_maxima": 0}
