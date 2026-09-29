"""Diagnostico estrutural do caso lido, antes de gravar o RAW.

A conversao pode terminar "com sucesso" e ainda assim produzir um caso
insoluvel - por exemplo se o deck de origem nao tem despacho de
geracao, ou se os elos CC vem bloqueados e subsistemas inteiros ficam
ilhados. Este modulo procura exatamente esse tipo de problema e o
reporta em linguagem util para quem vai rodar o fluxo de potencia.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from .model import Network


@dataclass
class Island:
    buses: list[int]
    load_mw: float = 0.0
    gen_mw: float = 0.0
    has_slack: bool = False


@dataclass
class Report:
    low_x_histogram: dict = dc_field(default_factory=dict)
    low_x_total: int = 0
    total_load_mw: float = 0.0
    total_load_mvar: float = 0.0
    total_gen_mw: float = 0.0
    n_islands: int = 0
    energized_islands: list[Island] = dc_field(default_factory=list)
    out_of_service_buses: int = 0
    buses_missing_base_kv: int = 0
    problems: list[str] = dc_field(default_factory=list)

    def format(self) -> str:
        out = ["=== Diagnostico do caso ==="]
        out.append(
            f"Carga total.......: {self.total_load_mw:,.0f} MW / "
            f"{self.total_load_mvar:,.0f} Mvar"
        )
        out.append(f"Geracao total (Pg): {self.total_gen_mw:,.0f} MW")
        multi = [i for i in self.energized_islands if len(i.buses) > 1]
        out.append(f"Ilhas.............: {self.n_islands} ({len(multi)} com mais de uma barra)")
        out.append(f"Barras fora de servico: {self.out_of_service_buses}")
        if multi:
            out.append("Maiores ilhas:")
            for i in sorted(multi, key=lambda x: -len(x.buses))[:5]:
                flag = "OK" if i.has_slack else "SEM REFERENCIA"
                out.append(
                    f"  {len(i.buses):>6} barras  carga {i.load_mw:>10,.0f} MW"
                    f"  geracao {i.gen_mw:>10,.0f} MW  [{flag}]"
                )
        if self.low_x_total:
            out.append("")
            out.append(
                f"Ramos de impedancia desprezivel: {self.low_x_total} "
                f"(disjuntores/jumpers modelados com x ~ 0)"
            )
            for faixa, n in self.low_x_histogram.items():
                out.append(f"  |x| {faixa:<16} {n:>6}")
            out.append(
                "  Esses ramos sao fieis ao deck, mas dificultam a solucao "
                "no Newton-Raphson. Use --x-floor para impor um piso "
                "(atencao: isso MODIFICA a rede)."
            )
        if self.problems:
            out.append("")
            out.append("PROBLEMAS DETECTADOS:")
            for p in self.problems:
                out.append(f"  * {p}")
        return "\n".join(out)


def diagnose(net: Network) -> Report:
    rep = Report()
    rep.total_load_mw = sum(l.p for l in net.loads if l.in_service)
    rep.total_load_mvar = sum(l.q for l in net.loads if l.in_service)
    rep.total_gen_mw = sum(g.pg for g in net.generators if g.in_service)
    rep.out_of_service_buses = sum(1 for b in net.buses.values() if not b.in_service)
    rep.buses_missing_base_kv = sum(
        1 for b in net.buses.values() if b.base_kv == 1.0
    )

    parent = {b: b for b in net.buses}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for e in list(net.branches) + list(net.transformers):
        if e.in_service and e.from_bus in parent and e.to_bus in parent:
            union(e.from_bus, e.to_bus)

    # ATENCAO: elos CC NAO unem ilhas para efeito de fluxo de potencia CA.
    # Um elo CC e uma injecao de potencia nas duas pontas, nao um caminho
    # de corrente alternada. Por isso subsistemas ligados so por CC
    # (Itaipu 50 Hz, Madeira, Alumar no SIN) sao ilhas CA distintas e o
    # deck fornece uma barra de referencia para cada uma - o caso EPE
    # 2035 tem 4 slacks exatamente por isso. Registramos os pares apenas
    # para poder explicar o ilhamento ao usuario.
    dc_pairs: list[tuple[int, int]] = []
    for lk in net.dc_links:
        if lk.rectifier is None or lk.inverter is None:
            continue
        a, b = lk.rectifier.ac_bus, lk.inverter.ac_bus
        if a in parent and b in parent:
            dc_pairs.append((a, b))
    for v in net.vsc_links:
        a, b = v.rectifier_bus, v.inverter_bus
        if a in parent and b in parent:
            dc_pairs.append((a, b))

    groups: dict[int, list[int]] = {}
    for b in net.buses:
        groups.setdefault(find(b), []).append(b)

    load_by_bus: dict[int, float] = {}
    for l in net.loads:
        if l.in_service:
            load_by_bus[l.bus] = load_by_bus.get(l.bus, 0.0) + l.p
    gen_by_bus: dict[int, float] = {}
    slack = set()
    for g in net.generators:
        if g.in_service:
            gen_by_bus[g.bus] = gen_by_bus.get(g.bus, 0.0) + g.pg
    for n, b in net.buses.items():
        if b.bus_type == 3:
            slack.add(n)

    rep.n_islands = len(groups)
    for buses in groups.values():
        energized = [b for b in buses if net.buses[b].in_service]
        if not energized:
            continue
        rep.energized_islands.append(
            Island(
                buses=energized,
                load_mw=sum(load_by_bus.get(b, 0.0) for b in energized),
                gen_mw=sum(gen_by_bus.get(b, 0.0) for b in energized),
                has_slack=any(b in slack for b in energized),
            )
        )

    if rep.total_load_mw > 0 and rep.total_gen_mw == 0:
        rep.problems.append(
            f"O caso tem {rep.total_load_mw:,.0f} MW de carga e nenhuma "
            f"geracao ativa (campo Pg do DBAR vazio em todos os registros). "
            f"Isso e caracteristica do arquivo de entrada, nao do parser: "
            f"sem despacho o fluxo de potencia e insoluvel."
        )

    orphan = [i for i in rep.energized_islands if not i.has_slack and len(i.buses) > 1]
    if orphan:
        rep.problems.append(
            f"{len(orphan)} ilha(s) com mais de uma barra sem barra de "
            f"referencia (slack)."
        )

    faixas = [
        ("< 1e-6", 0.0, 1e-6),
        ("1e-6 a 1e-5", 1e-6, 1e-5),
        ("1e-5 a 1e-4", 1e-5, 1e-4),
        ("1e-4 a 1e-3", 1e-4, 1e-3),
    ]
    hist = {}
    for nome, lo, hi in faixas:
        n = sum(
            1
            for e in list(net.branches) + list(net.transformers)
            if e.in_service and lo <= abs(e.x) < hi
        )
        if n:
            hist[nome] = n
    rep.low_x_histogram = hist
    rep.low_x_total = sum(hist.values())

    dc_off = [lk for lk in net.dc_links if not lk.in_service]
    dc_off += [v for v in net.vsc_links if not v.in_service]
    if dc_off and dc_pairs:
        rep.problems.append(
            f"{len(dc_off)} elo(s) CC bloqueado(s). Como parte do sistema so "
            f"se conecta ao restante por CC, isso fragmenta a rede. "
            f"Reconverta com --dc-status on para energiza-los."
        )

    if rep.buses_missing_base_kv:
        rep.problems.append(
            f"{rep.buses_missing_base_kv} barra(s) sem tensao base resolvida "
            f"(grupo ausente no DGBT); gravadas com 1.0 kV."
        )

    return rep
