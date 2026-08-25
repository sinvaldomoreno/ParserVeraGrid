from pathlib import Path

import pytest

from pwf2raw.pwf_reader import PwfReader
from pwf2raw.raw_writer import write_raw

FIXTURE = Path(__file__).parent / "data" / "mini_4bus.pwf"


def test_write_raw_smoke(tmp_path):
    net = PwfReader(FIXTURE).parse()
    out = tmp_path / "mini.raw"
    write_raw(net, out)
    content = out.read_text(encoding="latin-1")
    assert content.startswith(" 0,")
    assert "0 / END OF BUS DATA" in content
    assert content.strip().endswith("Q")


def test_write_raw_opens_in_veragrid(tmp_path):
    """Validação de ponta a ponta: abre o .raw gerado com o VeraGrid.

    Este teste é pulado automaticamente se o pacote `VeraGridEngine`
    não estiver instalado (é uma dependência pesada, opcional, só para
    validação - não é dependência do pwf2raw em si).
    """
    veragrid = pytest.importorskip("VeraGridEngine.api")

    net = PwfReader(FIXTURE).parse()
    out = tmp_path / "mini.raw"
    write_raw(net, out)

    grid = veragrid.open_file(str(out))
    assert len(grid.buses) == 4
    assert len(grid.lines) == 1
    assert len(grid.transformers2w) == 1
    assert len(grid.loads) == 2
    assert len(grid.generators) == 2

    options = veragrid.PowerFlowOptions(veragrid.SolverType.NR, verbose=0)
    pf = veragrid.PowerFlowDriver(grid=grid, options=options)
    pf.run()
    assert pf.results.converged
