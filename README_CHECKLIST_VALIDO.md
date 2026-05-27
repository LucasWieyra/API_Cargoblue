# Checklist Raster — somente consulta, sem criação

Esta versão não chama `setIncluirCheckList`.

Fluxo usado:

1. `getTabela` para FILIAIS, PERFIL_SEGURANCA, PRODUTOS e ERROS_WEBSERVICE.
2. `getHistoricoTestes` por placa para descobrir checklists existentes.
3. `getGerarResultadoCheckList` usando CodCheckList + CodFilial + CodPerfilSeguranca + Produtos.
4. Resultado válido somente quando `DataGeracao` e `DataExpiracao` vêm preenchidas.

Defaults colocados no `.env`:

```env
RASTER_COD_FILIAL="6278"
RASTER_COD_PERFIL_SEGURANCA="14341"
RASTER_PRODUTOS='[{"CodProduto":2134,"Valor":1}]'
RASTER_VALOR_PRODUTO="1"
```

Perfil 14341: DDR SHOPEE - LINE HAUL OWN FLEET - FROTA - ESSOR.
Produto 2134: 00 - PRODUTOS DIVERSOS.

Se a Raster retornar `Status` diferente de `FI`, ou sem `DataGeracao`/`DataExpiracao`, o registro fica salvo no raw para diagnóstico, mas não entra no contador de resultados válidos.
