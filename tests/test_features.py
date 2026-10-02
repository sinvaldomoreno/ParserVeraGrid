"""Testes das funcionalidades posteriores a v0.1.

Cada teste de regressao aqui corresponde a um defeito real encontrado
durante a validacao contra decks do ONS/EPE; o comentario de cada um diz
qual. Nenhum dado de deck real e versionado: as fixtures sao sinteticas,
montadas a partir das especificacoes de coluna.
"""
from pathlib import Path

import pytest

from pwf2raw import PwfReader, write_raw
from pwf2raw import sections as sec
from pwf2raw.diagnostics import diagnose
from pwf2raw.model import (
    Branch, Bus, Generator, Load, Network, Transformer2W,
)
from pwf2raw.zbranch import floor_residual_impedance, merge_zero_impedance

DATA = Path(__file__).parent / "data"
MINI_DC = DATA / "mini_dc.pwf"


# ---------------------------------------------------------------------
# Leitura numerica e layout de colunas
# ---------------------------------------------------------------------

def test_is_parseable_number_rejects_lone_sign():
    assert sec.is_parseable_number("-200.")
    assert sec.is_parseable_number(".5")
    assert not sec.is_parseable_number("-")
    assert not sec.is_parseable_number(".")
    assert not sec.is_parseable_number("")


def test_alignment_symptoms_detect_split_number():
    # Regressao: no deck de 107 barras do CEPEL o reator '-200.' se partia
    # em Ql='-' + Sh='200.', e a area virava 110 - silenciosamente.
    line = " " * 67 + "-" + "200. "
    field = sec.Field("reactive_load", 64, 68)
    assert sec.alignment_symptoms(line, [field]) == ["reactive_load"]


def test_header_layout_reproduces_validated_dbar_mapping():
    header = ("(Num)OETGb(   nome   )Gl( V)( A)( Pg)( Qg)( Qn)( Qm)(Bc  )"
              "( Pl)( Ql)( Sh)Are(Vf)M(1)(2)")
    layout = sec.layout_from_header("DBAR", header, sec.DBAR)
    for name, default in sec.DBAR.items():
        assert (layout[name].start, layout[name].end) == (default.start, default.end), name


def test_header_layout_falls_back_without_header():
    assert sec.layout_from_header("DBAR", "", sec.DBAR) is sec.DBAR


# ---------------------------------------------------------------------
# Rede CC e shunts de linha
# ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def dc_net():
    return PwfReader(MINI_DC).parse()


def test_dc_link_power_comes_from_dccv_not_delo_base(dc_net):
    # Regressao: o campo 14-18 do DELO e a BASE do elo (1000 na fixture);
    # o ponto de operacao e o SPECIFIED VALUE do DCCV do retificador (80).
    link = dc_net.dc_links[0]
    assert link.mw == pytest.approx(80.0)
    assert link.r_ohm == pytest.approx(5.0)
    assert (link.rectifier.ac_bus, link.inverter.ac_bus) == (3, 4)
    assert link.in_service


def test_dc_status_override():
    off = PwfReader(MINI_DC, dc_status="off").parse()
    assert not any(lk.in_service for lk in off.dc_links)
    with pytest.raises(ValueError):
        PwfReader(MINI_DC, dc_status="talvez")


def test_dshl_creates_shunt_at_each_end(dc_net):
    line_shunts = {(s.bus, s.b) for s in dc_net.fixed_shunts if s.id == "L"}
    assert line_shunts == {(1, -10.0), (3, -5.0)}


def test_dc_link_written_as_dummy_generators(tmp_path, dc_net):
    out = tmp_path / "dc.raw"
    write_raw(dc_net, out)
    text = out.read_text(encoding="latin-1")
    gen_block = text.split("BEGIN GENERATOR DATA")[1].split("END OF GENERATOR DATA")[0]
    # identificados pela barra conversora e pela potencia, nao pelo rotulo:
    # o ID e atribuido por barra para garantir unicidade no RAW
    dc_buses = {dc_net.dc_links[0].rectifier.ac_bus,
                dc_net.dc_links[0].inverter.ac_bus}
    dummy = [l for l in gen_block.splitlines()
             if l.strip() and not l.startswith("0 ")
             and int(l.split(",")[0]) in dc_buses
             and abs(float(l.split(",")[2])) > 1e-6]
    assert len(dummy) == 2
    powers = sorted(float(l.split(",")[2]) for l in dummy)
    assert powers[0] == pytest.approx(-80.0)
    assert 0 < powers[1] <= 80.0  # inversor injeta P menos perdas


# ---------------------------------------------------------------------
# Escrita do RAW
# ---------------------------------------------------------------------

def _tiny_net():
    net = Network()
    for n, t in ((1, 3), (2, 1), (3, 1)):
        net.buses[n] = Bus(number=n, name=f"B{n}", base_kv=138.0, bus_type=t)
    net.generators.append(Generator(bus=1, id="1", pg=10, qg=0, qmin=-50,
                                    qmax=50, vs=1.0, pmin=0, pmax=100))
    net.loads.append(Load(bus=3, id="1", p=10, q=2))
    net.branches.append(Branch(from_bus=1, to_bus=2, ckt="1", r=0.01, x=0.1, b=0.0))
    net.branches.append(Branch(from_bus=2, to_bus=3, ckt="1", r=0.01, x=0.1, b=0.0,
                               in_service=False))
    return net


def test_out_of_service_branch_written_with_status_zero(tmp_path):
    # Regressao: a v0.1 gravava '1' fixo no campo ST e o status real no
    # campo MET, colocando em servico TODO ramo desligado do deck.
    out = tmp_path / "t.raw"
    write_raw(_tiny_net(), out)
    text = out.read_text(encoding="latin-1")
    rows = text.split("BEGIN BRANCH DATA")[1].split("END OF BRANCH DATA")[0]
    fields = {l.split(",")[0].strip() + "-" + l.split(",")[1].strip(): l.split(",")
              for l in rows.splitlines() if l.strip() and not l.startswith("0 ")}
    # ordem RAW rev33: I J CKT R X B RATEA RATEB RATEC GI BI GJ BJ ST ...
    assert fields["1-2"][13].strip() == "1"
    assert fields["2-3"][13].strip() == "0"


def test_ltc_written_only_when_enabled(tmp_path):
    net = _tiny_net()
    net.transformers.append(Transformer2W(
        from_bus=2, to_bus=3, ckt="1", r=0.0, x=0.05, windv1=1.0,
        ltc=True, tap_min=0.9, tap_max=1.1, controlled_bus=3, n_taps=33))
    on, off = tmp_path / "on.raw", tmp_path / "off.raw"
    write_raw(net, on)
    write_raw(net, off, ltc=False)

    def cod1(path):
        block = path.read_text().split("BEGIN TRANSFORMER DATA")[1]
        return block.splitlines()[3].split(",")[6].strip()  # registro 3, COD1
    assert cod1(on) == "1"
    assert cod1(off) == "0"


# ---------------------------------------------------------------------
# Fusao de nos de impedancia desprezivel
# ---------------------------------------------------------------------

def test_merge_zero_impedance_keeps_slack_and_remaps():
    net = _tiny_net()
    net.branches[1].in_service = True
    net.branches.append(Branch(from_bus=3, to_bus=4, ckt="1", r=0.0, x=1e-6, b=0.0))
    net.buses[4] = Bus(number=4, name="B4", base_kv=138.0, bus_type=1)
    net.loads.append(Load(bus=4, id="1", p=5, q=1))
    rep = merge_zero_impedance(net, 1e-4)
    assert rep.merged_buses == 1
    assert 4 not in net.buses and 3 in net.buses
    assert {l.bus for l in net.loads} == {3}
    assert net.buses[1].bus_type == 3


def test_transformer_with_off_nominal_tap_is_not_merged():
    # Um trafo ideal com tap != 1 nao pode ser fundido: a relacao de tensao
    # entre os nos e real. No deck EPE 2032_3, o trafo Foz 500 kV -> Itaipu
    # 525 kV (X = 0,001%, tap 1,05) sozinho dominava o residuo.
    net = _tiny_net()
    net.transformers.append(Transformer2W(from_bus=2, to_bus=3, ckt="1",
                                          r=0.0, x=1e-5, windv1=1.05))
    rep = merge_zero_impedance(net, 1e-4)
    assert rep.merged_buses == 0
    changed = floor_residual_impedance(net, 1e-4, 1e-3)
    assert len(changed) == 1 and net.transformers[0].x == pytest.approx(1e-3)


# ---------------------------------------------------------------------
# Diagnostico
# ---------------------------------------------------------------------

def test_dc_links_do_not_merge_ac_islands(dc_net):
    # Um elo CC e injecao de potencia, nao caminho CA: subsistemas ligados
    # so por CC sao ilhas CA distintas (por isso o deck EPE tem 4 slacks).
    # Na fixture, {1,3} e {2,4} sao ilhas CA e o elo liga 3 a 4.
    rep = diagnose(dc_net)
    ilhas = sorted(sorted(i.buses) for i in rep.energized_islands)
    assert ilhas == [[1, 3], [2, 4]]


# ---------------------------------------------------------------------
# Modulo DESSEM (relatorios sinteticos)
# ---------------------------------------------------------------------

@pytest.fixture
def deck(tmp_path):
    (tmp_path / "pdo_oper_term.dat").write_text(
        "legenda\n1;001;001;ANGRA;SE;3;60.0;x\n2;001;001;ANGRA;SE;3;40.0;x\n",
        encoding="latin-1")
    (tmp_path / "pdo_eolica.dat").write_text(
        "legenda\n1;1;EOL X;4;SE;999;1.0;30.0;30.0;\n", encoding="latin-1")
    (tmp_path / "pdo_hidr.dat").write_text(
        "cabecalho\nIPER;Pat;USIH;Nome;SIST;CONJ;Unid;MW;Gmax\n"
        "1;MEDIA;18;A. VERMELHA;SE;1;1;100.0;x\n"
        "1;MEDIA;18;A. VERMELHA;SE;1;2;50.0;x\n"
        "1;MEDIA;18;A. VERMELHA;SE;99;99;150.0;x\n"
        "49;MEDIA;18;A. VERMELHA;SE;99;99;999.0;x\n",
        encoding="latin-1")
    (tmp_path / "pdo_somflux.dat").write_text(
        "20;18;MEDIA;-;;18;Elo;-;-;-;120.0;-99999;3150;0;\n"
        "20;18;MEDIA;-;;18;Elo;4;-;-;120.0;-;-;-;\n",
        encoding="latin-1")
    return tmp_path


def _dusi_pwf(tmp_path):
    line = " " * 78
    line = list(line)
    line[6:11] = list("    1")        # barra 1
    line[12:24] = list("AGUA VERMELH")
    line[24:28] = list("   2")         # unidades
    line[72:76] = list("  18")         # codigo da usina
    line[77] = "H"
    p = tmp_path / "dusi.pwf"
    p.write_text("DUSI\n(No) cabecalho\n" + "".join(line) + "\n99999\nFIM\n",
                 encoding="latin-1")
    return p


def test_hydro_total_rows_are_not_double_counted(deck):
    # Regressao: a linha CONJ=99/Unid=99 e o TOTAL da usina. Somada junto
    # com as unidades, Itaipu saiu com 24.608 MW (o dobro de 12.304).
    from pwf2raw.dessem import read_hydro
    assert sum(read_hydro(deck, "1")[18].values()) == pytest.approx(150.0)


def test_dusi_matches_by_plant_code_not_name(tmp_path):
    # O DUSI grava 'AGUA VERMELH' e o pdo_hidr 'A. VERMELHA': por nome
    # falharia; o codigo 18 e o mesmo nos dois.
    from pwf2raw.dessem import read_dusi
    assert read_dusi(_dusi_pwf(tmp_path)) == {18: [(1, 2)]}


def test_dc_flow_from_single_bus_constraint(deck):
    from pwf2raw.dessem import read_dc_flows
    assert read_dc_flows(deck, "20") == {4: 120.0}


def test_apply_dc_dispatch_replaces_template_setpoint(deck):
    from pwf2raw.dessem import apply_dc_dispatch
    net = PwfReader(MINI_DC).parse()
    apply_dc_dispatch(net, deck, "20")
    assert net.dc_links[0].mw == pytest.approx(120.0)


def test_best_period_ignores_periods_beyond_the_day(deck):
    # Regressao: o periodo 51 (bloco agregado do horizonte seguinte) chegou
    # a ser escolhido para a pesada, prevendo +3,0% e resultando em -3,9%.
    from pwf2raw.dessem import best_period
    period, _ = best_period(deck, load_mw=900.0)
    assert int(period) <= 48


def test_apply_dispatch_with_curtailment(deck, tmp_path):
    from pwf2raw.dessem import apply_dispatch
    net = PwfReader(MINI_DC).parse()
    load = sum(l.p for l in net.loads if l.in_service)          # 50 MW
    rep = apply_dispatch(net, deck, period="1", pwf_path=_dusi_pwf(tmp_path),
                         curtail=True, dc_dispatch=False)
    assert rep.hydro_mw == pytest.approx(150.0)
    assert rep.thermal_mw == pytest.approx(60.0)
    # termica + hidro ja passam da carga: toda a renovavel e cortada
    assert rep.curtailed_mw == pytest.approx(30.0)
    assert rep.total_mw > load
