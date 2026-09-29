"""
Especificação de colunas dos registros do formato ANAREDE (.pwf).

O formato PWF é um formato de colunas fixas (fixed-width), não delimitado.
As posições abaixo foram determinadas por validação empírica diretamente
sobre decks reais (incluindo o deck completo do SIN - patamar de carga
média, ONS), comparando o comentário de cabeçalho de cada bloco (ex.
"(Num)OETGb(   nome   )Gl( V)...") com o conteúdo real das colunas.

Convenção de índices: 1-based, INCLUSIVO em ambas as pontas (igual à
documentação do Manual do Usuário ANAREDE/CEPEL), isto é, um campo
"start=11, end=22" ocupa os caracteres 11 a 22 da linha.

Casas decimais implícitas
--------------------------
Alguns campos numéricos estreitos (ex. Tensão em DBAR, colunas 25-28)
não têm largura suficiente para conter o ponto decimal quando o valor
usa todas as casas decimais disponíveis. Nesse caso o ANAREDE grava o
número sem o ponto e a posição decimal é implícita (ex. "1001" == 1.001
quando o campo tem 1 casa inteira e 3 decimais). Quando o valor cabe
com o ponto explícito, o ANAREDE grava o ponto normalmente (ex. "-53."
== -53.0). O parser trata isso da seguinte forma: se o campo contém um
".", faz-se float(campo); caso contrário, aplica-se o número de casas
implícitas configurado para aquele campo (0 por padrão, ou seja, inteiro).

Referência cruzada / crédito
-----------------------------
As posições de colunas foram checadas de forma independente, mas o
projeto de código aberto `pyxparser` (github.com/mcllerena/pyxparser,
licença BSD-3-Clause) documenta um mapeamento equivalente para DBAR,
DLIN e DGER, o que serviu como segunda fonte de validação cruzada.
Vale a pena conhecer aquele projeto também.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    name: str
    start: int  # 1-based, inclusive
    end: int  # 1-based, inclusive
    implicit_decimals: int = 0  # usado só quando o campo não tem '.'


def raw(line: str, start: int, end: int) -> str:
    """Extrai o texto bruto (sem strip) de uma coluna 1-based inclusiva."""
    if start - 1 >= len(line):
        return ""
    return line[start - 1:end]


def text(line: str, f: Field) -> str:
    return raw(line, f.start, f.end).strip()


def is_parseable_number(t: str) -> bool:
    """Um token so e numerico se sobrar algo alem de sinal/ponto.

    Tokens como '-' ou '.' sozinhos aparecem quando o layout de colunas
    nao bate com o arquivo e um numero fica partido entre dois campos
    (ver `alignment_symptoms`).
    """
    t = t.strip()
    if not t:
        return False
    try:
        float(t)
        return True
    except ValueError:
        return False


def alignment_symptoms(line: str, fields) -> list[str]:
    """Detecta sinais de que o layout de colunas nao bate com o arquivo.

    O sintoma mais confiavel e um campo contendo apenas um sinal ou um
    ponto decimal: so acontece quando um numero real ficou partido na
    fronteira entre dois campos. Sem essa checagem, um deck escrito por
    outra versao do ANAREDE seria lido em silencio com valores errados.
    """
    bad = []
    for f in fields:
        t = text(line, f)
        if t and t in ("-", "+", ".", "-.", "+."):
            bad.append(f.name)
    return bad


def integer(line: str, f: Field, default=None):
    t = text(line, f)
    if not t or not is_parseable_number(t):
        return default
    try:
        return int(t)
    except ValueError:
        # às vezes vem com ponto (ex "1.") em campos que deveriam ser int
        return int(float(t))


def number(line: str, f: Field, default=None):
    """Lê um campo numérico decimal, tratando decimal implícito."""
    t = text(line, f)
    if not t or not is_parseable_number(t):
        return default
    if "." in t:
        return float(t)
    if f.implicit_decimals:
        sign = 1
        if t.startswith("-"):
            sign = -1
            t = t[1:]
        elif t.startswith("+"):
            t = t[1:]
        scale = 10 ** f.implicit_decimals
        return sign * int(t) / scale
    return float(t)


# ---------------------------------------------------------------------
# DBAR - Dados de barra CA
# ---------------------------------------------------------------------
DBAR = {
    "number": Field("number", 1, 5),
    "operation": Field("operation", 6, 6),
    "state": Field("state", 7, 7),
    "type": Field("type", 8, 8),
    "voltage_base_group": Field("voltage_base_group", 9, 10),
    "name": Field("name", 11, 22),
    # cols 23-24 = "Gl" (grupo de limite de tensão) - não usado no MVP
    "voltage": Field("voltage", 25, 28, implicit_decimals=3),
    "angle": Field("angle", 29, 32, implicit_decimals=2),
    "active_generation": Field("active_generation", 33, 37),
    "reactive_generation": Field("reactive_generation", 38, 42),
    "min_reactive_generation": Field("min_reactive_generation", 43, 47),
    "max_reactive_generation": Field("max_reactive_generation", 48, 52),
    "controlled_bus": Field("controlled_bus", 53, 58),
    "active_load": Field("active_load", 59, 63),
    "reactive_load": Field("reactive_load", 64, 68),
    "capacitor_reactor": Field("capacitor_reactor", 69, 73),
    "area": Field("area", 74, 76),
    "voltage_for_load_definition": Field("voltage_for_load_definition", 77, 80),
    "visualization_mode": Field("visualization_mode", 81, 81),
}

# ---------------------------------------------------------------------
# DGBT - Grupos de base de tensão (código de grupo -> kV nominal)
# Formato "solto" (separado por espaços), não fixed-width estrito.
# ---------------------------------------------------------------------

# ---------------------------------------------------------------------
# DLIN - Dados de linha / circuito (linhas CA e transformadores)
# ---------------------------------------------------------------------
DLIN = {
    "from_bus": Field("from_bus", 1, 5),
    "from_bus_opening": Field("from_bus_opening", 6, 6),
    "operation": Field("operation", 8, 8),
    "to_bus_opening": Field("to_bus_opening", 10, 10),
    "to_bus": Field("to_bus", 11, 15),
    "circuit": Field("circuit", 16, 17),
    "state": Field("state", 18, 18),
    "owner": Field("owner", 19, 19),
    "resistance": Field("resistance", 21, 26),  # % (base 100 MVA)
    "reactance": Field("reactance", 27, 32),  # %
    "susceptance": Field("susceptance", 33, 38),  # Mvar totais (carregamento)
    "tap": Field("tap", 39, 43),
    "tap_minimum": Field("tap_minimum", 44, 48),
    "tap_maximum": Field("tap_maximum", 49, 53),
    "phase_shift": Field("phase_shift", 54, 58),
    "controlled_bus": Field("controlled_bus", 59, 64),
    "normal_capacity": Field("normal_capacity", 65, 68),  # MVA
    "emergency_capacity": Field("emergency_capacity", 69, 72),  # MVA
    "number_of_taps": Field("number_of_taps", 73, 74),
    "equipment_capacity": Field("equipment_capacity", 75, 78),  # MVA
}

# ---------------------------------------------------------------------
# DGER - Dados complementares de máquina (limites de geração ativa)
# ---------------------------------------------------------------------
DGER = {
    "number": Field("number", 1, 5),
    "operation": Field("operation", 7, 7),
    "min_active_generation": Field("min_active_generation", 9, 14),
    "max_active_generation": Field("max_active_generation", 16, 21),
    "participation_factor": Field("participation_factor", 23, 27),
    "remote_control_participation_factor": Field(
        "remote_control_participation_factor", 29, 33
    ),
    "nominal_power_factor": Field("nominal_power_factor", 35, 39),
    "armature_service_factor": Field("armature_service_factor", 41, 44),
    "rotor_service_factor": Field("rotor_service_factor", 46, 49),
    "load_angle": Field("load_angle", 51, 54),
    "machine_reactance": Field("machine_reactance", 56, 60),
    "nominal_apparent_power": Field("nominal_apparent_power", 62, 66),
}


# ---------------------------------------------------------------------
# DBSH - Bancos de shunt chaveaveis. Estrutura em dois niveis: uma linha
# de cabecalho por banco e, apos a linha "(G  O E ...", uma ou mais
# linhas de grupo, terminadas por FBAN.
# ---------------------------------------------------------------------
DBSH = {
    "from_bus": Field("from_bus", 1, 5),
    "to_bus": Field("to_bus", 10, 14),
    "circuit": Field("circuit", 15, 17),
    "control_mode": Field("control_mode", 18, 18),
    "v_min": Field("v_min", 20, 23, implicit_decimals=3),
    "v_max": Field("v_max", 25, 28, implicit_decimals=3),
    "controlled_bus": Field("controlled_bus", 30, 35),
    "q_initial": Field("q_initial", 36, 42),
    "mode": Field("mode", 43, 43),
    "state": Field("state", 45, 45),
}

DBSH_GROUP = {
    "group": Field("group", 1, 2),
    "state": Field("state", 7, 7),
    "units": Field("units", 9, 11),
    "units_operating": Field("units_operating", 13, 15),
    "shunt_per_unit": Field("shunt_per_unit", 17, 22),
    "manoeuvre": Field("manoeuvre", 24, 24),
}

# ---------------------------------------------------------------------
# DSHL - Shunts de linha (reator/capacitor nos terminais de um circuito).
# O RAW rev 33 nao tem shunt de linha nativo: cada extremidade vira um
# shunt fixo na barra correspondente, que e a conversao usual e preserva
# o balanco de reativo.
# ---------------------------------------------------------------------
DSHL = {
    "from_bus": Field("from_bus", 1, 5),
    "to_bus": Field("to_bus", 10, 14),
    "circuit": Field("circuit", 15, 16),
    "shunt_from": Field("shunt_from", 18, 23),
    "shunt_to": Field("shunt_to", 24, 29),
    "state_from": Field("state_from", 31, 32),
    "state_to": Field("state_to", 34, 35),
}

# ---------------------------------------------------------------------
# DCER - Compensadores estaticos de reativo (SVC).
# ---------------------------------------------------------------------
# Cabecalho: "(No ) O Gr Un (Kb ) (Incl) ( Qg)( Qn)( Qm) C E L"
DCER = {
    "bus": Field("bus", 1, 5),
    "operation": Field("operation", 7, 7),
    "group": Field("group", 9, 10),
    "units": Field("units", 12, 13),
    "controlled_bus": Field("controlled_bus", 15, 19),
    "slope": Field("slope", 21, 26),
    "reactive_generation": Field("reactive_generation", 28, 32),
    "min_reactive": Field("min_reactive", 33, 37),
    "max_reactive": Field("max_reactive", 38, 42),
    "control_mode": Field("control_mode", 44, 44),
    "state": Field("state", 46, 46),
}

# ---------------------------------------------------------------------
# DCSC - Compensadores serie controlaveis (TCSC).
# ---------------------------------------------------------------------
# Cabecalho: "(De ) O  (Pa )NcEPB      (Xmin)(Xmax)( Xv )C ( Vsp) (Ext)Nst(Cn)(Ce)(Cq)"
DCSC = {
    "from_bus": Field("from_bus", 1, 5),
    "to_bus": Field("to_bus", 10, 14),
    "circuit": Field("circuit", 15, 16),
    "state": Field("state", 17, 17),
    "owner": Field("owner", 18, 18),
    "min_reactance": Field("min_reactance", 26, 31),
    "max_reactance": Field("max_reactance", 32, 37),
    "initial_reactance": Field("initial_reactance", 38, 43),
    "control_mode": Field("control_mode", 44, 44),
    "setpoint": Field("setpoint", 46, 51),
    "normal_capacity": Field("normal_capacity", 61, 64),
    "emergency_capacity": Field("emergency_capacity", 65, 68),
}

# ---------------------------------------------------------------------
# Rede de corrente continua (DELO/DCBA/DCLI/DCNV/DCCV) e VSC (DVSC).
# ---------------------------------------------------------------------
DELO = {
    "number": Field("number", 1, 4),
    "voltage": Field("voltage", 8, 12),
    # Coluna 14-18 e a BASE do elo, nao a potencia de operacao. O ponto
    # de operacao vem do DCCV (SPECIFIED VALUE) quando o tipo de
    # controle e 'P'. Confirmado contra a especificacao do PWF.jl
    # (LAMPSPUC), que valida este mapeamento de forma independente.
    "base": Field("base", 14, 18),
    "name": Field("name", 20, 39),
    "mode": Field("mode", 41, 41),
    "state": Field("state", 43, 43),
}

DCBA = {
    "number": Field("number", 1, 4),
    "type": Field("type", 8, 8),
    "polarity": Field("polarity", 9, 9),
    "name": Field("name", 10, 21),
    "voltage": Field("voltage", 24, 28),
    "ground_r": Field("ground_r", 67, 71),
    "link": Field("link", 72, 75),
}

DCLI = {
    "from_bus": Field("from_bus", 1, 4),
    "to_bus": Field("to_bus", 9, 12),
    "circuit": Field("circuit", 13, 14),
    "state": Field("state", 16, 16),
    "resistance": Field("resistance", 18, 23),
    "inductance": Field("inductance", 24, 29),
    "capacity": Field("capacity", 61, 64),
}

DCNV = {
    "number": Field("number", 1, 4),
    "ac_bus": Field("ac_bus", 8, 12),
    "dc_bus": Field("dc_bus", 14, 17),
    "neutral_bus": Field("neutral_bus", 19, 22),
    "type": Field("type", 24, 24),
    "bridges": Field("bridges", 26, 26),
    "nominal_current": Field("nominal_current", 28, 32),
    "xc_pct": Field("xc_pct", 34, 38),
    "ebas_kv": Field("ebas_kv", 40, 44),
    "nominal_power": Field("nominal_power", 46, 50),
}

DCCV = {
    "number": Field("number", 1, 4),
    "looseness": Field("looseness", 8, 8),
    "inverter_control_mode": Field("inverter_control_mode", 9, 9),
    "control_type": Field("control_type", 10, 10),
    "setpoint": Field("setpoint", 12, 16),
    "margin": Field("margin", 18, 22),
    "max_current": Field("max_current", 24, 28),
    "angle_setpoint": Field("angle_setpoint", 30, 34),
    "angle_min": Field("angle_min", 36, 40),
    "angle_max": Field("angle_max", 42, 46),
    "tap_min": Field("tap_min", 48, 52),
    "tap_max": Field("tap_max", 54, 58),
}

DVSC = {
    "number": Field("number", 1, 4),
    "state": Field("state", 8, 8),
    "rectifier_bus": Field("rectifier_bus", 10, 14),
    "inverter_bus": Field("inverter_bus", 16, 20),
    "power": Field("power", 22, 28),
    "power_base": Field("power_base", 30, 36),
    "vcc": Field("vcc", 38, 46),
    "vcc_base": Field("vcc_base", 48, 56),
    "r_line": Field("r_line", 58, 65),
    "name": Field("name", 67, 86),
}

DARE = {
    "number": Field("number", 1, 3),
    "exchange": Field("exchange", 5, 10),
    "name": Field("name", 12, 47),
}


SECTIONS_IMPLEMENTED = {
    "DBAR", "DGBT", "DLIN", "DGER", "DBSH", "DSHL", "DCER", "DCSC",
    "DELO", "DCBA", "DCLI", "DCNV", "DCCV", "DVSC", "DARE",
}



SECTIONS_KNOWN_NOT_IMPLEMENTED = {
    "DCTR": "Dados complementares de transformador (controle de tap/LTC)",
    "DGLT": "Limites de tensao por grupo",
    "DAGR": "Agrupamentos (submercados etc.) - organizacional",
    "DUSI": "Dados de usina - organizacional/relatorio",
    "DCTE": "Constantes gerais do caso (tolerancias do fluxo)",
    "DCAR": "Dados complementares de carga (curvas ZIP)",
    "DCMT": "Bloco de comentarios livres (sem dado eletrico)",
    "DOPC": "Opcoes de execucao",
    "DTPF": "Opcoes de relatorio",
}


# =====================================================================
# LAYOUT DERIVADO DO CABECALHO
#
# As posicoes acima sao o layout dos decks do ONS/EPE. Mas o layout do
# PWF NAO e estavel entre versoes do ANAREDE: no caso de referencia de
# 107 barras do CEPEL o campo (Bc) tem 5 colunas em vez de 6, o que
# desloca todos os campos seguintes em 1. Lido com o layout errado, o
# reator "-200." de Araraquara se parte em Ql='-' + Sh='200.' e a area
# vira 110 no lugar de 1 - silenciosamente.
#
# Felizmente o proprio arquivo carrega o layout: a linha de comentario
# logo apos o codigo da secao delimita os campos com parenteses:
#   (Num)OETGb(   nome   )Gl( V)( A)( Pg)( Qg)...
# Derivamos as colunas desses parenteses, usando o layout hardcoded
# apenas como fallback quando nao ha cabecalho utilizavel.
# =====================================================================


def parse_header_spans(header: str) -> list[tuple[int, int]]:
    """Extrai os spans (1-based, inclusivos) delimitados por parenteses."""
    spans: list[tuple[int, int]] = []
    i = 0
    while i < len(header):
        if header[i] == "(":
            j = header.find(")", i)
            if j == -1:
                spans.append((i + 1, len(header)))
                break
            spans.append((i + 1, j + 1))
            i = j + 1
        else:
            i += 1
    return spans


# Para cada secao: nomes canonicos dos campos entre parenteses, na ordem
# do cabecalho, e os campos curtos que ficam nos "vaos" entre eles
# (indice do vao = indice do parenteses anterior). Um nome None e um
# preenchimento de colunas em branco.
HEADER_LAYOUT: dict[str, dict] = {
    "DBAR": {
        "brackets": [
            "number", "name", "voltage", "angle", "active_generation",
            "reactive_generation", "min_reactive_generation",
            "max_reactive_generation", "controlled_bus", "active_load",
            "reactive_load", "capacitor_reactor",
            "voltage_for_load_definition",
        ],
        "gaps": {
            0: [("operation", 1), ("state", 1), ("type", 1),
                ("voltage_base_group", 2)],
            1: [("voltage_limit_group", 2)],
        },
    },
    "DLIN": {
        "brackets": [
            "from_bus", "to_bus", "resistance", "reactance", "susceptance",
            "tap", "tap_minimum", "tap_maximum", "phase_shift",
            "controlled_bus", "normal_capacity", "emergency_capacity",
            "equipment_capacity",
        ],
        "gaps": {
            0: [("from_bus_opening", 1), (None, 1), ("operation", 1),
                (None, 1), ("to_bus_opening", 1)],
            1: [("circuit", 2), ("state", 1), ("owner", 1)],
            11: [("number_of_taps", 2)],
        },
    },
    "DSHL": {
        "brackets": ["from_bus", "to_bus", "shunt_from", "shunt_to"],
        "gaps": {1: [("circuit", 2)]},
    },
    "DCSC": {
        "brackets": ["from_bus", "to_bus", "min_reactance", "max_reactance",
                     "initial_reactance", "setpoint", None,
                     "normal_capacity", "emergency_capacity"],
        "gaps": {1: [("circuit", 2), ("state", 1), ("owner", 1)]},
    },
    "DCER": {
        "brackets": ["bus", "controlled_bus", "slope",
                     "reactive_generation", "min_reactive", "max_reactive"],
        "gaps": {0: [(None, 1), ("operation", 1), (None, 1), ("group", 2),
                     (None, 1), ("units", 2)]},
    },
    "DVSC": {
        "brackets": [
            "number", "rectifier_bus", "inverter_bus", "power",
            "power_base", "vcc", "vcc_base", "r_line", "name",
        ],
        "gaps": {},
    },
}


def layout_from_header(section: str, header: str, default: dict) -> dict:
    """Constroi o dict de Field a partir do cabecalho do arquivo.

    Retorna o layout default se o cabecalho nao for utilizavel, para
    nunca piorar em relacao ao comportamento anterior.
    """
    spec = HEADER_LAYOUT.get(section)
    if spec is None or not header:
        return default

    spans = parse_header_spans(header)
    names = spec["brackets"]
    if len(spans) < len(names):
        return default

    out: dict[str, Field] = dict(default)
    for name, (start, end) in zip(names, spans):
        if name is None:
            continue
        prev = default.get(name)
        out[name] = Field(
            name, start, end,
            implicit_decimals=prev.implicit_decimals if prev else 0,
        )

    for gap_idx, entries in spec.get("gaps", {}).items():
        if gap_idx >= len(spans):
            continue
        cursor = spans[gap_idx][1] + 1
        for fname, width in entries:
            if fname is not None:
                prev = default.get(fname)
                out[fname] = Field(
                    fname, cursor, cursor + width - 1,
                    implicit_decimals=prev.implicit_decimals if prev else 0,
                )
            cursor += width

    return out
