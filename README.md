# pwf2raw

Conversor de arquivos **ANAREDE (.pwf)** para **PSS/E RAW (rev 33)**,
para permitir abrir decks de fluxo de potência do ANAREDE diretamente
no **VeraGrid** (ou GridCal, pandapower, PowerWorld, ou qualquer outra
ferramenta com leitor de RAW).

## Por que RAW e não `.gridcal`?

O formato `.gridcal` é um zip de CSVs com o modelo de objetos interno
do GridCal/VeraGrid (UUIDs, tabelas relacionais de área/zona/país
etc.) — e amarra o parser à versão interna daquele formato. O RAW, por outro lado:

- é um formato texto por registro, orientado a colunas fixas — mais
  parecido com o próprio PWF (formato do ANAREDE), o que simplifica o mapeamento
  campo a campo;
- é um padrão de fato da indústria (PSS/E), com leitores maduros em
  praticamente todas as ferramentas de análise de redes, incluindo um
  importador nativo e bem mantido no VeraGrid/GridCal;
- desacopla este projeto de mudanças internas no formato `.gridcal`.

Ou seja: em vez de escrever *e manter* um exportador para o formato
interno do VeraGrid, o projeto buscou gerar um RAW correto e deixar o importador
RAW do próprio VeraGrid fazer o trabalho pesado.

## Instalação

```bash
git clone https://github.com/seu-usuario/seu-repositorio.git
cd pwf2raw
pip install -e ".[dev]"
```

Para rodar os testes de validação end-to-end com o próprio VeraGrid
(opcional, pesado):

```bash
pip install -e ".[validate]"
```

## Uso

Via linha de comando:

```bash
pwf2raw entrada.pwf saida.raw
pwf2raw entrada.pwf saida.raw -v   # avisos detalhados
```

Ou programaticamente:

```python
from pwf2raw import PwfReader, write_raw

net = PwfReader("entrada.pwf").parse()
print(net.summary())
for w in net.warnings:
    print("aviso:", w)

write_raw(net, "saida.raw")
```

Veja também `examples/convert_example.py`.

## Arquitetura

```
src/pwf2raw/
├── sections.py    # especificação de colunas do PWF (fixed-width) + parsing numérico
├── model.py        # modelo intermediário (Bus, Load, Shunt, Generator, Branch, Transformer2W)
├── pwf_reader.py    # .pwf -> Network
├── raw_writer.py    # Network -> .raw (PSS/E rev 33)
└── cli.py           # `pwf2raw` entry point
```

O modelo intermediário (`Network`) é o desacoplamento chave: qualquer
formato de saída futuro (ex. um exportador `.gridcal` nativo, ou
`.m`/MATPOWER) só precisa consumir `Network`, sem tocar no parser do
PWF.

## Status / cobertura atual (v0.1)

Implementado: `DBAR` (barras, cargas e shunt fixo embutidos), `DGBT`
(base de tensão), `DGER` (limites de geração ativa), `DLIN` (linhas e
transformadores de 2 enrolamentos).

**Testado contra o deck completo do SIN (ONS, patamar de carga
média — ~41 mil linhas de arquivo):**

```
12.901 barras, 2.863 cargas, 1.165 geradores,
9.452 linhas, 7.367 transformadores 2 enrolamentos
```

O `.raw` resultante **abre corretamente no VeraGrid**, com todas as
contagens de elementos batendo.

### Limitação conhecida

Um fluxo de potência no deck completo do ONS **não converge** com a
cobertura atual. O suspeito principal são as ~10 seções ainda não
implementadas (ver `docs/FORMAT_NOTES.md`) — em especial os elos de
corrente contínua (`DELO`/`DCNV`/`DCCV`/`DCLI`/`DCBA`), cuja ausência
provavelmente deixa subsistemas do SIN conectados apenas via HVDC
eletricamente ilhados no RAW gerado. Isso **não invalida o parser em
si** (a topologia CA extraída bate 1:1 com o arquivo fonte), mas é o
próximo passo antes de usar isso para estudos reais de fluxo de
potência.

No exemplo sintético pequeno (`tests/data/mini_4bus.pwf`, 4 barras) o
fluxo de potência **converge normalmente** — ver
`tests/test_raw_writer.py::test_write_raw_opens_in_veragrid`.

### Roadmap (por prioridade - sugerida para quem quiser contribuir)

1. `DELO`/`DCNV`/`DCCV`/`DCLI`/`DCBA` (HVDC) — provável causa da
   não-convergência no deck completo.
2. `DBSH` (shunt chaveável) → *Switched Shunt* do RAW.
3. `DCTR` (controle de tap/LTC) — hoje o tap é importado como fixo.
4. `DCER`/`DCSC` (compensadores síncronos/estáticos, TCSC).
5. `DARE`/`DAGR`/`DGLT`/`DUSI`/`DCTE`/`DCAR` — dados complementares.

Ver `docs/FORMAT_NOTES.md` para o detalhamento de colunas de cada
seção, casas decimais implícitas e as pegadinhas de parsing já
resolvidas (documentadas para quem for estender o parser).

## Testes

```bash
pytest -v
```

13 testes: parsing de colunas contra linhas reais extraídas do deck
ONS (regressão), leitura completa do fixture sintético de 4 barras, e
escrita do RAW com round-trip de validação no VeraGrid (pulado
automaticamente se `VeraGridEngine` não estiver instalado).

Os dados completos do ONS (`media.pwf`, ~3.5 MB) **não são versionados**
no repositório — apenas o fixture sintético pequeno em `tests/data/`.

## Créditos

O mapeamento de colunas foi validado empiricamente linha a linha
contra decks reais, com o projeto open source
[`pyxparser`](https://github.com/mcllerena/pyxparser) (BSD-3-Clause)
servindo como segunda fonte de validação cruzada para `DBAR`, `DLIN` e
`DGER`.

## Licença

MIT — ver `LICENSE`.
