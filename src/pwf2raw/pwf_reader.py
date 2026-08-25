"""Leitor do formato ANAREDE (.pwf) -> modelo intermediário `Network`.

Cobertura atual (v0.1): DBAR, DGBT, DLIN, DGER.
Ver `sections.SECTIONS_KNOWN_NOT_IMPLEMENTED` e docs/FORMAT_NOTES.md
para o que falta (shunts chaveáveis, HVDC, compensadores, controle de
tap detalhado etc.)
"""
from __future__ import annotations

import logging
from pathlib import Path

from . import sections as sec
from .model import (
    Branch,
    Bus,
    FixedShunt,
    Generator,
    Load,
    Network,
    Transformer2W,
)

logger = logging.getLogger(__name__)

# Todos os códigos de seção de 4 letras que reconhecemos como início de
# bloco (mesmo os que ainda não interpretamos), para não confundir uma
# linha de dados com um novo cabeçalho.
_ALL_SECTION_CODES = sec.SECTIONS_IMPLEMENTED | set(
    sec.SECTIONS_KNOWN_NOT_IMPLEMENTED
) | {"TITU", "FAGR", "DOPC", "DTPF"}


def _iter_lines(path: str | Path):
    with open(path, "r", encoding="latin-1", newline="") as f:
        for raw_line in f:
            yield raw_line.rstrip("\r\n")


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    """Agrupa as linhas de dados de cada seção reconhecida.

    Ignora a(s) linha(s) de comentário (iniciadas por '(') logo após o
    cabeçalho, e para de coletar ao encontrar o terminador '99999' ou o
    início de outra seção reconhecida.
    """
    blocks: dict[str, list[str]] = {}
    current = None
    for line in lines:
        code4 = line[:4]
        if code4 in _ALL_SECTION_CODES and (len(line) == 4 or line[4:5] in (" ", "")):
            current = code4
            blocks.setdefault(current, [])
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped == "99999":
            current = None
            continue
        if stripped.startswith("("):
            # linha de comentário / cabeçalho de campos
            continue
        if stripped == "":
            continue
        blocks[current].append(line)
    return blocks


def _parse_dgbt(lines: list[str]) -> dict[str, float]:
    """DGBT usa formato solto (separado por espaço), não fixed-width."""
    group_kv: dict[str, float] = {}
    for line in lines:
        parts = line.split()
        if len(parts) < 2:
            continue
        code, kv_txt = parts[0], parts[1]
        try:
            kv = float(kv_txt.rstrip("."))
        except ValueError:
            continue
        group_kv[code] = kv
    return group_kv


def _bus_type_from_anarede(t: int | None) -> int:
    """Converte tipo de barra ANAREDE -> convenção PSS/E.

    ANAREDE: 0=PQ, 1=PV, 2=referência(slack), 3=PQ c/ limite de tensão
    PSS/E:   1=PQ, 2=PV, 3=slack,             4=isolada
    """
    if t is None or t == 0:
        return 1
    if t == 1:
        return 2
    if t == 2:
        return 3
    if t == 3:
        # PQ com limite de tensão: RAW não tem equivalente direto;
        # tratamos como PQ comum e avisamos.
        return 1
    return 1


class PwfReader:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def parse(self) -> Network:
        lines = list(_iter_lines(self.path))
        blocks = _split_sections(lines)
        net = Network(case_name=self.path.stem)

        group_kv = _parse_dgbt(blocks.get("DGBT", []))
        if not group_kv:
            net.add_warning(
                "Seção DGBT não encontrada ou vazia: bases de tensão (kV) "
                "das barras não puderam ser resolvidas a partir dos "
                "códigos de grupo; base_kv será gravada como 1.0 kV."
            )

        self._parse_dbar(blocks.get("DBAR", []), group_kv, net)
        self._parse_dger(blocks.get("DGER", []), net)
        self._parse_dlin(blocks.get("DLIN", []), net)

        for code in sec.SECTIONS_KNOWN_NOT_IMPLEMENTED:
            if code in blocks and blocks[code]:
                net.add_warning(
                    f"Seção {code} presente no arquivo ({len(blocks[code])} "
                    f"registro(s)) mas ainda não é interpretada por este "
                    f"parser: {sec.SECTIONS_KNOWN_NOT_IMPLEMENTED[code]}."
                )

        return net

    # -- DBAR ------------------------------------------------------
    def _parse_dbar(
        self, lines: list[str], group_kv: dict[str, float], net: Network
    ) -> None:
        f = sec.DBAR
        for line in lines:
            number = sec.integer(line, f["number"])
            if number is None:
                continue
            name = sec.text(line, f["name"]) or f"BUS {number}"
            state = sec.text(line, f["state"]) or "L"
            btype = sec.integer(line, f["type"], default=0)
            group = sec.text(line, f["voltage_base_group"]) or "0"
            base_kv = group_kv.get(group, 1.0)
            vm = sec.number(line, f["voltage"], default=1.0)
            va = sec.number(line, f["angle"], default=0.0)
            area = sec.integer(line, f["area"], default=1)

            bus = Bus(
                number=number,
                name=name[:12],
                base_kv=base_kv,
                vm=vm,
                va=va,
                bus_type=_bus_type_from_anarede(btype),
                area=area if area else 1,
                in_service=(state.upper() != "D"),
            )
            net.buses[number] = bus

            pl = sec.number(line, f["active_load"])
            ql = sec.number(line, f["reactive_load"])
            if pl or ql:
                net.loads.append(
                    Load(bus=number, id="1", p=pl or 0.0, q=ql or 0.0)
                )

            bc = sec.number(line, f["capacitor_reactor"])
            if bc:
                net.fixed_shunts.append(
                    FixedShunt(bus=number, id="1", g=0.0, b=bc)
                )

            pg = sec.number(line, f["active_generation"])
            qg = sec.number(line, f["reactive_generation"])
            qn = sec.number(line, f["min_reactive_generation"])
            qx = sec.number(line, f["max_reactive_generation"])
            if bus.bus_type in (2, 3) or pg or qg:
                # Barra de geração (PV/slack) ou com Pg/Qg declarados.
                net.generators.append(
                    Generator(
                        bus=number,
                        id="1",
                        pg=pg or 0.0,
                        qg=qg or 0.0,
                        qmin=qn if qn is not None else -9999.0,
                        qmax=qx if qx is not None else 9999.0,
                        vs=vm,
                        pmin=0.0,
                        pmax=9999.0,
                    )
                )

    # -- DGER (limites de geração ativa, casa com DBAR pelo nº da barra)
    def _parse_dger(self, lines: list[str], net: Network) -> None:
        f = sec.DGER
        limits: dict[int, tuple[float, float]] = {}
        for line in lines:
            number = sec.integer(line, f["number"])
            if number is None:
                continue
            pmin = sec.number(line, f["min_active_generation"], default=0.0)
            pmax = sec.number(line, f["max_active_generation"], default=9999.0)
            limits[number] = (pmin or 0.0, pmax if pmax else 9999.0)

        for gen in net.generators:
            if gen.bus in limits:
                gen.pmin, gen.pmax = limits[gen.bus]

    # -- DLIN (linhas e transformadores de 2 enrolamentos) ----------
    def _parse_dlin(self, lines: list[str], net: Network) -> None:
        f = sec.DLIN
        for line in lines:
            fb = sec.integer(line, f["from_bus"])
            tb = sec.integer(line, f["to_bus"])
            if fb is None or tb is None:
                continue
            ckt_num = sec.integer(line, f["circuit"], default=1)
            ckt = str(ckt_num if ckt_num is not None else 1)
            state = sec.text(line, f["state"]) or "L"

            r_pct = sec.number(line, f["resistance"], default=0.0) or 0.0
            x_pct = sec.number(line, f["reactance"], default=0.0) or 0.0
            b_mvar = sec.number(line, f["susceptance"], default=0.0) or 0.0
            tap = sec.number(line, f["tap"])
            phase = sec.number(line, f["phase_shift"])

            r = r_pct / 100.0
            x = x_pct / 100.0
            b = b_mvar / net.sbase

            rate_a = sec.number(line, f["normal_capacity"], default=0.0) or 0.0
            rate_b = (
                sec.number(line, f["emergency_capacity"], default=rate_a) or rate_a
            )
            rate_c = (
                sec.number(line, f["equipment_capacity"], default=rate_b) or rate_b
            )

            in_service = state.upper() != "D"

            from_bus = net.buses.get(fb)
            to_bus = net.buses.get(tb)
            is_transformer = False
            if tap is not None and tap not in (0.0,):
                is_transformer = True
            elif (
                from_bus
                and to_bus
                and from_bus.base_kv
                and to_bus.base_kv
                and abs(from_bus.base_kv - to_bus.base_kv) > 1e-6
            ):
                is_transformer = True

            if is_transformer:
                net.transformers.append(
                    Transformer2W(
                        from_bus=fb,
                        to_bus=tb,
                        ckt=ckt,
                        r=r,
                        x=x,
                        windv1=tap if tap else 1.0,
                        angle=phase or 0.0,
                        windv2=1.0,
                        rate_a=rate_a,
                        rate_b=rate_b,
                        rate_c=rate_c,
                        in_service=in_service,
                    )
                )
            else:
                net.branches.append(
                    Branch(
                        from_bus=fb,
                        to_bus=tb,
                        ckt=ckt,
                        r=r,
                        x=x,
                        b=b,
                        rate_a=rate_a,
                        rate_b=rate_b,
                        rate_c=rate_c,
                        in_service=in_service,
                    )
                )
