# Notas técnicas: formato ANAREDE (.pwf), conversão para PSS/E RAW e armadilhas

Este documento registra **como** cada decisão de conversão foi tomada e **por
que**. Quase tudo aqui foi descoberto empiricamente, validando contra decks
reais do ONS e da EPE — e várias seções existem porque uma leitura "óbvia"
se mostrou errada. Quem for estender o parser deve ler as armadilhas antes.

---

## 1. Convenções gerais do PWF

- Formato de **colunas fixas**, não delimitado. Índices 1-based e inclusivos
  nas duas pontas, como no Manual do Usuário do ANAREDE (CEPEL).
- Cada bloco começa com o código de execução (`DBAR`, `DLIN`, ...), seguido
  de uma linha de comentário iniciada por `(` com os rótulos dos campos, dos
  registros, e termina em `99999`.
- Codificação Latin-1 (acentuação em português); terminador CRLF.

### Decimal implícito

Campos numéricos estreitos gravam o número **sem ponto** quando ele não cabe
com o ponto, e a posição decimal passa a ser implícita pela largura:

| Texto | Campo | Valor |
|---|---|---|
| `1001` | tensão do DBAR (col. 25–28, 3 decimais implícitas) | 1,001 pu |
| `-53.` | ângulo do DBAR (tem ponto: leitura direta) | −53,0° |
| `0900` | Vmn do DBSH | 0,900 pu |

A regra em `sections.number`: se o campo contém `.`, leitura direta; senão,
aplica as casas implícitas configuradas para aquele campo.

---

## 2. O layout de colunas não é estável entre versões do ANAREDE

No caso de referência de 107 barras do CEPEL, o campo `(Bc)` do DBAR tem 5
colunas; nos decks do ONS/EPE, 6. Isso desloca em uma coluna **todos** os
campos seguintes. Lido com o layout errado, o reator `-200.` de Araraquara
se parte em `Ql='-'` + `Sh='200.'` e a área sai 110 em vez de 1 — **sem
nenhum erro**, só números errados.

Duas defesas implementadas:

1. **Layout derivado do cabeçalho** (`sections.layout_from_header`). A linha
   de comentário de cada bloco delimita os campos com parênteses:
   `(Num)OETGb(   nome   )Gl( V)( A)( Pg)...`. As colunas são extraídas
   desses parênteses; o layout fixo serve apenas de fallback. Para o DBAR do
   ONS o layout derivado reproduz exatamente o mapeamento validado à mão.
2. **Detecção de desalinhamento** (`sections.alignment_symptoms`). Um campo
   que contém apenas `-`, `+` ou `.` só existe quando um número real ficou
   partido na fronteira entre dois campos. O parser avisa em vez de seguir
   em silêncio.

> Observação: no deck de 107 barras o cabeçalho é idêntico ao do ONS, mas os
> dados estão deslocados. Aí o layout derivado não resolve — e é exatamente
> esse caso que a detecção de desalinhamento sinaliza.

---

## 3. Armadilhas por seção

### DBAR — barras
- Carga, geração e shunt de uma **barra desligada** também ficam fora de
  serviço. Sem propagar isso, o RAW recebia injeções "fantasmas": no deck
  EPE 2035 eram **~8 GW de geração inexistente**.
- Tipos ANAREDE → PSS/E: 0 → PQ (1), 1 → PV (2), 2 → referência (3).

### DLIN — linhas e transformadores
- **Barra "para" × circuito.** A linha `   38       17954 ...` *parece* ter
  barra de destino 17954. Errado: a barra ocupa as colunas 11–15 e o circuito
  16–17. Quando a barra tem 3 dígitos (179) e o circuito 2 (54), o texto
  colado parece um número só. Confirmado por registros onde os campos vêm
  separados (`   60     43810 2`).
- **Transformador × linha.** O DLIN não separa os dois. É transformador se o
  campo tap está preenchido ou se as barras têm tensão base diferente.
- **LTC.** Transformador com faixa de tap válida (`Tmn < Tmx`) é tratado como
  LTC: barra controlada, faixa e número de posições vão para o RAW (2.311 de
  7.414 no deck DESSEM de set/2026). Barra controlada inexistente cai para a
  barra "para". A opção `--no-ltc` grava tudo com tap fixo.
- **Três enrolamentos** vêm como três transformadores ligados a um ponto
  estrela fictício (nome terminado em `000`, grupo sentinela de tensão). Um
  dos ramos pode ter reatância negativa — é o equivalente estrela, não erro.

### DGBT — grupos de base de tensão
Formato solto (separado por espaço). Grupos com valores como `990`, `991`,
`992` e `999` kV são **sentinelas** para barras internas (terminais de
máquina, pontos estrela), não tensões reais. Grupo ausente → 1,0 kV.

### DSHL — shunts de linha
O RAW rev 33 não tem shunt de linha. Cada extremidade vira um shunt fixo na
barra correspondente, preservando o balanço de reativo. Colunas derivadas do
cabeçalho `(De ) O  (Pa )Nc (Shde)(Shpa) ED EP`.

### DBSH — bancos chaveáveis
Estrutura em dois níveis: uma linha de banco e, depois de `(G  O E ...`,
linhas de grupo até `FBAN`. `Vmn`/`Vmx` têm decimal implícito (`0900` =
0,900 pu). Faixas largas como 0,4–1,9 pu são dado real (banco sem controle
efetivo), não erro de leitura.

### DCER e DCSC
Colunas validadas campo a campo contra os registros e, de forma
independente, contra a especificação do PWF.jl (ver §9). Reconstruí-las "de
memória" produziu um erro real: `Qg` lia `'.-100.'` e `Qn` lia `150.`.

### DUSI — usinas
O código da usina (col. 73–76) é o mesmo `USIH` do DESSEM. Usado para
casar a geração hidráulica com as barras (§7).

---

## 4. Rede de corrente contínua

### O ponto de operação vem do DCCV, não do DELO
O campo 14–18 do DELO é a **base** do elo, não a potência de operação. O
ponto de operação é o `SPECIFIED VALUE` do DCCV (col. 12–16) do retificador,
quando o tipo de controle é `P`. Confirmação no deck EPE 2035: Foz–Ibiúna
passa de 4 × 1.566 = 6.264 MW (nominal) para 4 × 692,3 = 2.769 MW, contra
2.777 MW de excedente da ilha de Itaipu 50 Hz.

### Modelo: dois geradores acoplados
Cada elo vira dois geradores com P especificado e Q livre — retificador
consumindo, inversor injetando P menos as perdas (`I = P/Vcc`,
`perda = I²R`). É o modelo do PWF.jl/PowerModels. Gravar o bloco
two-terminal DC do RAW (opção `dc_model="raw"`) depende do modelo HVDC do
leitor e, no VeraGrid, se mostrou pior. Somado à correção do setpoint, isso
levou a amostra EPE de 3/8 para 6/8 casos convergindo e o erro mediano de
ângulo de ~5° para ~0,35°.

### Elos CC não unem ilhas CA
Um elo é injeção de potência nas duas pontas, não caminho de corrente
alternada. Subsistemas ligados só por CC (Itaipu 50 Hz, Madeira, Alumar) são
**ilhas CA distintas**, e um deck consistente fornece uma barra de referência
para cada uma — por isso o caso EPE 2035 tem 4 slacks. A primeira versão do
diagnóstico fundia essas ilhas e interpretava as slacks como problema.

### Nem todo elo é HVDC de transmissão: o caso Alumar
Nos decks do ONS, a carga das salas de cubas da Alumar é modelada por um
**artifício**: retificador na barra CA real de São Luís, e inversor
injetando numa **barra swing fictícia e isolada** que representa a
contra-tensão das cubas. Isso representa corretamente o consumo de reativo
dos conversores a tiristor e evita divergência. Consequências: uma barra
swing isolada sem ramo CA é parte do modelo, não erro; e conversores com
`Ebas` de 0,7–0,9 kV e faixa de tap ampla são fisicamente corretos numa
linha de cubas — o writer não pode rejeitá-los.

### Estado do elo
`L`/`D` no campo estado do DELO. `--dc-status on|off` força o estado.

---

## 5. Escrita do PSS/E RAW rev 33

- **Ramos.** A ordem é `... GI, BI, GJ, BJ, ST, MET, LEN ...`. A v0.1
  gravava `1` fixo em `ST` e o status real em `MET`, colocando em serviço
  **todo** ramo desligado do deck (1.003 no caso EPE 2029). Há teste de
  regressão.
- **Two-terminal DC**: registro 1 com 12 campos, registros do conversor com
  17 (`IP NB ANMX ANMN RC XC EBAS TR TAP TMX TMN STP IC IF IT ID XCAP`).
- **Nome de elo** tem 12 caracteres no RAW; nomes do ANAREDE têm até 20 e
  colidiam (`ELOCC-FOZ-IB` para os 4 polos). O número do elo vira sufixo.
- **Transformador**, registro 3: `COD1 CONT1 RMA1 RMI1 VMA1 VMI1 NTP1`
  carregam o controle de LTC.

---

## 6. Ramos de impedância desprezível

Disjuntores e jumpers vêm como ramos com r, x ≈ 1e-5 pu. É fiel ao
equipamento, mas destrói o condicionamento: seis jumpers com
`r = x = 1e-5` numa barra dão `Ydiag ≈ 3e5` pu.

`zbranch.merge_zero_impedance` funde os nós ligados por esses ramos
(preservando slack e PV como representantes) e `floor_residual_impedance`
impõe reatância mínima ao que não pode ser fundido — transformadores com
tap ≠ 1, onde a relação de tensão é real. No caso EPE 2032_3, o
transformador Foz 500 kV → Itaipu-Foz 525 kV (X = 0,001%, tap 1,05) sozinho
respondia pelo resíduo dominante.

**A fusão não é padrão.** Numa amostra de 6 casos de patamar 1 ela piorou o
resultado (2/6 convergindo sem fusão, 0/6 com fusão a 1e-3): resolve o
mal-condicionamento local, mas tira casos da bacia de convergência. Fica
disponível como `--merge-z`, para uso caso a caso e medindo.

---

## 7. Decks DESSEM do ONS

### O .pwf é template de rede, não caso resolvido
Os `.pwf` de um deck DESSEM são a **entrada** de rede do modelo; o despacho
é a **saída**, nos relatórios `pdo_*.dat`. Medido no deck DS_ONS_092026_RV2D17:

| Aspecto | DESSEM media.pwf | EPE 2029_1 (resolvido) |
|---|---|---|
| Geração ativa no DBAR | 0 em todas as barras | despacho completo |
| Barras com Vm = 1,000 exato | 83,0% | 5,4% |
| Reatores chaveáveis ligados no estado inicial | −102.764 Mvar | −41.677 Mvar |
| Setpoint dos elos (DCCV) | placeholder | despacho |
| Estado dos elos | todos `D` | em serviço |

### Montagem do despacho (`dessem.py`)

| Fonte | Chave de ligação à rede | Cobertura no deck de set/2026 |
|---|---|---|
| `pdo_oper_term.dat` | coluna `NumBarra` | 122 barras |
| `pdo_eolica.dat` (eólica, FV, PCH, MMGD) | coluna `Barra` | 3.110 barras |
| `pdo_hidr.dat` | código da usina → bloco `DUSI` do .pwf | 155/169 usinas, 100% da geração |
| `pdo_somflux.dat` (elos CC) | restrição de barra única no inversor | Foz, Madeira, Xingu, BtB |

Armadilhas:
- **Casar por código, não por nome.** O DUSI grava `AGUA VERMELH`, o
  `pdo_hidr` grava `A. VERMELHA`.
- **Linhas de total.** O `pdo_hidr` fecha cada usina com `CONJ=99, Unid=99`.
  Somá-las contou tudo em dobro: Itaipu saiu com 24.608 MW (o dobro dos
  12.304 reais).
- **Usinas com várias barras.** Se o número de barras no DUSI bate com o de
  conjuntos, conjunto → barra na ordem (Itaipu: conj. 1 → 50 Hz, conj. 2 →
  60 Hz); senão, rateio pelo número de unidades.
- **Rótulo de patamar não identifica um instante.** `MEDIA` aparece de
  madrugada (~81 GW, 31 GW de renovável) e ao meio-dia (~106–110 GW, 71–75
  GW com solar). O `media.pwf` casa com o meio-dia. `best_period` escolhe,
  entre os 48 períodos do dia, o de balanço mais próximo; períodos acima de
  48 cobrem o horizonte seguinte em blocos e são excluídos (o 51 chegou a ser
  escolhido prevendo +3,0% e resultando em −3,9%).
- **Carga bruta e curtailment.** A carga do .pwf é bruta; as renováveis são
  abatidas para formar a líquida. E o resultado inicial do DESSEM **não
  contém o curtailment do tempo real**, que é elevado — geração acima da
  carga é esperada. `--curtail` corta a renovável proporcionalmente até
  carga + 3%, sem tocar hidráulica e térmica.
- **Elos CC pelas inequações de controle.** O `pdo_somflux.dat` contém as
  restrições de somatório de fluxo. Verificação interna no período 20:
  `& BIPS` soma os quatro inversores e bate exato com os valores individuais
  (2.676 + 1.203,041 − 1,6 + 197,9 = 4.075,341). Fluxo pequeno (|F| < 50 MW)
  é elo parado, não reversão.

### Por que o caso DESSEM montado não converge
Testadas uma a uma, **nenhuma** correção isolada resolve: setpoints dos
elos, renováveis como PV ou PQ, carga reduzida a 20%, controles de reativo
e tap, reatores reduzidos a 40%. Cada correção de estado move o resultado na
direção certa.

Os testes de controle:
- **Rede em vazio:** o caso EPE fica saudável (Vm máx 1,098 pu); o DESSEM
  vai a 10,8 pu.
- **Achatar o perfil de um caso EPE** o degrada (erro 3e-07 → 2,7e-03), mas
  não reproduz o colapso do DESSEM.

Leitura: o parser reproduz o ANAREDE em casos resolvidos; o `.pwf` do DESSEM
traz o estado de um template, do qual o ANAREDE sai com seu ferramental de
controle a partir de um ponto que ele mesmo constrói. Resolver templates do
DESSEM é problema de solver, não de conversão. Não foi provado que não
exista também algum defeito de conversão específico — mas não há evidência
dele.

---

## 8. Validação: o que medir e o que não medir

O método: um .pwf salvo pelo ANAREDE guarda, nos campos V e A do DBAR, a
solução daquele caso. Convertemos, resolvemos no VeraGrid e comparamos.
Ângulos são comparados a menos de um offset constante (a referência pode
ser outra), por isso a mediana é removida.

Três armadilhas de medição que custaram várias rodadas de investigação:

1. **A métrica de erro do VeraGrid é norma infinita, em pu.** É o mismatch
   da **pior barra**, não uma soma. Um "erro de 5.028" não são 5.028 MW
   espalhados; é uma barra com ~500 MVA.
2. **`retry_with_other_methods=True` devolve um sentinela quando todos os
   métodos falham.** NR e FASTDECOUPLED reportavam exatamente o mesmo 5.028
   em casos diferentes. Nesse caminho, nem o erro nem a tensão são
   utilizáveis.
3. **Convergência não é correção.** No caso EPE 2035_7, o NR não converge
   e reproduz o ANAREDE com ΔV mediano de 0,0005 pu; IWAMOTO e
   FASTDECOUPLED "convergem" (erro 1e-8) para uma solução espúria com 33° de
   erro de ângulo. Basta um punhado de barras não assentar para o flag cair.

Uma quarta, de diagnóstico: `compile_numerical_circuit_at` monta a Ybus
**incluindo ramos fora de serviço**. Resíduos calculados com ela apontaram
para uma barra que estava isolada.

---

## 9. Referências cruzadas

- **PWF.jl** (LAMPSPUC/PUC-Rio), parser do PWF para Julia/PowerModels. Sua
  especificação de colunas valida de forma independente as deste projeto
  para DCNV, DCCV, DCER e DCSC, e dela vêm o setpoint pelo DCCV e o modelo
  de geradores acoplados. Validado pelos autores até 500 barras; não tem
  tratamento de impedância nula.
- **pyxparser** (mcllerena), mapeamento declarativo em JSON; usado como
  segunda fonte na validação inicial de DBAR, DLIN e DGER.
