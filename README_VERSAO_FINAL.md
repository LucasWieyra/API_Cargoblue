# Versão final segura — Raster checklist somente consulta

Esta versão foi ajustada para o fluxo correto:

1. **Não cria checklist**.
2. **Não chama `setIncluirCheckList`**.
3. Usa `getTabela` para apoio: FILIAIS, PERFIL_SEGURANCA, PRODUTOS e ERROS_WEBSERVICE.
4. Usa `getHistoricoTestes` para descobrir `CodCheckList` já existente por placa.
5. Usa `getGerarResultadoCheckList` para consultar resultado oficial.
6. Envia Produtos automaticamente porque a Raster em produção retornou erro 105 quando Produtos estava vazio.
7. Respeita intervalo mínimo de 12 segundos entre chamadas do `getGerarResultadoCheckList` para evitar erro 102.
8. HTTP 500 da Raster não trava o app: grava no raw e segue na próxima rodada.
9. Resultado só é contado como válido se vier `DataGeracao` e `DataExpiracao`.

## Configurações importantes no .env

```env
RASTER_COD_FILIAL="6278"
RASTER_COD_PERFIL_SEGURANCA="14341"
RASTER_PRODUTOS='[{"CodProduto":2134,"Valor":1}]'
RASTER_DELAY_CHECKLIST_SECONDS="12"
RASTER_TIMEOUT_SECONDS="20"
RASTER_MAX_CHECKLIST_POR_RODADA="1"
```

Perfil usado: `14341 — DDR SHOPEE - LINE HAUL OWN FLEET - FROTA - ESSOR`.
Produto vinculado: `2134 — 00 PRODUTOS DIVERSOS`.

## Como usar

1. Rodar o app.
2. Aba **Raster**.
3. Clique em **getTabela apoio**.
4. Clique em **Consultar checklist automático** ou **Consultar resultados existentes em lote**.
5. O app consulta uma rodada segura por vez.

Se quiser avançar mais registros, clique novamente ou aumente `RASTER_MAX_CHECKLIST_POR_RODADA` para 2 ou 3, mantendo o delay de 12 segundos.
