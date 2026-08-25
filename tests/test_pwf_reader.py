from pathlib import Path

import pytest

from pwf2raw.pwf_reader import PwfReader

FIXTURE = Path(__file__).parent / "data" / "mini_4bus.pwf"


@pytest.fixture(scope="module")
def net():
    return PwfReader(FIXTURE).parse()


def test_bus_count_and_types(net):
    assert len(net.buses) == 4
    assert net.buses[1].bus_type == 3  # slack (ANAREDE tipo 2)
    assert net.buses[2].bus_type == 2  # PV (ANAREDE tipo 1)
    assert net.buses[3].bus_type == 1  # PQ
    assert net.buses[4].bus_type == 1  # PQ


def test_bus_base_kv_from_dgbt(net):
    assert net.buses[1].base_kv == 138.0
    assert net.buses[4].base_kv == 69.0


def test_loads(net):
    loads = {ld.bus: ld for ld in net.loads}
    assert loads[3].p == 30.0
    assert loads[3].q == 15.0
    assert loads[4].p == 20.0
    assert loads[4].q == 8.0


def test_fixed_shunt(net):
    assert len(net.fixed_shunts) == 1
    sh = net.fixed_shunts[0]
    assert sh.bus == 4
    assert sh.b == 5.0


def test_generators_pick_up_dger_limits(net):
    gens = {g.bus: g for g in net.generators}
    assert gens[1].pmax == 120.0  # slack, vindo do DGER
    assert gens[2].pmax == 80.0  # PV, vindo do DGER
    assert gens[2].pg == 50.0
    assert gens[2].qg == 10.0


def test_branch_vs_transformer_classification(net):
    # bus1 (138 kV) -- bus3 (138 kV), sem tap => linha
    assert len(net.branches) == 1
    br = net.branches[0]
    assert (br.from_bus, br.to_bus) == (1, 3)
    assert br.r == pytest.approx(0.015)
    assert br.x == pytest.approx(0.08)

    # bus2 (138 kV) -- bus4 (69 kV), com tap => transformador
    assert len(net.transformers) == 1
    tr = net.transformers[0]
    assert (tr.from_bus, tr.to_bus) == (2, 4)
    assert tr.windv1 == pytest.approx(0.98)


def test_no_warnings_for_clean_fixture(net):
    # o fixture só usa DGBT/DBAR/DGER/DLIN, todas implementadas
    assert net.warnings == []
