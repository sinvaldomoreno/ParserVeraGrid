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
            f"{len(self.warnings)} avisos"
        )
