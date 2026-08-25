"""Escritor do formato PSS/E RAW (rev 33) a partir do modelo `Network`.

Rev 33 foi escolhida por ser amplamente suportada (inclusive por
leitores baseados em `raw` no ecossistema GridCal/VeraGrid) e por ser
a revisão dos arquivos de exemplo usados como referência neste projeto.

Este writer cobre: Bus, Load, Fixed Shunt, Generator, Branch (non
transformer) e Transformer (2 enrolamentos). As demais seções do RAW
(Area, DC de dois terminais, VSC, correção de impedância, MSL, Zone,
Inter-area transfer, Owner, FACTS, Switched Shunt, GNE) são escritas
vazias (terminador "0") para manter o arquivo válido - ver README para
o roadmap de extensão.
"""
from __future__ import annotations

from pathlib import Path

from .model import Network


def _q(text: str, width: int) -> str:
    return f"'{text[:width]:<{width}}'"


def write_raw(net: Network, path: str | Path) -> None:
    path = Path(path)
    lines: list[str] = []

    # --- Case identification (registro 0) ---
    lines.append(f" 0,{net.sbase:>9.2f}, 33, 0, 0, 60.00")
    lines.append(f"pwf2raw / gerado a partir de {net.case_name}.pwf")
    lines.append("")

    # --- Bus data ---
    for bus in sorted(net.buses.values(), key=lambda b: b.number):
        ide = 1 if bus.in_service else 4
        lines.append(
            f"{bus.number:>6d},{_q(bus.name, 12)},{bus.base_kv:>10.4f},"
            f"{bus.bus_type if bus.in_service else 4},{bus.area:>4d},"
            f"{1:>4d},{bus.owner:>4d},{bus.vm:>9.5f},{bus.va:>10.4f}"
        )
    lines.append("0 / END OF BUS DATA, BEGIN LOAD DATA")

    # --- Load data ---
    for ld in net.loads:
        status = 1 if ld.in_service else 0
        lines.append(
            f"{ld.bus:>6d},{_q(ld.id, 2)},{status},   1,   1,"
            f"{ld.p:>11.3f},{ld.q:>11.3f},     0.000,     0.000,"
            f"     0.000,    -0.000,   1,1"
        )
    lines.append("0 / END OF LOAD DATA, BEGIN FIXED SHUNT DATA")

    # --- Fixed shunt data ---
    for sh in net.fixed_shunts:
        status = 1 if sh.in_service else 0
        lines.append(
            f"{sh.bus:>6d},{_q(sh.id, 2)},{status},{sh.g:>10.3f},{sh.b:>10.3f}"
        )
    lines.append("0 / END OF FIXED SHUNT DATA, BEGIN GENERATOR DATA")

    # --- Generator data ---
    for gen in net.generators:
        status = 1 if gen.in_service else 0
        lines.append(
            f"{gen.bus:>6d},{_q(gen.id, 2)},{gen.pg:>10.3f},{gen.qg:>10.3f},"
            f"{gen.qmax:>10.3f},{gen.qmin:>10.3f},{gen.vs:>8.5f},    0,"
            f"{gen.mbase:>10.3f},0.00000,1.00000,0.00000,0.00000,1.00000,"
            f"{status},{100.0:>7.1f},{gen.pmax:>10.3f},{gen.pmin:>10.3f},"
            "   1,1.0000,   0,1.0000,   0,1.0000,   0,1.0000,0, 1.0000"
        )
    lines.append("0 / END OF GENERATOR DATA, BEGIN BRANCH DATA")

    # --- Branch data ---
    for br in net.branches:
        status = 1 if br.in_service else 0
        lines.append(
            f"{br.from_bus:>6d},{br.to_bus:>6d},{_q(br.ckt, 2)},"
            f"{br.r:>8.5f},{br.x:>8.5f},{br.b:>8.5f},"
            f"{br.rate_a:>7.2f},{br.rate_b:>7.2f},{br.rate_c:>7.2f},"
            "  0.00000,  0.00000,  0.00000,  0.00000,"
            f"1,{status},   0.0,   1,1.0000,   0,1.0000,   0,1.0000,   0,1.0000"
        )
    lines.append("0 / END OF BRANCH DATA, BEGIN TRANSFORMER DATA")

    # --- Transformer data (2-winding, 4-record format) ---
    for tr in net.transformers:
        status = 1 if tr.in_service else 0
        lines.append(
            f"{tr.from_bus:>6d},{tr.to_bus:>6d},{0:>6d},{_q(tr.ckt, 2)},"
            f"1,1,1,  0.00000,  0.00000,2,{_q('', 8)},{status},"
            "   1,1.0000,   0,1.0000,   0,1.0000,   0,1.0000"
        )
        lines.append(f" {tr.r:.5f}, {tr.x:.5f}, {net.sbase:.2f}")
        lines.append(
            f"{tr.windv1:.5f},  {tr.angle:.3f},   0.000,"
            f"{tr.rate_a:>7.2f},{tr.rate_b:>7.2f},{tr.rate_c:>7.2f},"
            "0,     0, 1.50000, 0.51000, 1.50000, 0.51000,159, 0, 0.00000, 0.00000"
        )
        lines.append(f"{tr.windv2:.5f},  0.000")
    lines.append("0 / END OF TRANSFORMER DATA, BEGIN AREA DATA")

    # --- Remaining sections: written empty (roadmap) ---
    lines.append("0 / END OF AREA DATA, BEGIN TWO-TERMINAL DC DATA")
    lines.append("0 / END OF TWO-TERMINAL DC DATA, BEGIN VOLTAGE SOURCE CONVERTER DATA")
    lines.append(
        "0 / END OF VOLTAGE SOURCE CONVERTER DATA, BEGIN IMPEDANCE CORRECTION DATA"
    )
    lines.append("0 / END OF IMPEDANCE CORRECTION DATA, BEGIN MULTI-TERMINAL DC DATA")
    lines.append("0 / END OF MULTI-TERMINAL DC DATA, BEGIN MULTI-SECTION LINE DATA")
    lines.append("0 / END OF MULTI-SECTION LINE DATA, BEGIN ZONE DATA")
    lines.append("0 / END OF ZONE DATA, BEGIN INTER-AREA TRANSFER DATA")
    lines.append("0 / END OF INTER-AREA TRANSFER DATA, BEGIN OWNER DATA")
    lines.append(f"    1,{_q('1', 12)}")
    lines.append("0 / END OF OWNER DATA, BEGIN FACTS CONTROL DEVICE DATA")
    lines.append("0 / END OF FACTS CONTROL DEVICE DATA, BEGIN SWITCHED SHUNT DATA")
    lines.append("0 /END OF SWITCHED SHUNT DATA, BEGIN GNE DEVICE DATA")
    lines.append("0 /END OF GNE DEVICE DATA")
    lines.append("Q")

    path.write_text("\n".join(lines) + "\n", encoding="latin-1")
