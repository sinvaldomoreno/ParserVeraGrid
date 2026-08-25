from pwf2raw import sections as sec


def test_dbar_columns_against_real_ons_line():
    # Linha real extraida do deck ONS (patamar de carga media), usada
    # aqui apenas como fixture textual para travar a especificacao de
    # colunas - ver docs/FORMAT_NOTES.md.
    line = (
        "   10 L1 VANGRA1UNE001 51001-53.     9.576   0.   0."
        "                     2211000                  1                "
    )
    f = sec.DBAR
    assert sec.integer(line, f["number"]) == 10
    assert sec.text(line, f["state"]) == "L"
    assert sec.integer(line, f["type"]) == 1
    assert sec.text(line, f["voltage_base_group"]) == "V"
    assert sec.text(line, f["name"]) == "ANGRA1UNE001"
    assert sec.number(line, f["voltage"]) == 1.001
    assert sec.number(line, f["angle"]) == -53.0
    assert sec.number(line, f["reactive_generation"]) == 9.576
    assert sec.integer(line, f["area"]) == 221


def test_dlin_columns_against_real_ons_lines():
    # Duas linhas reais do mesmo deck: uma com to_bus/circuito "colados"
    # (sem espaco) e outra com espaco - regressao para o bug de
    # segmentacao to_bus (11-15) vs circuito (16-17).
    l1 = (
        "   38       17954         3.0195         1.                     "
        "200.200.  200.                                 1   1"
    )
    l2 = (
        "   60     43810 2           .806      .9524                     "
        "15721815  1792                                 1   1"
    )
    f = sec.DLIN
    assert sec.integer(l1, f["from_bus"]) == 38
    assert sec.integer(l1, f["to_bus"]) == 179
    assert sec.integer(l1, f["circuit"]) == 54

    assert sec.integer(l2, f["from_bus"]) == 60
    assert sec.integer(l2, f["to_bus"]) == 43810
    assert sec.integer(l2, f["circuit"]) == 2
    assert sec.number(l2, f["reactance"]) == 0.806
    assert sec.number(l2, f["tap"]) == 0.9524


def test_implicit_decimal_voltage():
    f = sec.DBAR["voltage"]

    def dummy(value_text: str) -> str:
        line = [" "] * 28
        line[f.start - 1:f.end] = list(value_text.rjust(f.end - f.start + 1))
        return "".join(line)

    assert sec.number(dummy("1001"), f) == 1.001
    assert sec.number(dummy("0950"), f) == 0.950
    assert sec.number(dummy("-053"), f) == -0.053


def test_dger_columns():
    line = "   10       0.   640.    0.  100.                                     0."
    f = sec.DGER
    assert sec.integer(line, f["number"]) == 10
    assert sec.number(line, f["min_active_generation"]) == 0.0
    assert sec.number(line, f["max_active_generation"]) == 640.0
