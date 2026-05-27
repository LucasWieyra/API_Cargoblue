# Checklist Raster — todos os status

Esta versão mantém a regra principal: o app **não cria checklist** e **não chama `setIncluirCheckList`**.

Fluxo usado:

1. `getTabela` para apoio: FILIAIS, PERFIL_SEGURANCA e PRODUTOS.
2. `getHistoricoTestes` para localizar CodCheckList existentes por placa.
3. `getGerarResultadoCheckList` para consultar o resultado/status oficial.

A tela agora mostra todos os status retornados pela Raster:

- ST = Sem teste
- AI = Aguardando início
- AE = Aguardando espelhamento
- CV = Configurando veículo
- ET = Teste em execução
- FI = Finalizado
- CA = Cancelado

A tabela operacional não mostra `raw`, `CodErro`, `MsgErro` ou erro técnico. Esses campos ficam apenas no banco/log para diagnóstico.

`DataGeracao` e `DataExpiracao` aparecem quando a Raster devolver esses campos, normalmente no status FI.
