# Central Raster + Omnilink/WSTT

Projeto Streamlit para sincronizar e analisar as APIs Raster e Omnilink/WSTT com Supabase.

## Importante sobre Supabase

A tabela `public.raster_checklist_resultado` já pode existir no seu Supabase. Se ela já existe, não precisa recriar nem executar o SQL dessa tabela novamente.

O app apenas lê e grava nela usando `upsert` pela chave `cod_resultado`.

## Rodar no Windows

```bat
py -m pip install -r requirements.txt
py -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

## Terminal do sistema

A página `Terminal` mostra os logs gravados na tabela `integracao_execucoes` e ajuda a acompanhar as rotinas executadas.

## Checklist Raster

A aba Raster possui a tabela `Resultado checklist`, que usa a estrutura existente:

- cod_resultado
- cod_checklist
- veiculo
- cod_filial
- cod_perfil_seguranca
- status
- resultado
- apto
- data_geracao
- data_expiracao
- url_documento
- produtos
- raw
- synced_at
