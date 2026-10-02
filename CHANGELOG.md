# Changelog

## 1.0.1

### Corrigido
- **Identificadores duplicados no RAW** (`Local ID duplicate` ao abrir no
  VeraGrid): geradores acoplados dos elos CC, shunts de linha do `DSHL` e
  bancos chaveáveis na mesma barra. IDs passam a ser únicos por barra e os
  bancos da mesma barra são agregados num registro.

## 1.0.0

Primeira versão completa. Substitui a 0.1.0 publicada.

### Adicionado
- Rede CC completa (`DELO`, `DCBA`, `DCLI`, `DCNV`, `DCCV`) modelada como
  geradores acoplados; elos VSC (`DVSC`).
- `DSHL`, `DBSH`, `DCER`, `DCSC`, `DARE`; controle de tap LTC a partir do `DLIN`.
- Layout de colunas derivado do cabeçalho de cada bloco, com detecção de
  desalinhamento entre versões do ANAREDE.
- Módulo `dessem`: despacho térmico, renovável, hidráulico (via `DUSI`) e dos
  elos CC (via `pdo_somflux`), seleção automática de período e curtailment.
- Módulo `zbranch`: fusão de nós de impedância desprezível (opcional).
- Diagnóstico estrutural (`--check`).
- Validação contra casos resolvidos (`examples/`); 32 testes.

### Corrigido (defeitos da 0.1.0)
- **Status de ramo gravado no campo errado do RAW**: todo ramo desligado do
  deck entrava em serviço. Se você usou a 0.1.0, reconverta os casos.
- Setpoint dos elos CC lido do campo `BASE` do `DELO` em vez do `DCCV`.
- Carga, geração e shunt de barras desligadas permaneciam em serviço.
- Transformadores gravados sem dados de controle de tap.
