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


def integer(line: str, f: Field, default=None):
    t = text(line, f)
    if not t:
        return default
    try:
        return int(t)
    except ValueError:
        # às vezes vem com ponto (ex "1.") em campos que deveriam ser int
        return int(float(t))


def number(line: str, f: Field, default=None):
    """Lê um campo numérico decimal, tratando decimal implícito."""
    t = text(line, f)
    if not t:
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

SECTIONS_IMPLEMENTED = {"DBAR", "DGBT", "DLIN", "DGER"}

# Seções presentes em decks ONS típicos que ainda NÃO são interpretadas
# nesta versão (ver docs/FORMAT_NOTES.md e README - roadmap).
SECTIONS_KNOWN_NOT_IMPLEMENTED = {
    "DBSH": "Bancos de shunt chaveáveis (capacitor/reator controlado)",
    "DCAR": "Dados complementares de carga",
    "DCER": "Compensadores estáticos / síncronos",
    "DCSC": "Compensadores série controláveis (TCSC)",
    "DCTR": "Dados complementares de transformador (controle de tap/LTC)",
    "DELO": "Elos de corrente contínua (HVDC) - dados gerais",
    "DCNV": "Conversores CC",
    "DCCV": "Dados de conversora CC",
    "DCLI": "Dados de linha CC",
    "DCBA": "Dados de barra CC",
    "DGLT": "Limites de geração de reativo por grupo",
    "DARE": "Dados de área",
    "DAGR": "Agrupamentos (submercados etc.)",
    "DUSI": "Dados de usina",
    "DCTE": "Constantes gerais do caso (tolerâncias etc.)",
}
