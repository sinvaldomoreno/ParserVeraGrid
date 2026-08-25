# Notas do formato ANAREDE (.pwf) e do mapeamento para RAW

Este documento registra, de forma verificável, como cada campo foi
determinado - para que qualquer seção nova adicionada no futuro siga
o mesmo processo de validação empírica (e não apenas "confie no
manual", já que o comentário de cabeçalho embutido no próprio arquivo
`.pwf` **não é sempre pixel-perfeito** em relação às colunas reais de
dados, como descrito abaixo).

## Convenção geral

- Formato de colunas fixas (fixed-width), **não delimitado**.
- Índices de coluna são 1-based e inclusivos nas duas pontas (igual ao
  Manual do Usuário CEPEL/ANAREDE).
- Cada bloco de dados começa com uma linha `DXXX` (ex. `DBAR`), seguida
  por **uma linha de comentário** iniciada por `(` com os rótulos dos
  campos, seguida pelos registros de dados, terminando em uma linha
  `99999`.
- Encoding: Latin-1 (arquivos ONS têm acentuação em português).
- Terminador de linha: CRLF.

## Decimal implícito

Campos numéricos estreitos (ex. Tensão em `DBAR`, 4 colunas) não têm
espaço para o ponto decimal quando o valor usa todas as casas
disponíveis. Nesse caso o ANAREDE grava o número **sem o ponto**, e a
posição decimal é implícita pela largura do campo. Quando o valor cabe
com o ponto, o ANAREDE grava o ponto normalmente.

Exemplo real (`DBAR`, campo Tensão, colunas 25-28):
- Texto no arquivo: `1001`
- Sem ponto ⇒ decimal implícito (1 casa inteira, 3 decimais) ⇒ `1.001` pu

Exemplo real (`DBAR`, campo Ângulo, colunas 29-32):
- Texto no arquivo: `-53.`
- Contém ponto ⇒ parse direto ⇒ `-53.0`

O parser (`sections.number`) implementa exatamente essa regra: se o
campo contém `.`, faz `float()` direto; senão aplica o número de casas
implícitas configurado por campo.

## Pegadinha real encontrada: `DLIN` — bus de destino vs. circuito

Durante a validação, uma leitura ingênua de uma linha como:

```
   38       17954         3.0195         1. ...
```

sugere (visualmente) que o barramento de destino é `17954`. **Isso
está errado.** O campo `to_bus` ocupa as colunas 11-15 e o campo
`circuit` ocupa as colunas 16-17 (2 caracteres, permitindo até 2
dígitos). Quando o número da barra é curto (3 dígitos, `179`) e o
circuito tem 2 dígitos (`54`), o texto colado visualmente parece um
único número de 5 dígitos. A forma correta de confirmar isso foi
comparar com uma linha onde os campos aparecem naturalmente separados
por espaço:

```
   60     43810 2 ...
```

Aqui fica claro: `to_bus=43810` (5 dígitos, preenche exatamente as
colunas 11-15) e `circuit=2` (1 dígito, coluna 17, coluna 16 em
branco). Isso confirma o mapeamento `to_bus: 11-15`, `circuit: 16-17`.

Há um teste de regressão para isso em `tests/test_sections.py::test_dlin_columns_against_real_ons_lines`.

## Detecção de transformador em `DLIN`

O ANAREDE não tem um registro `DLIN` separado exclusivamente para
transformadores — a mesma seção descreve linhas CA e transformadores
de 2 enrolamentos. O parser classifica um registro como transformador
quando:

1. O campo `tap` está preenchido e é diferente de zero, **ou**
2. As barras `from`/`to` têm bases de tensão nominal (kV) diferentes,
   resolvidas via `DGBT`.

Isso é uma heurística razoável para a maioria dos decks, mas pode
falhar em casos extremos (ex. tap=1.0 explícito em um transformador
sem mudança de kV nominal cadastrada corretamente). Ver seção
"Limitações conhecidas" abaixo.

## `DGBT` — grupos de base de tensão

Formato "solto" (tokens separados por espaço, não fixed-width). Mapeia
um código de grupo (1-2 caracteres, ex. `V`, `GC`, `41`) para o kV
nominal correspondente. Barras sem grupo definido (`Gb` em branco) têm
kV = 1.0 conforme o manual ("Grupos não definidos terão valor igual a
1 kV").

Nota: grupos como `V`, `U`, `T` costumam aparecer com valores como
`992.`, `991.`, `990.` em decks do ONS — não são kV reais, e sim
códigos "placeholder" tipicamente usados em barras internas de
geração (terminal de gerador). Isso é esperado e não é um bug do
parser.

## Seções implementadas nesta versão (v0.1)

| Seção | Conteúdo | Status |
|---|---|---|
| `DBAR` | Barras, cargas embutidas, shunt fixo embutido, geração Pg/Qg | ✅ |
| `DGBT` | Grupo de base de tensão → kV | ✅ |
| `DGER` | Limites de geração ativa (Pmin/Pmax) | ✅ |
| `DLIN` | Linhas CA e transformadores de 2 enrolamentos | ✅ |

## Seções conhecidas e ainda NÃO implementadas (roadmap)

Ver `sections.SECTIONS_KNOWN_NOT_IMPLEMENTED` — o parser detecta a
presença dessas seções no arquivo e emite um aviso (`Network.warnings`),
em vez de falhar silenciosamente:

- `DBSH` — bancos de shunt chaveáveis (capacitor/reator controlado) →
  mapear para *Switched Shunt* do RAW.
- `DCTR` — controle de tap/LTC de transformador → hoje o tap é
  importado como fixo (`windv1`); falta o modo de controle
  (CONT bus, VMA/VMI etc.) e o intervalo de tap (`Tmn`/`Tmx`, já lidos
  mas não usados).
- `DELO`, `DCNV`, `DCCV`, `DCLI`, `DCBA` — elos e conversores de
  corrente contínua (HVDC) → mapear para os registros de DC de 2
  terminais / multi-terminal do RAW. **Importante:** decks do SIN têm
  elos CC significativos (Madeira, Xingu). Sem isso, subsistemas
  conectados só via CC ficam eletricamente ilhados no RAW resultante,
  o que provavelmente explica a não-convergência observada ao rodar
  fluxo de potência no deck completo do ONS (ver README).
- `DCER`, `DCSC` — compensadores síncronos/estáticos e TCSC.
- `DGLT`, `DARE`, `DAGR`, `DUSI`, `DCTE`, `DCAR` — dados
  complementares/organizacionais que não afetam a topologia elétrica
  básica, mas são úteis para relatórios e conferência.

## Referência cruzada

As posições de coluna foram determinadas empiricamente a partir de
decks reais, mas o projeto open source
[`pyxparser`](https://github.com/mcllerena/pyxparser) (licença
BSD-3-Clause) documenta um mapeamento equivalente para `DBAR`, `DLIN`
e `DGER`, que serviu como segunda fonte de validação cruzada durante o
desenvolvimento. Vale a pena conhecer esse projeto — ele resolve um
problema adjacente (conversão PWF → outros formatos via um mapeamento
declarativo em JSON) e pode ser uma fonte útil para expandir a
cobertura de seções deste projeto no futuro.
