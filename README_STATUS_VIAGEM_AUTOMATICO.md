# Versão com getStatusViagem automático

Esta versão adiciona a rotina Raster `getStatusViagem` sem preenchimento manual.

## O que faz

- Não cria checklist.
- Não chama `setIncluirCheckList`.
- Coleta placas automaticamente de SM abertas, viagens, checklist e WSTT.
- Consulta `getStatusViagem` por placa.
- Salva em `raster_status_viagem`.
- Inclui a rotina na execução automática.
- `getEventoFimViagem` usa período automático: mês anterior + mês atual.

## Secrets opcionais

```toml
RASTER_STATUS_VIAGEM_LIMITE = "50"
RASTER_DELAY_STATUS_VIAGEM_SECONDS = "1"
RASTER_EVENTO_FIM_STATUS = "T"
# Se quiser janela curta em dias, defina; se deixar vazio usa mês anterior + mês atual
RASTER_EVENTO_FIM_DIAS = ""
```

## SQL

Execute `supabase_schema.sql` no Supabase para criar `raster_status_viagem`.
