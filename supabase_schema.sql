-- ============================================================
-- CENTRAL RASTER + OMNILINK/WSTT
-- Execute tudo no SQL Editor do Supabase.
-- Este script cria e também corrige tabelas antigas com ALTER TABLE.
-- ============================================================

create extension if not exists pgcrypto;

create table if not exists public.integracao_execucoes (
  id uuid primary key default gen_random_uuid(),
  origem text not null,
  rotina text not null,
  status text not null,
  qtd_registros integer default 0,
  erro text,
  executado_em timestamptz default now()
);

-- ============================================================
-- RASTER
-- ============================================================

create table if not exists public.raster_sm_geradas (
  codigo             bigint primary key,
  placa              text,
  data               timestamptz,
  data_prev_inicio   timestamptz,
  data_prev_fim      timestamptz,
  cod_ibge_origem    bigint,
  cidade_origem      text,
  cod_ibge_destino   bigint,
  cidade_destino     text,
  cnpj_cliente_orig  text,
  razao_cliente_orig text,
  cnpj_cliente_dest  text,
  razao_cliente_dest text,
  synced_at          timestamptz default now()
);

create table if not exists public.raster_checklist (
  codigo     text primary key,
  veiculo    text,
  carreta01  text,
  carreta02  text,
  carreta03  text,
  data_sol   text,
  teste_temp text,
  tipo       text,
  synced_at  timestamptz default now()
);



create table if not exists public.raster_checklist_resultado (
  cod_resultado text not null,
  cod_checklist bigint null,
  veiculo text null,
  cod_filial bigint null,
  cod_perfil_seguranca bigint null,
  status text null,
  resultado text null,
  apto boolean null,
  data_geracao timestamp with time zone null,
  data_expiracao timestamp with time zone null,
  url_documento text null,
  produtos jsonb null,
  raw jsonb null,
  synced_at timestamp with time zone null default now(),
  constraint raster_checklist_resultado_pkey primary key (cod_resultado)
);

alter table public.raster_checklist_resultado add column if not exists cod_checklist bigint;
alter table public.raster_checklist_resultado add column if not exists veiculo text;
alter table public.raster_checklist_resultado add column if not exists cod_filial bigint;
alter table public.raster_checklist_resultado add column if not exists cod_perfil_seguranca bigint;
alter table public.raster_checklist_resultado add column if not exists status text;
alter table public.raster_checklist_resultado add column if not exists resultado text;
alter table public.raster_checklist_resultado add column if not exists apto boolean;
alter table public.raster_checklist_resultado add column if not exists data_geracao timestamp with time zone;
alter table public.raster_checklist_resultado add column if not exists data_expiracao timestamp with time zone;
alter table public.raster_checklist_resultado add column if not exists url_documento text;
alter table public.raster_checklist_resultado add column if not exists produtos jsonb;
alter table public.raster_checklist_resultado add column if not exists raw jsonb;
alter table public.raster_checklist_resultado add column if not exists synced_at timestamp with time zone default now();

create index if not exists idx_raster_checklist_resultado_veiculo on public.raster_checklist_resultado using btree (veiculo);

create table if not exists public.raster_evento_fim_viagem (
  cod_solicitacao          bigint primary key,
  cod_filial               bigint,
  placa_veiculo            text,
  placa_carreta1           text,
  cpf_motorista1           text,
  status_viagem            text,
  status_checklist         text,
  aptidao_operacional      text,
  status_engate            text,
  status_detalhamento      text,
  status_rota              text,
  status_liberacao_engate  text,
  dentro_prazo             text,
  data_prev_inicio         timestamptz,
  data_prev_fim            timestamptz,
  data_real_inicio         timestamptz,
  data_real_fim            timestamptz,
  velocidade_media         numeric,
  maior_velocidade         numeric,
  tempo_total_viagem       numeric,
  tempo_parado             numeric,
  tempo_movimentando       numeric,
  percentual_atraso        numeric,
  desvios_rota             integer,
  eventos_velocidade       integer,
  link_timeline            text,
  synced_at                timestamptz default now()
);

-- Correção para quem já tinha criado a tabela antes sem colunas novas.
alter table public.raster_evento_fim_viagem add column if not exists aptidao_operacional text;
alter table public.raster_evento_fim_viagem add column if not exists cod_filial bigint;
alter table public.raster_evento_fim_viagem add column if not exists placa_veiculo text;
alter table public.raster_evento_fim_viagem add column if not exists placa_carreta1 text;
alter table public.raster_evento_fim_viagem add column if not exists cpf_motorista1 text;
alter table public.raster_evento_fim_viagem add column if not exists status_viagem text;
alter table public.raster_evento_fim_viagem add column if not exists status_checklist text;
alter table public.raster_evento_fim_viagem add column if not exists status_engate text;
alter table public.raster_evento_fim_viagem add column if not exists status_detalhamento text;
alter table public.raster_evento_fim_viagem add column if not exists status_rota text;
alter table public.raster_evento_fim_viagem add column if not exists status_liberacao_engate text;
alter table public.raster_evento_fim_viagem add column if not exists dentro_prazo text;
alter table public.raster_evento_fim_viagem add column if not exists data_prev_inicio timestamptz;
alter table public.raster_evento_fim_viagem add column if not exists data_prev_fim timestamptz;
alter table public.raster_evento_fim_viagem add column if not exists data_real_inicio timestamptz;
alter table public.raster_evento_fim_viagem add column if not exists data_real_fim timestamptz;
alter table public.raster_evento_fim_viagem add column if not exists velocidade_media numeric;
alter table public.raster_evento_fim_viagem add column if not exists maior_velocidade numeric;
alter table public.raster_evento_fim_viagem add column if not exists tempo_total_viagem numeric;
alter table public.raster_evento_fim_viagem add column if not exists tempo_parado numeric;
alter table public.raster_evento_fim_viagem add column if not exists tempo_movimentando numeric;
alter table public.raster_evento_fim_viagem add column if not exists percentual_atraso numeric;
alter table public.raster_evento_fim_viagem add column if not exists desvios_rota integer;
alter table public.raster_evento_fim_viagem add column if not exists eventos_velocidade integer;
alter table public.raster_evento_fim_viagem add column if not exists link_timeline text;
alter table public.raster_evento_fim_viagem add column if not exists synced_at timestamptz default now();

create index if not exists idx_raster_sm_placa on public.raster_sm_geradas (placa);
create index if not exists idx_raster_checklist_veiculo on public.raster_checklist (veiculo);
create index if not exists idx_raster_evento_placa on public.raster_evento_fim_viagem (placa_veiculo);
create index if not exists idx_raster_evento_data on public.raster_evento_fim_viagem (data_real_fim);

-- ============================================================
-- RASTER - STATUS VIAGEM (getStatusViagem)
-- ============================================================
create table if not exists public.raster_status_viagem (
  chave text primary key,
  cod_solicitacao bigint,
  cod_pre_solicitacao bigint,
  cod_filial bigint,
  cod_perfil_seguranca bigint,
  cod_rota bigint,
  placa_veiculo text,
  placa_carreta1_original text,
  placa_carreta1_atual text,
  cpf_motorista1_original text,
  cpf_motorista1_atual text,
  cnpj_transportador text,
  cnpj_cliente_orig text,
  cnpj_cliente_dest text,
  status_viagem text,
  data_prev_inicio timestamptz,
  data_prev_fim timestamptz,
  data_real_inicio timestamptz,
  data_hora_ult_posicao timestamptz,
  latitude_ult_posicao numeric,
  longitude_ult_posicao numeric,
  ref_ult_posicao text,
  documentos jsonb,
  documentos_resumo text,
  qtd_documentos integer default 0,
  raw jsonb,
  payload jsonb,
  synced_at timestamptz default now()
);

alter table public.raster_status_viagem add column if not exists cod_solicitacao bigint;
alter table public.raster_status_viagem add column if not exists cod_pre_solicitacao bigint;
alter table public.raster_status_viagem add column if not exists cod_filial bigint;
alter table public.raster_status_viagem add column if not exists cod_perfil_seguranca bigint;
alter table public.raster_status_viagem add column if not exists cod_rota bigint;
alter table public.raster_status_viagem add column if not exists placa_veiculo text;
alter table public.raster_status_viagem add column if not exists placa_carreta1_original text;
alter table public.raster_status_viagem add column if not exists placa_carreta1_atual text;
alter table public.raster_status_viagem add column if not exists cpf_motorista1_original text;
alter table public.raster_status_viagem add column if not exists cpf_motorista1_atual text;
alter table public.raster_status_viagem add column if not exists cnpj_transportador text;
alter table public.raster_status_viagem add column if not exists cnpj_cliente_orig text;
alter table public.raster_status_viagem add column if not exists cnpj_cliente_dest text;
alter table public.raster_status_viagem add column if not exists status_viagem text;
alter table public.raster_status_viagem add column if not exists data_prev_inicio timestamptz;
alter table public.raster_status_viagem add column if not exists data_prev_fim timestamptz;
alter table public.raster_status_viagem add column if not exists data_real_inicio timestamptz;
alter table public.raster_status_viagem add column if not exists data_hora_ult_posicao timestamptz;
alter table public.raster_status_viagem add column if not exists latitude_ult_posicao numeric;
alter table public.raster_status_viagem add column if not exists longitude_ult_posicao numeric;
alter table public.raster_status_viagem add column if not exists ref_ult_posicao text;
alter table public.raster_status_viagem add column if not exists documentos jsonb;
alter table public.raster_status_viagem add column if not exists documentos_resumo text;
alter table public.raster_status_viagem add column if not exists qtd_documentos integer default 0;
alter table public.raster_status_viagem add column if not exists raw jsonb;
alter table public.raster_status_viagem add column if not exists payload jsonb;
alter table public.raster_status_viagem add column if not exists synced_at timestamptz default now();

create index if not exists idx_raster_status_viagem_placa on public.raster_status_viagem (placa_veiculo);
create index if not exists idx_raster_status_viagem_status on public.raster_status_viagem (status_viagem);
create index if not exists idx_raster_status_viagem_sync on public.raster_status_viagem (synced_at);

-- Documentos vinculados ao getStatusViagem
create table if not exists public.raster_status_viagem_documentos (
  chave text primary key,
  chave_status_viagem text,
  cod_solicitacao bigint,
  cod_pre_solicitacao bigint,
  placa_veiculo text,
  tipo text,
  numero text,
  origem text,
  raw jsonb,
  synced_at timestamptz default now()
);

alter table public.raster_status_viagem_documentos add column if not exists chave_status_viagem text;
alter table public.raster_status_viagem_documentos add column if not exists cod_solicitacao bigint;
alter table public.raster_status_viagem_documentos add column if not exists cod_pre_solicitacao bigint;
alter table public.raster_status_viagem_documentos add column if not exists placa_veiculo text;
alter table public.raster_status_viagem_documentos add column if not exists tipo text;
alter table public.raster_status_viagem_documentos add column if not exists numero text;
alter table public.raster_status_viagem_documentos add column if not exists origem text;
alter table public.raster_status_viagem_documentos add column if not exists raw jsonb;
alter table public.raster_status_viagem_documentos add column if not exists synced_at timestamptz default now();

create index if not exists idx_raster_status_viagem_docs_placa on public.raster_status_viagem_documentos (placa_veiculo);
create index if not exists idx_raster_status_viagem_docs_numero on public.raster_status_viagem_documentos (numero);
create index if not exists idx_raster_status_viagem_docs_sync on public.raster_status_viagem_documentos (synced_at);

-- ============================================================
-- OMNILINK / WSTT
-- ============================================================

create table if not exists public.wstt_veiculos (
  placa          text primary key,
  frota          text,
  atualizado_em  timestamptz
);

create table if not exists public.wstt_viagens_telemetria (
  id                              bigserial primary key,
  viagem_id                       text,
  placa                           text not null,
  serial                          text,
  driver_id                       text,
  data_inicio_viagem              text,
  data_fim_viagem                 text,
  duracao_da_viagem               text,
  distancia_total_percorrida      numeric,
  odometro_inicial                numeric,
  odometro_final                  numeric,
  latitude_inicial                numeric,
  longitude_inicial               numeric,
  latitude_final                  numeric,
  longitude_final                 numeric,
  media_consumo_viagem            numeric,
  nivel_combustivel_inicial       numeric,
  nivel_combustivel_final         numeric,
  quantidade_aceleracao_brusca    integer,
  quantidade_freada_brusca        integer,
  quantidade_excesso_velocidade   integer,
  velocidade                      text,
  acelerador                      text,
  synced_at                       timestamptz default now(),
  unique (placa, data_inicio_viagem)
);

create table if not exists public.wstt_dados_historico_telemetria (
  id                            bigserial primary key,
  placa                         text not null,
  serial                        text,
  data_hora                     text,
  data_sys                      text,
  id_cliente                    text,
  id_contrato                   text,
  chassis                       text,
  altitude                      numeric,
  azimute                       numeric,
  consumo_combustivel           numeric,
  distancia_total               numeric,
  ignicao                       text,
  latitude                      numeric,
  longitude                     numeric,
  nivel_adblue                  numeric,
  nivel_combustivel_litros      numeric,
  nivel_combustivel_percentual  numeric,
  rpm                           numeric,
  rpm_max                       numeric,
  rpm_media                     numeric,
  velocidade_can                numeric,
  velocidade_gps                numeric,
  velocidade_maxima             numeric,
  velocidade_media              numeric,
  synced_at                     timestamptz default now(),
  unique (placa, data_hora, serial)
);

create table if not exists public.wstt_eventos_tracker_telemetria (
  id                             bigserial primary key,
  evento_id                      text,
  cod_evento                     text,
  placa                          text,
  serial                         text,
  data_evento                    text,
  data_cadastro                  text,
  endereco                       text,
  latitude_inicial               numeric,
  longitude_inicial              numeric,
  latitude_final                 numeric,
  longitude_final                numeric,
  duracao_evento                 numeric,
  velocidade                     numeric,
  velocidade_maxima              numeric,
  velocidade_limite_configurado  numeric,
  rpm_maximo                     numeric,
  aceleracao_maxima              numeric,
  desaceleracao_maxima           numeric,
  status                         text,
  id_viagem                      text,
  synced_at                      timestamptz default now(),
  unique (evento_id, data_evento)
);

create table if not exists public.wstt_eventos_tracker_telemetria2 (
  id                             bigserial primary key,
  evento_id                      text,
  cod_evento                     text,
  placa                          text,
  serial                         text,
  data_evento                    text,
  data_cadastro                  text,
  endereco                       text,
  latitude_inicial               numeric,
  longitude_inicial              numeric,
  latitude_final                 numeric,
  longitude_final                numeric,
  duracao_evento                 numeric,
  velocidade                     numeric,
  velocidade_maxima              numeric,
  velocidade_limite_configurado  numeric,
  rpm_maximo                     numeric,
  aceleracao_maxima              numeric,
  desaceleracao_maxima           numeric,
  status                         text,
  id_viagem                      text,
  descricao_evento               text,
  synced_at                      timestamptz default now(),
  unique (evento_id, data_evento)
);

create index if not exists idx_wstt_veiculos_placa on public.wstt_veiculos (placa);
create index if not exists idx_wstt_viagens_placa on public.wstt_viagens_telemetria (placa);
create index if not exists idx_wstt_viagens_data on public.wstt_viagens_telemetria (data_inicio_viagem);
create index if not exists idx_wstt_telemetria_placa on public.wstt_dados_historico_telemetria (placa);
create index if not exists idx_wstt_telemetria_data on public.wstt_dados_historico_telemetria (data_hora);
create index if not exists idx_wstt_eventos_placa on public.wstt_eventos_tracker_telemetria (placa);
create index if not exists idx_wstt_eventos_data on public.wstt_eventos_tracker_telemetria (data_evento);
create index if not exists idx_wstt_eventos2_placa on public.wstt_eventos_tracker_telemetria2 (placa);
create index if not exists idx_wstt_eventos2_data on public.wstt_eventos_tracker_telemetria2 (data_evento);

-- Compatibilidade: se você ainda usa a tabela antiga omnilink_telemetria, ela fica criada também.
create table if not exists public.omnilink_telemetria (
  evento_id                         text primary key,
  placa                             text,
  data_evento                       timestamptz,
  quantidade_horas_ocioso           numeric,
  litros_perdidos                   numeric,
  quantidade_excesso_velocidade     integer,
  quantidade_freada_brusca          integer,
  quantidade_aceleracao_brusca      integer,
  distancia_total_percorrida        numeric,
  velocidade_maxima                 numeric,
  synced_at                         timestamptz default now()
);

-- ============================================================
-- VIEWS PROFISSIONAIS
-- ============================================================

create or replace view public.vw_raster_status_veiculo as
with ultima_viagem as (
  select distinct on (placa_veiculo)
    placa_veiculo as placa,
    cod_solicitacao,
    cod_filial,
    status_viagem,
    status_checklist,
    coalesce(
      aptidao_operacional,
      case
        when status_checklist = 'S' then 'APTO'
        when status_checklist = 'N' then 'NAO_APTO'
        when status_checklist = 'I' then 'PENDENTE'
        else 'SEM_STATUS'
      end
    ) as aptidao_operacional,
    status_engate,
    status_rota,
    status_liberacao_engate,
    dentro_prazo,
    velocidade_media,
    maior_velocidade,
    tempo_parado,
    desvios_rota,
    eventos_velocidade,
    data_real_fim,
    synced_at
  from public.raster_evento_fim_viagem
  where placa_veiculo is not null
  order by placa_veiculo, coalesce(data_real_fim, synced_at) desc
), ultimo_checklist as (
  select veiculo as placa, max(data_sol) as ultima_data_sol, count(*) as qtd_checklists
  from public.raster_checklist
  group by veiculo
), sm as (
  select placa, count(*) as qtd_sms, max(synced_at) as ultima_sm
  from public.raster_sm_geradas
  group by placa
)
select
  coalesce(v.placa, c.placa, sm.placa) as placa,
  v.cod_solicitacao,
  v.cod_filial,
  v.status_viagem,
  v.status_checklist,
  coalesce(v.aptidao_operacional, 'SEM_STATUS') as aptidao_operacional,
  v.status_engate,
  v.status_rota,
  v.status_liberacao_engate,
  v.dentro_prazo,
  v.velocidade_media,
  v.maior_velocidade,
  v.tempo_parado,
  v.desvios_rota,
  v.eventos_velocidade,
  c.ultima_data_sol,
  coalesce(c.qtd_checklists, 0) as qtd_checklists,
  coalesce(sm.qtd_sms, 0) as qtd_sms,
  sm.ultima_sm,
  coalesce(v.synced_at, sm.ultima_sm) as ultima_sincronizacao
from ultima_viagem v
full join ultimo_checklist c on c.placa = v.placa
full join sm on sm.placa = coalesce(v.placa, c.placa);

create or replace view public.vw_wstt_resumo_placa as
with viagens as (
  select
    placa,
    count(*) as qtd_viagens,
    sum(coalesce(distancia_total_percorrida,0)) as km_total,
    sum(coalesce(quantidade_aceleracao_brusca,0)) as aceleracao_brusca,
    sum(coalesce(quantidade_freada_brusca,0)) as freada_brusca,
    sum(coalesce(quantidade_excesso_velocidade,0)) as excesso_velocidade,
    max(synced_at) as ultima_viagem_sync
  from public.wstt_viagens_telemetria
  group by placa
), tele as (
  select
    placa,
    count(*) as qtd_leituras,
    max(velocidade_maxima) as velocidade_maxima,
    avg(velocidade_media) as velocidade_media,
    max(synced_at) as ultima_telemetria_sync
  from public.wstt_dados_historico_telemetria
  group by placa
), eventos as (
  select
    placa,
    count(*) as qtd_eventos_tracker,
    max(velocidade_maxima) as maior_velocidade_evento,
    max(synced_at) as ultimo_evento_sync
  from public.wstt_eventos_tracker_telemetria2
  group by placa
)
select
  coalesce(v.placa, vi.placa, t.placa, e.placa) as placa,
  v.frota,
  coalesce(vi.qtd_viagens,0) as qtd_viagens,
  coalesce(vi.km_total,0) as km_total,
  coalesce(vi.aceleracao_brusca,0) as aceleracao_brusca,
  coalesce(vi.freada_brusca,0) as freada_brusca,
  coalesce(vi.excesso_velocidade,0) as excesso_velocidade,
  coalesce(t.qtd_leituras,0) as qtd_leituras_telemetria,
  t.velocidade_maxima,
  t.velocidade_media,
  coalesce(e.qtd_eventos_tracker,0) as qtd_eventos_tracker,
  e.maior_velocidade_evento,
  greatest(vi.ultima_viagem_sync, t.ultima_telemetria_sync, e.ultimo_evento_sync, v.atualizado_em) as ultima_sincronizacao
from public.wstt_veiculos v
full join viagens vi on vi.placa = v.placa
full join tele t on t.placa = coalesce(v.placa, vi.placa)
full join eventos e on e.placa = coalesce(v.placa, vi.placa, t.placa);

create or replace view public.vw_analise_integracoes as
select 'Raster SM' as origem, count(*)::numeric as total_registros, max(synced_at) as ultima_sincronizacao from public.raster_sm_geradas
union all
select 'Raster Checklist', count(*)::numeric, max(synced_at) from public.raster_checklist
union all
select 'Raster Viagens', count(*)::numeric, max(synced_at) from public.raster_evento_fim_viagem
union all
select 'WSTT Veículos', count(*)::numeric, max(atualizado_em) from public.wstt_veiculos
union all
select 'WSTT Viagens', count(*)::numeric, max(synced_at) from public.wstt_viagens_telemetria
union all
select 'WSTT Telemetria', count(*)::numeric, max(synced_at) from public.wstt_dados_historico_telemetria
union all
select 'WSTT Eventos', count(*)::numeric, max(synced_at) from public.wstt_eventos_tracker_telemetria2;

-- ============================================================
-- RASTER - TABELAS DE APOIO PARA CHECKLIST
-- Fluxo correto informado pela Raster:
-- 1) getTabela para FILIAIS, PERFIL_SEGURANCA e PRODUTOS
-- 2) setIncluirCheckList para obter CodCheckList
-- 3) getGerarResultadoCheckList para obter Status/Resultado/PDF
-- ============================================================

create table if not exists public.raster_tabelas (
  tabela text not null,
  codigo text not null,
  descricao text,
  dados jsonb,
  synced_at timestamptz default now(),
  constraint raster_tabelas_pkey primary key (tabela, codigo)
);

create index if not exists idx_raster_tabelas_tabela on public.raster_tabelas using btree (tabela);

create table if not exists public.raster_checklist_solicitacoes (
  chave text primary key,
  cod_checklist bigint,
  veiculo text,
  cod_filial bigint,
  placa_carreta1 text,
  placa_carreta2 text,
  placa_carreta3 text,
  vinculo text,
  tipo text,
  sensor_temperatura text,
  responsavel text,
  celular1 text,
  celular2 text,
  data_hora_agendada text,
  cod_erro text,
  msg_erro text,
  raw jsonb,
  synced_at timestamptz default now()
);

alter table public.raster_checklist_solicitacoes add column if not exists cod_checklist bigint;
alter table public.raster_checklist_solicitacoes add column if not exists veiculo text;
alter table public.raster_checklist_solicitacoes add column if not exists cod_filial bigint;
alter table public.raster_checklist_solicitacoes add column if not exists raw jsonb;
alter table public.raster_checklist_solicitacoes add column if not exists synced_at timestamptz default now();

create index if not exists idx_raster_checklist_solicitacoes_cod on public.raster_checklist_solicitacoes using btree (cod_checklist);
create index if not exists idx_raster_checklist_solicitacoes_veiculo on public.raster_checklist_solicitacoes using btree (veiculo);

-- ============================================================
-- AJUSTE STATUS VIAGEM - DOCUMENTOS CTE / CARGA
-- Versão segura: não depende de colunas antigas inexistentes.
-- Também prepara campos retornados de ColetasEntregas -> Documentos.
-- ============================================================

alter table public.raster_status_viagem_documentos add column if not exists chave_status_viagem text;
alter table public.raster_status_viagem_documentos add column if not exists cod_solicitacao bigint;
alter table public.raster_status_viagem_documentos add column if not exists cod_pre_solicitacao bigint;
alter table public.raster_status_viagem_documentos add column if not exists placa_veiculo text;
alter table public.raster_status_viagem_documentos add column if not exists ordem_coleta_entrega bigint;
alter table public.raster_status_viagem_documentos add column if not exists tipo_coleta_entrega text;
alter table public.raster_status_viagem_documentos add column if not exists cnpj_cliente_coleta_entrega text;
alter table public.raster_status_viagem_documentos add column if not exists tipo text;
alter table public.raster_status_viagem_documentos add column if not exists numero text;
alter table public.raster_status_viagem_documentos add column if not exists origem text;
alter table public.raster_status_viagem_documentos add column if not exists raw jsonb;
alter table public.raster_status_viagem_documentos add column if not exists synced_at timestamptz default now();

update public.raster_status_viagem_documentos
set
  tipo = upper(coalesce(tipo, raw->>'Tipo', raw->>'tipo')),
  numero = coalesce(numero, raw->>'Numero', raw->>'numero'),
  origem = coalesce(origem, 'getStatusViagem')
where
  tipo is null
  or numero is null
  or origem is null;

create index if not exists idx_raster_status_viagem_docs_sm on public.raster_status_viagem_documentos using btree (cod_solicitacao);
create index if not exists idx_raster_status_viagem_docs_pre_sm on public.raster_status_viagem_documentos using btree (cod_pre_solicitacao);
create index if not exists idx_raster_status_viagem_docs_placa on public.raster_status_viagem_documentos using btree (placa_veiculo);
create index if not exists idx_raster_status_viagem_docs_tipo on public.raster_status_viagem_documentos using btree (tipo);
create index if not exists idx_raster_status_viagem_docs_numero_clean on public.raster_status_viagem_documentos using btree (numero);

-- Troca segura porque versões antigas da view tinham colunas diferentes, como id.
drop view if exists public.vw_raster_status_viagem_documentos cascade;

create view public.vw_raster_status_viagem_documentos as
select
  chave,
  chave_status_viagem,
  cod_solicitacao,
  cod_pre_solicitacao,
  placa_veiculo,
  ordem_coleta_entrega,
  tipo_coleta_entrega,
  cnpj_cliente_coleta_entrega,
  tipo,
  numero,
  origem,
  synced_at
from public.raster_status_viagem_documentos
where numero is not null;

notify pgrst, 'reload schema';

-- ============================================================
-- RASTER getEventoFimViagem - estrutura completa páginas 100 a 105
-- Requisição automática: mês anterior completo + mês atual completo, StatusViagem = T
-- ============================================================

alter table public.raster_evento_fim_viagem add column if not exists sequencial bigint;
alter table public.raster_evento_fim_viagem add column if not exists cod_pre_solicitacao bigint;
alter table public.raster_evento_fim_viagem add column if not exists vinc_veiculo text;
alter table public.raster_evento_fim_viagem add column if not exists vinc_carreta1 text;
alter table public.raster_evento_fim_viagem add column if not exists placa_carreta2 text;
alter table public.raster_evento_fim_viagem add column if not exists vinc_carreta2 text;
alter table public.raster_evento_fim_viagem add column if not exists placa_carreta3 text;
alter table public.raster_evento_fim_viagem add column if not exists vinc_carreta4 text;
alter table public.raster_evento_fim_viagem add column if not exists vinc_motorista1 text;
alter table public.raster_evento_fim_viagem add column if not exists cpf_motorista2 text;
alter table public.raster_evento_fim_viagem add column if not exists vinc_motorista2 text;
alter table public.raster_evento_fim_viagem add column if not exists cod_ibge_cidade_orig bigint;
alter table public.raster_evento_fim_viagem add column if not exists cod_ibge_cidade_dest bigint;
alter table public.raster_evento_fim_viagem add column if not exists cnpj_cliente_orig text;
alter table public.raster_evento_fim_viagem add column if not exists cnpj_cliente_dest text;
alter table public.raster_evento_fim_viagem add column if not exists data_hora_prev_ini timestamptz;
alter table public.raster_evento_fim_viagem add column if not exists data_hora_prev_fim timestamptz;
alter table public.raster_evento_fim_viagem add column if not exists data_hora_real_ini timestamptz;
alter table public.raster_evento_fim_viagem add column if not exists data_hora_real_fim timestamptz;
alter table public.raster_evento_fim_viagem add column if not exists status_localiz_secund text;
alter table public.raster_evento_fim_viagem add column if not exists status_localiz_avulso text;
alter table public.raster_evento_fim_viagem add column if not exists status_escolta_armada text;
alter table public.raster_evento_fim_viagem add column if not exists status_escolta_velada text;
alter table public.raster_evento_fim_viagem add column if not exists local_maior_velocidade text;
alter table public.raster_evento_fim_viagem add column if not exists latitude_maior_velocidade numeric;
alter table public.raster_evento_fim_viagem add column if not exists longitude_maior_velocidade numeric;
alter table public.raster_evento_fim_viagem add column if not exists percentual_movimentando numeric;
alter table public.raster_evento_fim_viagem add column if not exists maior_tempo_movimentando bigint;
alter table public.raster_evento_fim_viagem add column if not exists dia_maior_tempo_movimentando bigint;
alter table public.raster_evento_fim_viagem add column if not exists perc_maior_tempo_movimentando numeric;
alter table public.raster_evento_fim_viagem add column if not exists tempo_parado_area_risco bigint;
alter table public.raster_evento_fim_viagem add column if not exists tempo_parado_alvos bigint;
alter table public.raster_evento_fim_viagem add column if not exists percentual_pernoite numeric;
alter table public.raster_evento_fim_viagem add column if not exists menor_pernoite bigint;
alter table public.raster_evento_fim_viagem add column if not exists botao_panico bigint;
alter table public.raster_evento_fim_viagem add column if not exists eficiencia_temperatura numeric;
alter table public.raster_evento_fim_viagem add column if not exists paradas_area_risco bigint;
alter table public.raster_evento_fim_viagem add column if not exists desvios_de_rota bigint;
alter table public.raster_evento_fim_viagem add column if not exists sem_posicao bigint;
alter table public.raster_evento_fim_viagem add column if not exists rodou_fora_horario text;
alter table public.raster_evento_fim_viagem add column if not exists violacao_painel bigint;
alter table public.raster_evento_fim_viagem add column if not exists violacao_antena bigint;
alter table public.raster_evento_fim_viagem add column if not exists desengate bigint;
alter table public.raster_evento_fim_viagem add column if not exists ultima_temperatura text;
alter table public.raster_evento_fim_viagem add column if not exists razao_transportador text;
alter table public.raster_evento_fim_viagem add column if not exists fantasia_transportador text;
alter table public.raster_evento_fim_viagem add column if not exists cnpj_transportador text;
alter table public.raster_evento_fim_viagem add column if not exists razao_proprietario text;
alter table public.raster_evento_fim_viagem add column if not exists fantasia_proprietario text;
alter table public.raster_evento_fim_viagem add column if not exists cnpj_proprietario text;
alter table public.raster_evento_fim_viagem add column if not exists data_hora_identificou_fim_viagem timestamptz;
alter table public.raster_evento_fim_viagem add column if not exists periodo_consulta text;
alter table public.raster_evento_fim_viagem add column if not exists data_inicial_consulta date;
alter table public.raster_evento_fim_viagem add column if not exists data_final_consulta date;
alter table public.raster_evento_fim_viagem add column if not exists raw jsonb;

-- Mantém compatibilidade com as colunas antigas já usadas no dashboard
update public.raster_evento_fim_viagem
set
  data_hora_prev_ini = coalesce(data_hora_prev_ini, data_prev_inicio),
  data_hora_prev_fim = coalesce(data_hora_prev_fim, data_prev_fim),
  data_hora_real_ini = coalesce(data_hora_real_ini, data_real_inicio),
  data_hora_real_fim = coalesce(data_hora_real_fim, data_real_fim)
where data_hora_prev_ini is null or data_hora_prev_fim is null or data_hora_real_ini is null or data_hora_real_fim is null;

create index if not exists idx_raster_evento_fim_pre_sm on public.raster_evento_fim_viagem (cod_pre_solicitacao);
create index if not exists idx_raster_evento_fim_status on public.raster_evento_fim_viagem (status_viagem);
create index if not exists idx_raster_evento_fim_periodo on public.raster_evento_fim_viagem (data_inicial_consulta, data_final_consulta);

create table if not exists public.raster_evento_fim_viagem_coletas (
  chave text primary key,
  cod_solicitacao bigint,
  cod_pre_solicitacao bigint,
  placa_viagem text,
  placa_veiculo text,
  ordem integer,
  tipo text,
  cod_ibge_cidade bigint,
  cnpj_cliente text,
  data_hora_prev_chegada timestamptz,
  data_hora_prev_saida timestamptz,
  data_hora_real_chegada timestamptz,
  data_hora_real_saida timestamptz,
  data_hora_calculada_chegada timestamptz,
  latitude numeric,
  longitude numeric,
  dentro_prazo text,
  diferenca_tempo text,
  eficiencia_temperatura numeric,
  percentual_percorrido numeric,
  percentual_restante numeric,
  km_restante_entrega numeric,
  km_percorrido_entrega numeric,
  chegou_na_entrega text,
  distancia_rota numeric,
  data_hora_ultima_posicao timestamptz,
  latitude_ultima_posicao numeric,
  longitude_ultima_posicao numeric,
  referencia_ultima_posicao text,
  raw jsonb,
  synced_at timestamptz default now()
);

alter table public.raster_evento_fim_viagem_coletas add column if not exists cod_pre_solicitacao bigint;
alter table public.raster_evento_fim_viagem_coletas add column if not exists placa_viagem text;
alter table public.raster_evento_fim_viagem_coletas add column if not exists raw jsonb;
alter table public.raster_evento_fim_viagem_coletas add column if not exists synced_at timestamptz default now();

create index if not exists idx_raster_evento_coletas_sm on public.raster_evento_fim_viagem_coletas (cod_solicitacao);
create index if not exists idx_raster_evento_coletas_placa on public.raster_evento_fim_viagem_coletas (placa_veiculo);
create index if not exists idx_raster_evento_coletas_tipo on public.raster_evento_fim_viagem_coletas (tipo);

create table if not exists public.raster_evento_fim_viagem_pernoites (
  chave text primary key,
  cod_solicitacao bigint,
  cod_pre_solicitacao bigint,
  data_hora_inicial timestamptz,
  data_hora_final timestamptz,
  percentual_eficiencia numeric,
  raw jsonb,
  synced_at timestamptz default now()
);

create index if not exists idx_raster_evento_pernoites_sm on public.raster_evento_fim_viagem_pernoites (cod_solicitacao);

-- Complemento da tabela de documentos para identificar a coleta/entrega de origem
alter table public.raster_status_viagem_documentos add column if not exists ordem_coleta_entrega integer;
alter table public.raster_status_viagem_documentos add column if not exists tipo_coleta_entrega text;
alter table public.raster_status_viagem_documentos add column if not exists cnpj_cliente_coleta_entrega text;

create index if not exists idx_raster_status_docs_sm_tipo on public.raster_status_viagem_documentos (cod_solicitacao, tipo);
create index if not exists idx_raster_status_docs_numero on public.raster_status_viagem_documentos (numero);

-- Views operacionais limpas
create or replace view public.vw_raster_evento_fim_viagem_completo as
select
  cod_solicitacao,
  cod_pre_solicitacao,
  sequencial,
  cod_filial,
  placa_veiculo,
  vinc_veiculo,
  placa_carreta1,
  vinc_carreta1,
  placa_carreta2,
  vinc_carreta2,
  placa_carreta3,
  vinc_carreta4,
  cpf_motorista1,
  vinc_motorista1,
  cpf_motorista2,
  vinc_motorista2,
  cod_ibge_cidade_orig,
  cod_ibge_cidade_dest,
  cnpj_cliente_orig,
  cnpj_cliente_dest,
  data_hora_prev_ini,
  data_hora_prev_fim,
  status_viagem,
  data_hora_real_ini,
  data_hora_real_fim,
  status_engate,
  status_detalhamento,
  status_rota,
  status_checklist,
  aptidao_operacional,
  status_liberacao_engate,
  status_localiz_secund,
  status_localiz_avulso,
  status_escolta_armada,
  status_escolta_velada,
  dentro_prazo,
  percentual_atraso,
  velocidade_media,
  maior_velocidade,
  local_maior_velocidade,
  latitude_maior_velocidade,
  longitude_maior_velocidade,
  tempo_total_viagem,
  tempo_parado,
  tempo_movimentando,
  percentual_movimentando,
  maior_tempo_movimentando,
  dia_maior_tempo_movimentando,
  perc_maior_tempo_movimentando,
  tempo_parado_area_risco,
  tempo_parado_alvos,
  percentual_pernoite,
  menor_pernoite,
  botao_panico,
  eficiencia_temperatura,
  eventos_velocidade,
  paradas_area_risco,
  desvios_de_rota,
  sem_posicao,
  rodou_fora_horario,
  violacao_painel,
  violacao_antena,
  desengate,
  link_timeline,
  ultima_temperatura,
  razao_transportador,
  fantasia_transportador,
  cnpj_transportador,
  razao_proprietario,
  fantasia_proprietario,
  cnpj_proprietario,
  data_hora_identificou_fim_viagem,
  periodo_consulta,
  data_inicial_consulta,
  data_final_consulta,
  synced_at
from public.raster_evento_fim_viagem;

create or replace view public.vw_raster_evento_fim_documentos as
select
  d.cod_solicitacao,
  d.cod_pre_solicitacao,
  v.status_viagem,
  v.status_checklist,
  d.placa_veiculo,
  d.ordem_coleta_entrega,
  d.tipo_coleta_entrega,
  d.cnpj_cliente_coleta_entrega,
  d.tipo as tipo_documento,
  d.numero as numero_documento,
  d.origem,
  d.synced_at
from public.raster_status_viagem_documentos d
left join public.raster_evento_fim_viagem v on v.cod_solicitacao = d.cod_solicitacao
where d.numero is not null;

create or replace view public.vw_raster_evento_fim_carga_cte as
select *
from public.vw_raster_evento_fim_documentos
where upper(tipo_documento) in ('CARGA', 'CTE', 'CT-E', 'CTRC', 'LOAD NUMBER');

notify pgrst, 'reload schema';
