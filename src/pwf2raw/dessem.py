"""Aplica o despacho calculado pelo DESSEM a uma rede lida de um .pwf.

Por que este modulo existe
--------------------------
Os arquivos .pwf de um deck DESSEM do ONS (leve/media/pesada) NAO tem
ponto de operacao: o campo Pg do DBAR vem vazio em todos os registros e
os elos CC vem bloqueados. Isso nao e deck incompleto - e o papel do
arquivo no fluxo de trabalho. O .pwf e a *entrada* de rede do DESSEM; o
despacho e a *saida* dele, e fica nos relatorios pdo_*.dat.

Sem juntar as duas partes, converter o .pwf sozinho produz um caso com
carga e sem geracao, que nenhum fluxo de potencia resolve.

Fontes de despacho, por barra
-----------------------------
- `pdo_oper_term.dat`: geracao termica. Traz a coluna NumBarra, que casa
  diretamente com a numeracao do .pwf (ex.: ANGRA 1 na barra 10, com
  GTER 640 MW, e a barra ANGRA1UNE001 cujo DGER traz Pmax 640).
- `pdo_eolica.dat`: geracao eolica, fotovoltaica e MMGD agregada. Traz a
  coluna Barra. E a maior fatia mapeavel: ~31 GW em ~3.100 pontos de
  conexao no caso de setembro/2026.

A geracao hidraulica fica em `pdo_hidr.dat`, mas identificada por usina
(USIH + nome), sem numero de barra - o mapeamento depende de cruzar com
o bloco DUSI do proprio .pwf, por nome, e ainda nao esta implementado
aqui. Por isso `apply_dispatch` devolve um relatorio dizendo quanto da
carga ficou coberta: sem a hidraulica, o caso continua incompleto.

Nota sobre o balanco de carga
-----------------------------
A carga do .pwf e BRUTA. As renovaveis sao abatidas dela para formar a
carga liquida, que e o que o despacho hidrotermico cobre. Entao comparar
so a termica com a carga bruta subestima grosseiramente a cobertura - a
eolica/FV responde por cerca de 30% no caso analisado.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from pathlib import Path

from .model import Generator, Network


@dataclass
class DispatchReport:
    thermal_mw: float = 0.0
    renewable_mw: float = 0.0
    thermal_buses: int = 0
    renewable_buses: int = 0
    matched_buses: int = 0
    unmatched_buses: list[int] = dc_field(default_factory=list)
    load_mw: float = 0.0
    hydro_mw: float = 0.0
    hydro_plants: int = 0
    hydro_unmatched: list[int] = dc_field(default_factory=list)
    curtailed_mw: float = 0.0
    dc_log: list[str] = dc_field(default_factory=list)

    @property
    def total_mw(self) -> float:
        return self.thermal_mw + self.renewable_mw + self.hydro_mw

    def describe(self) -> str:
        cover = 100 * self.total_mw / self.load_mw if self.load_mw else 0.0
        out = [
            f"Despacho DESSEM aplicado: {self.total_mw:,.0f} MW "
            f"({self.thermal_mw:,.0f} MW termica em {self.thermal_buses} barras, "
            f"{self.renewable_mw:,.0f} MW eolica/FV/PCH em {self.renewable_buses} barras, "
            f"{self.hydro_mw:,.0f} MW hidraulica em {self.hydro_plants} usinas)",
            f"Carga bruta da rede: {self.load_mw:,.0f} MW "
            f"-> cobertura de {cover:.0f}%",
        ]
        if self.unmatched_buses:
            out.append(
                f"{len(self.unmatched_buses)} barra(s) do despacho nao existem "
                f"na rede e foram ignoradas: {self.unmatched_buses[:8]}"
            )
        if self.hydro_unmatched:
            out.append(
                f"{len(self.hydro_unmatched)} usina(s) hidraulica(s) com "
                f"geracao e sem barra no DUSI: {self.hydro_unmatched[:8]}"
            )
        if not self.hydro_mw:
            out.append(
                "Hidraulica nao aplicada: passe pwf_path para cruzar o "
                "pdo_hidr.dat com o bloco DUSI do .pwf."
            )
        if self.load_mw:
            saldo = self.total_mw - self.load_mw
            rel = saldo / self.load_mw
            msg = (f"Saldo geracao - carga bruta: {saldo:+,.0f} MW "
                   f"({100 * rel:+.1f}%).")
            if rel < 0.0:
                msg += (" DEFICIT de geracao: o periodo do despacho "
                        "provavelmente nao corresponde ao patamar de carga "
                        "deste .pwf.")
            elif rel > 0.06:
                msg += (" Excedente acima das perdas. Esperado quando ha "
                        "curtailment no tempo real, que nao aparece no "
                        "resultado inicial do DESSEM; use --curtail para "
                        "corta-lo nas renovaveis em vez de joga-lo na slack.")
            out.append(msg)
        if self.dc_log:
            out.append("Elos CC ajustados ao despacho (pdo_somflux):")
            out.extend(f"  - {l}" for l in self.dc_log)
        if self.curtailed_mw:
            out.append(
                f"Curtailment aplicado: {self.curtailed_mw:,.0f} MW cortados "
                f"da geracao renovavel (proporcional, hidro e termica "
                f"intactas)."
            )
        return "\n".join(out)


def _read_period(path: Path, bus_col: int, gen_col: int, period: str = "1"):
    """Le um relatorio pdo_*.dat delimitado por ';' para um periodo.

    Os relatorios tem dezenas de linhas de cabecalho e legenda; as linhas
    de dado sao as que comecam com o indice de periodo numerico.
    """
    out: dict[int, float] = {}
    total = 0.0
    with open(path, encoding="latin-1") as fh:
        for line in fh:
            parts = [x.strip() for x in line.split(";")]
            if len(parts) <= max(bus_col, gen_col):
                continue
            if not parts[0].isdigit() or parts[0] != period:
                continue
            try:
                bus = int(parts[bus_col])
                mw = float(parts[gen_col])
            except ValueError:
                continue
            out[bus] = out.get(bus, 0.0) + mw
            total += mw
    return total, out


def read_thermal(deck_dir: str | Path, period: str = "1"):
    """pdo_oper_term.dat: IPER;USIT;UNIDT;Nome;Sist;NumBarra;GTER;..."""
    return _read_period(Path(deck_dir) / "pdo_oper_term.dat", 5, 6, period)


def read_renewable(deck_dir: str | Path, period: str = "1"):
    """pdo_eolica.dat: IPER;NUM;Nome;Barra;Submerc;Potencia;FatCap;Geracao;..."""
    return _read_period(Path(deck_dir) / "pdo_eolica.dat", 3, 7, period)


def read_hydro(deck_dir: str | Path, period: str = "1"):
    """pdo_hidr.dat: geracao por usina (codigo USIH) e por conjunto.

    O relatorio traz uma linha por unidade geradora e, ao final de cada
    usina, uma linha de TOTAL marcada com CONJ = 99 e Unid = 99. Como
    '99' e numerico, somar tudo conta cada usina em dobro - foi o que
    fez Itaipu aparecer com 24.608 MW (o dobro dos 12.304 reais) numa
    primeira tentativa. As linhas de total sao descartadas aqui.

    Retorna {codigo: {conjunto: MW}}.
    """
    lines = (Path(deck_dir) / "pdo_hidr.dat").read_text(
        encoding="latin-1"
    ).splitlines()
    hi = next(i for i, l in enumerate(lines) if l.strip().startswith("IPER"))
    cols = [c.strip() for c in lines[hi].split(";")]
    gcol = cols.index("MW")  # primeira coluna em MW e a de Geracao
    out: dict[int, dict[int, float]] = {}
    for line in lines[hi + 1:]:
        p = [x.strip() for x in line.split(";")]
        if len(p) <= gcol or p[0] != period:
            continue
        if not (p[5].isdigit() and p[6].isdigit()):
            continue
        if p[5] == "99" or p[6] == "99":
            continue  # linha de total da usina
        try:
            code, conj, mw = int(p[2]), int(p[5]), float(p[gcol])
        except ValueError:
            continue
        out.setdefault(code, {})
        out[code][conj] = out[code].get(conj, 0.0) + mw
    return out


def read_dusi(pwf_path: str | Path):
    """Bloco DUSI do .pwf: codigo da usina hidraulica -> [(barra, unidades)].

    Colunas derivadas do cabecalho do proprio bloco:
      8-11 barra, 13-24 nome, 25-28 unidades, 73-76 codigo, 78 tipo.
    O codigo (73-76) e o mesmo USIH do DESSEM - Agua Vermelha e 18 nos
    dois arquivos. Casar por NOME falharia: o DUSI grava 'AGUA VERMELH' e
    o pdo_hidr grava 'A. VERMELHA'.
    """
    out: dict[int, list[tuple[int, int]]] = {}
    inside = False
    with open(pwf_path, encoding="latin-1") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            if line.startswith("DUSI"):
                inside = True
                continue
            if inside and line.strip() == "99999":
                break
            if not inside or line.startswith("(") or len(line) < 78:
                continue
            if line[77:78] != "H":
                continue
            try:
                bus = int(line[6:11])
                code = int(line[72:76])
            except ValueError:
                continue
            try:
                units = int(line[24:28])
            except ValueError:
                units = 1
            out.setdefault(code, []).append((bus, max(units, 1)))
    return out


def period_totals(deck_dir: str | Path) -> dict[int, tuple[str, float]]:
    """Geracao total (hidro + termica + renovavel) e patamar de cada periodo.

    Usa as linhas de total (CONJ=99) do pdo_hidr para a hidraulica.
    """
    deck_dir = Path(deck_dir)
    lines = (deck_dir / "pdo_hidr.dat").read_text(encoding="latin-1").splitlines()
    hi = next(i for i, l in enumerate(lines) if l.strip().startswith("IPER"))
    gcol = [c.strip() for c in lines[hi].split(";")].index("MW")
    tot: dict[int, float] = {}
    pat: dict[int, str] = {}
    for line in lines[hi + 1:]:
        p = [x.strip() for x in line.split(";")]
        if len(p) <= gcol or not p[0].isdigit():
            continue
        if p[5] != "99" or p[6] != "99":
            continue
        try:
            i = int(p[0])
            tot[i] = tot.get(i, 0.0) + float(p[gcol])
            pat[i] = p[1].upper()
        except ValueError:
            pass
    for fn, bcol, gcol2 in (("pdo_oper_term.dat", 5, 6), ("pdo_eolica.dat", 3, 7)):
        with open(deck_dir / fn, encoding="latin-1") as fh:
            for line in fh:
                p = [x.strip() for x in line.split(";")]
                if len(p) <= gcol2 or not p[0].isdigit():
                    continue
                try:
                    i = int(p[0])
                    tot[i] = tot.get(i, 0.0) + float(p[gcol2])
                except ValueError:
                    pass
    return {i: (pat.get(i, "?"), v) for i, v in tot.items() if i in pat}


def best_period(
    deck_dir: str | Path, load_mw: float, patamar: str | None = None,
    loss_margin: float = 0.03,
) -> tuple[str, float]:
    """Escolhe o periodo cuja geracao total mais se aproxima da carga.

    POR QUE ISTO E NECESSARIO: o rotulo de patamar do DESSEM nao
    identifica um instante. No deck de set/2026 o rotulo MEDIA aparece
    tanto de madrugada (IPER 1-2, ~81 GW, 31 GW de renovavel) quanto ao
    meio-dia (IPER 20-28, ~106-110 GW, 71-75 GW de renovavel com solar).
    O media.pwf tem 104.386 MW de carga bruta: casa com o meio-dia
    (+1.6% a +5.4%, faixa de perdas), e NAO com o periodo 1 (-20%).

    Alvo: carga * (1 + loss_margin). Retorna (periodo, saldo_relativo).
    """
    target = load_mw * (1.0 + loss_margin)
    # Apenas os 48 periodos semi-horarios do dia de estudo. Periodos
    # acima de 48 existem no relatorio mas cobrem o horizonte seguinte em
    # blocos agregados: no deck de set/2026 o periodo 51 foi escolhido
    # para a pesada com previsao de +3.0% e, aplicado, deu -3.9%.
    cands = [
        (i, v) for i, (pt, v) in period_totals(deck_dir).items()
        if i <= 48 and (patamar is None or pt == patamar.upper())
    ]
    if not cands:
        raise ValueError(f"nenhum periodo com patamar {patamar!r}")
    i, v = min(cands, key=lambda iv: abs(iv[1] - target))
    return str(i), (v - load_mw) / load_mw


def apply_dispatch(
    net: Network,
    deck_dir: str | Path,
    period: str = "1",
    pwf_path: str | Path | None = None,
    curtail: bool = False,
    loss_margin: float = 0.03,
    dc_dispatch: bool = True,
) -> DispatchReport:
    """Injeta o despacho do DESSEM na rede, in-place.

    curtail: se True e a geracao exceder carga*(1+loss_margin), reduz a
    geracao renovavel (eolica/FV/PCH do pdo_eolica) proporcionalmente ate
    fechar o balanco. Hidraulica e termica nao sao tocadas.

    Por que isso e legitimo: o resultado inicial do DESSEM NAO contem o
    curtailment que ocorre no tempo real, que e elevado. Geracao acima da
    carga no pdo e, portanto, esperada - nao e erro do deck nem da
    conversao. Sem cortar, todo o excedente vai para a barra slack (no
    leve.pwf de set/2026 seriam ~10 GW), o que e irreal e dificulta a
    solucao do fluxo de potencia.

    Para cada barra com despacho: se ja existe gerador, ajusta seu Pg; se
    nao existe, cria um com Q livre. Barras do despacho que nao existem
    na rede sao ignoradas e reportadas - nunca inventadas.
    """
    rep = DispatchReport()
    rep.load_mw = sum(l.p for l in net.loads if l.in_service)

    ter_tot, ter = read_thermal(deck_dir, period)
    eol_tot, eol = read_renewable(deck_dir, period)
    rep.thermal_mw, rep.thermal_buses = ter_tot, len(ter)
    rep.renewable_mw, rep.renewable_buses = eol_tot, len(eol)

    combined: dict[int, float] = dict(ter)

    # --- hidraulica: por codigo de usina, via DUSI
    if pwf_path is not None:
        hydro = read_hydro(deck_dir, period)
        dusi = read_dusi(pwf_path)
        for code, conjs in hydro.items():
            total = sum(conjs.values())
            rep.hydro_mw += total
            buses = dusi.get(code)
            if not buses:
                if total > 0:
                    rep.hydro_unmatched.append(code)
                continue
            rep.hydro_plants += 1
            if len(buses) == len(conjs):
                # uma barra por conjunto, na mesma ordem (ex.: Itaipu:
                # conj 1 -> 1100 ITAIPU 50 HZ, conj 2 -> 1107 ITAIPU 60 HZ)
                for (bus, _), conj in zip(buses, sorted(conjs)):
                    combined[bus] = combined.get(bus, 0.0) + conjs[conj]
            else:
                # reparte pela quantidade de unidades de cada barra
                n_units = sum(u for _, u in buses)
                for bus, u in buses:
                    combined[bus] = combined.get(bus, 0.0) + total * u / n_units

    # --- renovavel, com curtailment opcional
    if curtail and rep.load_mw:
        target = rep.load_mw * (1.0 + loss_margin)
        others = sum(combined.values())  # termica + hidraulica ja somadas
        excess = others + eol_tot - target
        if excess > 0 and eol_tot > 0:
            factor = max(0.0, (eol_tot - excess) / eol_tot)
            rep.curtailed_mw = eol_tot * (1.0 - factor)
            eol = {b: mw * factor for b, mw in eol.items()}
            rep.renewable_mw = eol_tot * factor
    for b, mw in eol.items():
        combined[b] = combined.get(b, 0.0) + mw

    by_bus: dict[int, list[Generator]] = {}
    for g in net.generators:
        by_bus.setdefault(g.bus, []).append(g)

    for bus, mw in combined.items():
        if bus not in net.buses:
            rep.unmatched_buses.append(bus)
            continue
        rep.matched_buses += 1
        gens = by_bus.get(bus)
        if gens:
            # distribui proporcionalmente a capacidade, ou igualmente
            caps = [g.pmax if g.pmax and g.pmax < 9000 else 0.0 for g in gens]
            total_cap = sum(caps)
            for g, cap in zip(gens, caps):
                g.pg = mw * cap / total_cap if total_cap else mw / len(gens)
        else:
            net.generators.append(
                Generator(
                    bus=bus, id="D", pg=mw, qg=0.0,
                    qmin=-9999.0, qmax=9999.0,
                    vs=net.buses[bus].vm, pmin=0.0, pmax=max(mw * 1.2, 1.0),
                    in_service=net.buses[bus].in_service,
                )
            )

    if dc_dispatch:
        rep.dc_log = apply_dc_dispatch(net, deck_dir, period)

    net.add_warning(rep.describe())
    return rep


def read_dc_flows(deck_dir: str | Path, period: str) -> dict[int, float]:
    """Fluxo despachado em cada elo CC, a partir das inequacoes de controle.

    pdo_somflux.dat lista as restricoes de somatorio de fluxo do DESSEM
    (as 'inequacoes de controle' do ONS): a primeira linha de cada
    restricao traz o valor despachado e os limites; as seguintes, as
    barras que participam. Quando uma restricao envolve UMA unica barra
    e essa barra e o terminal inversor de um elo CC, o valor e o fluxo
    daquele grupo de elos.

    Verificado no deck de set/2026, periodo 20: a restricao '& BIPS'
    soma os quatro inversores e bate exatamente com os valores
    individuais (2676 + 1203.041 - 1.6 + 197.9 = 4075.341).

    Retorna {barra_inversora: MW}.
    """
    groups: dict[str, list[list[str]]] = {}
    with open(Path(deck_dir) / "pdo_somflux.dat", encoding="latin-1") as fh:
        for line in fh:
            r = [x.strip() for x in line.split(";")]
            if len(r) > 12 and r[0].isdigit() and r[0] == period:
                groups.setdefault(r[1], []).append(r)
    flows: dict[int, float] = {}
    for rows in groups.values():
        buses = {int(r[7]) for r in rows if r[7].isdigit()}
        if len(buses) != 1:
            continue
        try:
            value = float(rows[0][10])
        except ValueError:
            continue
        flows.setdefault(next(iter(buses)), value)
    return flows


def apply_dc_dispatch(
    net: Network, deck_dir: str | Path, period: str
) -> list[str]:
    """Substitui os setpoints de template dos elos CC pelo despacho real.

    Os .pwf do DESSEM trazem no DCCV setpoints de placeholder: no deck de
    set/2026, Foz-Ibiuna 4 x 330 = 1.320 MW e Madeira 4 x 500 = 2.000 MW,
    contra 2.676 MW e 1.203 MW despachados no periodo 20. Forcar os elos
    com o template impunha fluxos incompativeis com o despacho de geracao.

    O fluxo do grupo e dividido igualmente entre os polos que compartilham
    o mesmo inversor. Elos sem restricao correspondente (Garabi, Alumar)
    mantem o valor do template. Retorna um log do que foi alterado.
    """
    flows = read_dc_flows(deck_dir, period)
    poles: dict[int, list] = {}
    for lk in net.dc_links:
        if lk.inverter is not None:
            poles.setdefault(lk.inverter.ac_bus, []).append(lk)
    log = []
    for bus, links in poles.items():
        if bus not in flows:
            continue
        total = flows[bus]
        # Fluxo pequeno, positivo ou negativo, e elo praticamente parado:
        # Xingu-Estreito vem com -1.6 MW no periodo 20. Tratar isso como
        # "sentido reverso" e manter o template (500 MW) seria muito pior
        # do que zerar. So um fluxo negativo relevante indica reversao de
        # verdade, que este modelo de geradores dummy nao representa.
        if total < -50.0:
            log.append(
                f"inversor {bus}: fluxo {total:.1f} MW em sentido reverso - "
                f"nao suportado, elo mantido no template"
            )
            continue
        per_pole = max(total, 0.0) / len(links)
        for lk in links:
            old = lk.mw
            lk.mw = per_pole
            lk.in_service = per_pole > 1.0
        log.append(
            f"inversor {bus}: {len(links)} polo(s), template "
            f"{old * len(links):,.0f} MW -> despacho {total:,.1f} MW"
        )
    return log
