# ParserVeraGrid — `pwf2raw`

Conversor de arquivos do **ANAREDE** (`.pwf`, CEPEL) para **PSS/E RAW rev 33**,
para abrir casos de fluxo de potência do Sistema Interligado Nacional no
[VeraGrid](https://github.com/SanPen/VeraGrid)/GridCal — ou em qualquer
ferramenta que leia RAW.

Inclui a montagem de casos operativos a partir de decks **DESSEM** do ONS:
rede do `.pwf` + despacho dos relatórios `pdo_*.dat`.

## Por que RAW, e não o formato nativo do VeraGrid

O `.gridcal` é um zip de CSVs com o modelo interno de objetos (UUIDs, tabelas
relacionais) — caro de escrever e amarrado a uma versão do formato. O RAW é
texto por registro, padrão de fato da indústria, e o VeraGrid tem importador
nativo maduro. Gerar um RAW correto e deixar o importador fazer o resto
desacopla este projeto das mudanças internas do VeraGrid.

## Instalação

```bash
git clone https://github.com/sinvaldomoreno/ParserVeraGrid.git
cd ParserVeraGrid
pip install -e ".[dev]"          # parser + testes
pip install -e ".[validate]"     # + VeraGridEngine, para validar
```

Requer Python 3.10+. O parser não tem dependências; o VeraGrid só é
necessário para validação.

## Uso

```bash
# caso de fluxo de potência resolvido (ex.: casos de referência da EPE)
pwf2raw caso.pwf caso.raw

# com diagnóstico estrutural (ilhas, balanço, elos, ramos de impedância nula)
pwf2raw caso.pwf caso.raw --check

# deck DESSEM do ONS: rede + despacho do período que casa com a carga
pwf2raw media.pwf media.raw --dessem-deck ./DS_ONS_092026_RV2D17 \
        --dc-status on --curtail
```

| Opção | Efeito |
|---|---|
| `--check` | Diagnóstico estrutural antes de gravar |
| `--dc-status file\|on\|off` | Estado dos elos CC: respeita o DELO, força ligados ou bloqueados |
| `--dessem-deck DIR` | Injeta o despacho do DESSEM (térmica, renovável, hidráulica, elos CC) |
| `--dessem-period N\|auto` | Período do DESSEM (1–48); `auto` escolhe pelo balanço com a carga |
| `--curtail` | Corta a renovável excedente (o DESSEM não contém o curtailment do tempo real) |
| `--no-ltc` | Grava todos os transformadores com tap fixo |
| `--merge-z TOL` | Funde nós ligados por ramos com impedância < TOL pu (**não é padrão**, ver abaixo) |
| `--x-floor X` | Piso de reatância em ramos de impedância desprezível (**modifica a rede**) |
| `-v` | Todos os avisos |

Uso programático:

```python
from pwf2raw import PwfReader, write_raw
from pwf2raw.dessem import apply_dispatch, best_period

net = PwfReader("media.pwf", dc_status="on").parse()
load = sum(l.p for l in net.loads if l.in_service)
period, _ = best_period("DS_ONS_092026_RV2D17", load)
print(apply_dispatch(net, "DS_ONS_092026_RV2D17", period=period,
                     pwf_path="media.pwf", curtail=True).describe())
write_raw(net, "media.raw")
```

## O que é convertido

| Seção ANAREDE | Conteúdo | Destino no RAW |
|---|---|---|
| `DBAR` | barras, carga, geração, shunt de barra | Bus, Load, Generator, Fixed Shunt |
| `DGBT` | grupos de tensão base | tensão base das barras |
| `DGER` | limites de geração ativa | Pmin/Pmax |
| `DLIN` | linhas e transformadores, incluindo LTC | Branch, Transformer (com controle de tap) |
| `DSHL` | shunts de linha | Fixed Shunt em cada extremidade |
| `DBSH` | bancos chaveáveis | Switched Shunt |
| `DCER` | compensadores estáticos | Switched Shunt contínuo |
| `DCSC` | compensação série controlável | Branch de reatância fixa |
| `DELO` `DCBA` `DCLI` `DCNV` `DCCV` | rede CC (LCC) | dois geradores acoplados por elo |
| `DVSC` | elos VSC | seção VSC do RAW |
| `DARE` | áreas | Area |
| `DUSI` | usinas (código ↔ barra) | usado no casamento do despacho DESSEM |

Informativas, reconhecidas e reportadas: `DCTR`, `DGLT`, `DAGR`, `DCTE`,
`DCAR`, `DCMT`, `DOPC`, `DTPF`. Qualquer seção `Dxxx` desconhecida gera
aviso — nunca é descartada em silêncio.

Três decisões de projeto que protegem contra erro silencioso:

- **Colunas derivadas do cabeçalho** de cada bloco, porque o layout do PWF
  varia entre versões do ANAREDE.
- **Detecção de desalinhamento**: campo contendo só `-` ou `.` indica número
  partido entre dois campos, e gera aviso.
- **Relatórios que dizem o que faltou**, em vez de produzir um caso que
  parece completo.

## Casos de referência do PDE (EPE)

A validação principal usa a base de casos de referência para estudos de
fluxo de potência que a EPE disponibiliza com o Plano Decenal de Expansão,
descrita na nota informativa *Base de Dados para Estudos de Fluxo de
Potência — PDE 2034* (EPE, novembro de 2024). São casos **resolvidos**: os
campos de tensão e ângulo do `DBAR` guardam a solução do ANAREDE, o que
permite validar a conversão contra ela.

### O que vem no pacote

| Arquivo | Conteúdo | Uso pelo parser |
|---|---|---|
| `pwfs.zip` | **96 `.pwf`**: um por ano (2029–2040) e patamar (8) | convertidos e validados |
| `*.SAV` | 8 casos salvos em formato binário do ANAREDE | não usados |
| `Lista_de_Usinas.xlsx` | lista de usinas para redespacho dos casos | não usada |

Os casos são gravados pelo ANAREDE 12.03.04 e têm de 12.969 (2029) a 13.323
barras (2040). Patamares, pelo número no nome do arquivo:

| Nº | Patamar | Nº | Patamar |
|---|---|---|---|
| 1 | Máxima Diurna Seco | 5 | Mínima Noturna Seco |
| 2 | Máxima Diurna Úmido | 6 | Mínima Noturna Úmido |
| 3 | Máxima Noturna Seco | 7 | Máxima Coincidente |
| 4 | Máxima Noturna Úmido | 8 | Mínima Diurna Coincidente |

### Características que importam para a conversão

Segundo a nota da EPE, a carga é **bruta** (sem descontar a geração
distribuída fotovoltaica), há um único cenário de despacho (Norte e
Nordeste exportadores), e as tensões foram ajustadas por fluxo de potência
ótimo, com **compensadores síncronos fictícios** onde o controle foi
inviável. Nos decks isso aparece assim:

- Os compensadores fictícios são listados nominalmente, com o número da
  barra, no bloco de comentários `DCMT`.
- A geração indicativa (UFV e EOL) fica concentrada na área 999.
- Há **4 barras de referência**, uma por ilha CA: o sistema principal e os
  subsistemas ligados ao restante só por corrente contínua (Itaipu 50 Hz,
  Madeira e a barra fictícia da Alumar).
- São 17 a 19 elos CC; os elos VSC (Angical–Itaporã) aparecem em anos
  posteriores do horizonte.
- O grupo de tensão `Z` do `DGBT` vale 999 kV: é sentinela para barras
  internas, não tensão real.

Vários tratamentos do parser foram motivados por esses casos: os shunts de
linha (`DSHL`: 604 a 663 shunts de extremidade por caso), os elos VSC, o setpoint dos elos pelo
`DCCV` (Foz–Ibiúna: 2.769 MW convertidos contra 2.777 MW de excedente na
ilha de Itaipu 50 Hz) e o transformador ideal Foz 500 kV → Itaipu-Foz 525 kV
(X = 0,001%, tap 1,05), que concentrava o resíduo em parte dos casos.

### Como usar

```bash
unzip Casos_de_Referência.zip && unzip pwfs.zip -d pwfs
pwf2raw "pwfs/2035_7. PD 2035 - MÁXIMA COINCIDENTE.PWF" caso.raw --check
python examples/validate_reference_cases.py pwfs 8       # amostra de 8
python examples/run_validation.py pwfs resultados.jsonl  # todos, retomável
```

Dependendo do descompactador, os acentos dos nomes podem aparecer escapados
(`M#U00c1XIMA`); o parser não depende do nome do arquivo.

### Resultados

- **96/96** arquivos convertidos sem erro.
- Onde o Newton-Raphson converge: **ΔV mediano de 0,0005 pu**, 96–97% das
  barras dentro de 0,02 pu e ângulo mediano de **~0,3°** em relação à
  solução do ANAREDE.

Qualidade por patamar no ano de 2035, medida na iteração do Newton-Raphson
puro, inclusive onde ele não acusa convergência:

| Patamar | ΔV mediano (pu) | Barras a até 0,02 pu | Δ ângulo mediano | Barras que não assentam |
|---|---|---|---|---|
| 1 | 0,0005 | 94,7% | 3,76° | 9 |
| 2 | 0,0005 | 94,9% | 1,70° | 5 |
| 3 | 0,0049 | 86,5% | 20,58° | 60 |
| 4 | 0,0050 | 87,4% | 3,99° | 48 |
| 5 | 0,0035 | 90,7% | 2,17° | 51 |
| 6 | 0,0038 | 90,7% | 2,39° | 17 |
| 7 | 0,0005 | 95,2% | 1,07° | 8 |
| 8 | 0,0006 | 94,3% | 4,60° | 8 |

O patamar 3 destoa (ângulo mediano de 20,6°); a causa não foi identificada.

**Convergência não é a métrica de correção.** De 2029 a 2039 (88 casos; os
8 de 2040 não foram rodados na validação completa), 24 acusam convergência:
os patamares 5 e 6 em todos os anos, os 1 e 2 até 2032, e os 3, 4, 7 e 8 em
nenhum. O flag cai quando um punhado de barras não assenta, mesmo com as
outras ~12.800 corretas — no caso 2035_7, o NR não converge e reproduz o
ANAREDE com ΔV mediano de 0,0005 pu, enquanto dois outros métodos
"convergem" para uma solução espúria com 33° de erro de ângulo. A queda de
convergência ao longo do horizonte acompanha o crescimento da carga e
atinge primeiro os patamares mais carregados, o que aponta para condição de
operação e não para erro de leitura.

O mapeamento de colunas de DCNV, DCCV, DCER e DCSC foi validado também de
forma independente contra a especificação do [PWF.jl](https://github.com/LAMPSPUC/PWF.jl).

## Limitações conhecidas

- **Templates DESSEM não convergem** no VeraGrid. O `.pwf` do DESSEM é
  entrada de rede, não caso resolvido: tensões planas em 83% das barras, 2,5×
  mais reatores ligados que num caso resolvido, setpoints de elos de
  placeholder. O parser monta rede + despacho corretamente (balanço +2,8% na
  média, +3,5% na pesada), mas resolver o template exige o ferramental de
  controle do ANAREDE. É problema de solver, não de conversão.
- **Fusão de nós não é padrão.** Resolve o mal-condicionamento dos jumpers de
  impedância nula, mas numa amostra piorou a convergência (2/6 → 0/6).
- **Elos CC com fluxo reverso relevante** (< −50 MW) mantêm o setpoint do
  template, com aviso: o modelo de geradores acoplados não representa
  inversão de sentido.
- **Patamar leve do DESSEM**: com curtailment, o balanço não discrimina o
  período. Informe `--dessem-period` explicitamente.
- Registros de três enrolamentos são convertidos como três transformadores
  em estrela, como o ANAREDE os representa.

Os detalhes de cada decisão, armadilha e medição estão em
[`docs/FORMAT_NOTES.md`](docs/FORMAT_NOTES.md).

## Estrutura

```
src/pwf2raw/
├── sections.py     especificação de colunas, layout pelo cabeçalho, leitura numérica
├── model.py        modelo intermediário (Bus, Branch, Transformer2W, DcLink, ...)
├── pwf_reader.py   .pwf -> Network
├── raw_writer.py   Network -> RAW rev 33
├── dessem.py       despacho do DESSEM (pdo_*.dat) -> Network
├── zbranch.py      fusão de nós de impedância desprezível
├── diagnostics.py  ilhas, balanço, elos, ramos de impedância nula
└── cli.py          comando `pwf2raw`
tests/              32 testes, fixtures sintéticas
examples/           validação contra casos de referência
docs/FORMAT_NOTES.md
```

O modelo intermediário `Network` desacopla leitura e escrita: um exportador
para outro formato só precisa consumir `Network`.

## Dados

Nenhum deck real é versionado — os decks do ONS e da EPE são grandes e têm
fontes próprias. As fixtures em `tests/data/` são sintéticas, montadas a
partir das especificações de coluna.

## Créditos

- [PWF.jl](https://github.com/LAMPSPUC/PWF.jl) (LAMPSPUC/PUC-Rio): validação
  independente de colunas, setpoint dos elos pelo DCCV e modelo de geradores
  acoplados.
- [pyxparser](https://github.com/mcllerena/pyxparser): segunda fonte na
  validação inicial.
- Casos de referência: EPE (base de dados para estudos de fluxo de potência do PDE). Decks DESSEM: ONS.

## Licença

MIT — ver [`LICENSE`](LICENSE).
