"""Modelo de dados intermediário (independente de formato de entrada/saída).

A ideia é o `PwfReader` popular esta estrutura, e qualquer "writer"
(RAW, futuramente .gridcal nativo, etc.) consumir só isto - assim o
parser de leitura fica desacoplado do formato de escrita.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field


@dataclass
class Bus:
    number: int
    name: str
    base_kv: float
    vm: float = 1.0
    va: float = 0.0
    bus_type: int = 1  # convenção PSS/E: 1=PQ, 2=PV, 3=slack, 4=isolada
    area: int = 1
    zone: int = 1
    owner: int = 1
    in_service: bool = True


@dataclass
class Load:
    bus: int
    id: str
    p: float
    q: float
    in_service: bool = True


@dataclass
class FixedShunt:
    bus: int
    id: str
    g: float
    b: float
    in_service: bool = True


@dataclass
class Generator:
    bus: int
    id: str
    pg: float
    qg: float
    qmin: float
    qmax: float
    vs: float
    pmin: float
    pmax: float
    mbase: float = 100.0
    in_service: bool = True


@dataclass
class Branch:
    from_bus: int
    to_bus: int
    ckt: str
    r: float
    x: float
    b: float
    rate_a: float = 0.0
    rate_b: float = 0.0
    rate_c: float = 0.0
    in_service: bool = True


@dataclass
class Transformer2W:
    from_bus: int
    to_bus: int
    ckt: str
    r: float
    x: float
    windv1: float = 1.0
    angle: float = 0.0
    windv2: float = 1.0
    rate_a: float = 0.0
    rate_b: float = 0.0
    rate_c: float = 0.0
    in_service: bool = True
    # Controle de tap sob carga (LTC), do DLIN: faixa de tap, barra
    # controlada e numero de posicoes. ltc=False => tap fixo.
    ltc: bool = False
    tap_min: float = 0.9
    tap_max: float = 1.1
    controlled_bus: int = 0
    n_taps: int = 33


@dataclass
class SwitchedShunt:
    """Banco chaveavel (DBSH) ou compensador estatico (DCER)."""
    bus: int
    binit: float          # Mvar iniciais em 1.0 pu
    v_min: float = 0.9
    v_max: float = 1.1
    controlled_bus: int = 0
    modsw: int = 1        # 0=fixo, 1=discreto, 2=continuo
    blocks: list = dc_field(default_factory=list)  # [(n_steps, Mvar/step)]
    in_service: bool = True


@dataclass
class DcConverter:
    ac_bus: int
    dc_bus: int
    neutral_bus: int = 0
    kind: str = "R"       # R = retificador, I = inversor
    control_type: str = ""
    setpoint: float = 0.0
    bridges: int = 1
    xc_pct: float = 0.0
    ebas_kv: float = 0.0
    angle_setpoint: float = 0.0
    angle_min: float = 5.0
    angle_max: float = 90.0
    tap_min: float = 0.9
    tap_max: float = 1.1


@dataclass
class DcLink:
    """Elo CC classico (LCC), montado a partir de DELO/DCBA/DCLI/DCNV/DCCV."""
    number: int
    name: str
    kv: float = 0.0
    mw: float = 0.0
    r_ohm: float = 0.0
    in_service: bool = True
    rectifier: "DcConverter | None" = None
    inverter: "DcConverter | None" = None


@dataclass
class VscLink:
    """Elo HVDC do tipo VSC (registro DVSC)."""
    number: int
    name: str
    rectifier_bus: int
    inverter_bus: int
    mw: float = 0.0
    mva_base: float = 0.0
    vcc_kv: float = 0.0
    vcc_base_kv: float = 0.0
    r_ohm: float = 0.0
    in_service: bool = True


@dataclass
class Area:
    number: int
    name: str = ""
    exchange: float = 0.0


@dataclass
class Network:
    sbase: float = 100.0
    case_name: str = ""
    buses: dict[int, Bus] = dc_field(default_factory=dict)
    loads: list[Load] = dc_field(default_factory=list)
    fixed_shunts: list[FixedShunt] = dc_field(default_factory=list)
    generators: list[Generator] = dc_field(default_factory=list)
    branches: list[Branch] = dc_field(default_factory=list)
    transformers: list[Transformer2W] = dc_field(default_factory=list)
    switched_shunts: list[SwitchedShunt] = dc_field(default_factory=list)
    dc_links: list[DcLink] = dc_field(default_factory=list)
    vsc_links: list[VscLink] = dc_field(default_factory=list)
    areas: list[Area] = dc_field(default_factory=list)

    # dados de apoio (não exportados, mas úteis para diagnóstico)
    warnings: list[str] = dc_field(default_factory=list)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def summary(self) -> str:
        return (
            f"{len(self.buses)} barras, {len(self.loads)} cargas, "
            f"{len(self.fixed_shunts)} shunts fixos, "
            f"{len(self.generators)} geradores, "
            f"{len(self.branches)} linhas, "
            f"{len(self.transformers)} transformadores 2 enrolamentos, "
            f"{len(self.switched_shunts)} shunts chaveaveis, "
            f"{len(self.dc_links)} elos CC, "
            f"{len(self.vsc_links)} elos VSC, "
            f"{len(self.areas)} areas, "
            f"{len(self.warnings)} avisos"
        )
