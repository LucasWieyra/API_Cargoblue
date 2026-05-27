# Versão final - Raster + Omnilink/WSTT

Esta versão consolida os ajustes solicitados:

- Execução automática integrada Raster + Omnilink/WSTT.
- Checklist Raster em modo SOMENTE CONSULTA.
- Não chama `setIncluirCheckList`.
- Não cria novos checklists.
- Consulta `getHistoricoTestes` para localizar checklists existentes.
- Consulta `getGerarResultadoCheckList` para obter resultado/status.
- Usa CodFilial 6278, CodPerfilSeguranca 14341 e Produto 2134 como padrão.
- Respeita intervalo de segurança para evitar erro 102 da Raster.
- Mostra todos os status do checklist: ST, AI, AE, CV, ET, FI e CA.
- A tabela principal de checklist não mostra `raw`, `CodErro`, `MsgErro`, payload nem erro técnico.
- O dashboard converte distância da Omnilink de metros para KM apenas na visualização.

Para rodar:

```bat
py -m pip install -r requirements.txt
py -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

