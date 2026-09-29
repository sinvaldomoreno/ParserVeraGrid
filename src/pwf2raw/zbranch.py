"""Fusao de nos ligados por ramos de impedancia desprezivel.

Motivacao
---------
Decks do ONS/EPE representam disjuntores, chaves e jumpers como ramos
com impedancia praticamente nula (r, x na casa de 1e-5 pu). Isso e
fiel ao equipamento, mas destroi o condicionamento da matriz de
admitancia: seis jumpers com r = x = 1e-5 pu convergindo numa mesma
barra produzem Ydiag da ordem de 3e5 pu, e ai um erro de tensao de
1e-5 pu ja gera varios pu de mismatch de potencia. Foi exatamente esse
efeito que dominou a norma infinita do residuo nos casos EPE que nao
convergiam (uma unica barra respondia por ~5e3 pu de mismatch).

O tratamento padrao (o mesmo que o PSS/E chama de "zero impedance
branch handling") nao e alterar a impedancia - isso mudaria a rede -
mas sim resolver o fluxo numa rede reduzida onde os nos ligados por
esses ramos viram um unico no equivalente, e depois redistribuir o
resultado. A fisica e preservada: como a impedancia e desprezivel, a
tensao e essencialmente a mesma em todos os nos do grupo.

O que este modulo faz
---------------------
1. Agrupa por union-find os barramentos ligados por ramos em servico
   com |z| < tolerancia.
2. Elege um representante por grupo (preferindo slack > PV > maior kV
   > menor numero), para nao perder a barra de referencia.
3. Remapeia cargas, geracao, shunts, ramos, transformadores e elos CC
   para o representante.
4. Remove os ramos de impedancia nula e os ramos que viraram laco.
5. Devolve o mapeamento no_original -> representante, para que a
   solucao possa ser redistribuida depois.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from .model import Network


@dataclass
class MergeReport:
    tolerance: float = 0.0
    merged_buses: int = 0
    groups: int = 0
    removed_branches: int = 0
    mapping: dict[int, int] = dc_field(default_factory=dict)

    def describe(self) -> str:
        if not self.groups:
            return (
                f"Nenhum ramo de impedancia abaixo de {self.tolerance:g} pu; "
                f"rede inalterada."
            )
        return (
            f"Fusao de nos: {self.merged_buses} barra(s) absorvida(s) em "
            f"{self.groups} no(s) equivalente(s), {self.removed_branches} "
            f"ramo(s) de impedancia < {self.tolerance:g} pu removido(s)."
        )


def _impedance(e) -> float:
    return (e.r * e.r + e.x * e.x) ** 0.5


def merge_zero_impedance(net: Network, tolerance: float = 1e-4) -> MergeReport:
    """Funde in-place os nos ligados por ramos de impedancia desprezivel."""
    rep = MergeReport(tolerance=tolerance)

    parent = {n: n for n in net.buses}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    zero_branches = []
    for e in net.branches:
        if not e.in_service:
            continue
        if e.from_bus not in parent or e.to_bus not in parent:
            continue
        if _impedance(e) < tolerance:
            zero_branches.append(e)
            union(e.from_bus, e.to_bus)

    # Transformadores de impedancia desprezivel com relacao de
    # transformacao unitaria e sem defasagem sao, eletricamente,
    # jumpers - e causam o mesmo mal-condicionamento. Um transformador
    # com tap != 1 NAO pode ser fundido: a relacao de tensao e real.
    zero_trafos = []
    for t in net.transformers:
        if not t.in_service:
            continue
        if t.from_bus not in parent or t.to_bus not in parent:
            continue
        if (
            _impedance(t) < tolerance
            and abs(t.windv1 - 1.0) < 1e-6
            and abs(t.windv2 - 1.0) < 1e-6
            and abs(t.angle) < 1e-6
        ):
            zero_trafos.append(t)
            union(t.from_bus, t.to_bus)

    if not zero_branches and not zero_trafos:
        return rep

    groups: dict[int, list[int]] = {}
    for n in net.buses:
        groups.setdefault(find(n), []).append(n)
    groups = {k: v for k, v in groups.items() if len(v) > 1}

    def rank(n: int):
        """Menor tupla vence. Preserva slack e PV como representante."""
        b = net.buses[n]
        type_rank = {3: 0, 2: 1, 1: 2, 4: 3}.get(b.bus_type, 4)
        return (type_rank, -b.base_kv, n)

    mapping: dict[int, int] = {}
    for members in groups.values():
        leader = min(members, key=rank)
        for n in members:
            mapping[n] = leader

    rep.groups = len(groups)
    rep.merged_buses = sum(len(v) - 1 for v in groups.values())
    rep.mapping = mapping

    def m(n: int) -> int:
        return mapping.get(n, n)

    # Uma barra absorvida herda o pior caso de disponibilidade: se
    # qualquer membro do grupo estiver energizado, o no equivalente esta.
    for members in groups.values():
        leader = mapping[members[0]]
        if any(net.buses[n].in_service for n in members):
            net.buses[leader].in_service = True

    for coll in (net.loads, net.fixed_shunts, net.generators, net.switched_shunts):
        for el in coll:
            el.bus = m(el.bus)

    for sh in net.switched_shunts:
        if sh.controlled_bus:
            sh.controlled_bus = m(sh.controlled_bus)

    for lk in net.dc_links:
        for c in (lk.rectifier, lk.inverter):
            if c is not None:
                c.ac_bus = m(c.ac_bus)
    for v in net.vsc_links:
        v.rectifier_bus = m(v.rectifier_bus)
        v.inverter_bus = m(v.inverter_bus)

    zero_ids = {id(e) for e in zero_branches} | {id(t) for t in zero_trafos}
    kept_branches = []
    for e in net.branches:
        if id(e) in zero_ids:
            continue
        e.from_bus, e.to_bus = m(e.from_bus), m(e.to_bus)
        if e.from_bus == e.to_bus:
            # virou laco depois da fusao: nao contribui para a rede
            continue
        kept_branches.append(e)
    rep.removed_branches = len(net.branches) - len(kept_branches)
    net.branches = kept_branches

    kept_trafos = []
    for t in net.transformers:
        if id(t) in zero_ids:
            continue
        t.from_bus, t.to_bus = m(t.from_bus), m(t.to_bus)
        if t.from_bus == t.to_bus:
            continue
        kept_trafos.append(t)
    net.transformers = kept_trafos

    for n in list(net.buses):
        if n in mapping and mapping[n] != n:
            del net.buses[n]

    net.add_warning(rep.describe())
    return rep


def redistribute(
    solution: dict[int, complex], report: MergeReport
) -> dict[int, complex]:
    """Devolve a solucao para os nos originais.

    Como a impedancia entre os nos do grupo e desprezivel, a tensao do
    no equivalente vale para todos os membros.
    """
    out = dict(solution)
    for original, leader in report.mapping.items():
        if leader in solution:
            out[original] = solution[leader]
    return out


def floor_residual_impedance(
    net: Network, tolerance: float = 1e-4, floor: float = 1e-4
) -> list[str]:
    """Impoe piso de reatancia aos elementos que a fusao nao absorve.

    Depois de `merge_zero_impedance`, sobram poucos elementos com
    impedancia desprezivel que NAO podem ser fundidos: transformadores
    ideais com tap != 1 (a relacao de tensao e real, os dois nos nao
    sao o mesmo ponto eletrico) e ramos com reatancia negativa
    (compensacao serie). No deck EPE 2032_3 sao 9 elementos em ~18 mil.

    Para esses, o tratamento usual e impor uma reatancia minima. Isso
    MODIFICA a rede, mas de forma cirurgica e rastreavel - devolvemos a
    lista do que foi alterado. Exemplo real: o transformador
    3633 -> 6649 (Foz 500 kV -> Itaipu-Foz 525 kV) tem X = 0.001% e
    tap 1.05 no deck; sozinho ele respondia por ~4780 pu de mismatch.
    """
    changed: list[str] = []
    for e in net.branches:
        if e.in_service and 0 <= abs(e.x) < tolerance:
            changed.append(
                f"linha {e.from_bus}->{e.to_bus} ckt {e.ckt}: "
                f"x {e.x:.2e} -> {floor:.2e}"
            )
            e.x = floor if e.x >= 0 else -floor
    for t in net.transformers:
        if t.in_service and abs(t.x) < tolerance:
            changed.append(
                f"trafo {t.from_bus}->{t.to_bus} ckt {t.ckt} (tap "
                f"{t.windv1:g}): x {t.x:.2e} -> {floor:.2e}"
            )
            t.x = floor
    return changed
