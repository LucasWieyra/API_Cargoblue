# Status viagem com documentos

Esta versão mantém o fluxo sem criação de checklist e adiciona captura dos documentos retornados pelo método Raster `getStatusViagem`.

## O que foi adicionado

- Campo `documentos` em `raster_status_viagem` para guardar a lista bruta de documentos retornados.
- Campos operacionais `documentos_resumo` e `qtd_documentos`.
- Nova tabela `raster_status_viagem_documentos` para visualizar documentos em linhas separadas.
- Aba Raster > Status viagem mostra o status da viagem e, abaixo, os documentos vinculados.

## Importante

O app não chama `setIncluirCheckList` e não cria checklist.
O `getStatusViagem` continua rodando automático por placas já existentes nas bases Raster/WSTT.
Execute `supabase_schema.sql` no Supabase antes de publicar esta versão.
