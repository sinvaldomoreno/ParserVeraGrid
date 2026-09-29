"""Escritor do formato PSS/E RAW rev 33 a partir do modelo `Network`.

Secoes gravadas: Bus, Load, Fixed Shunt, Generator (incluindo os
geradores acoplados que representam os elos CC), Branch, Transformer
(com controle de tap LTC), Area, Two-terminal DC (opcional, dc_model=
"raw"), VSC DC, Switched Shunt e Owner. Correcao de impedancia, MTDC,
MSL, Zone, intercambio, FACTS e GNE saem vazias, com seus terminadores,
para manter o arquivo valido.

Ver docs/FORMAT_NOTES.md, secao 5, para as armadilhas de campo do RAW.
"""
from __future__ import annotations

from pathlib import Path

from .model import Network


def _q(text: str, width: int) -> str:
    return f"'{text[:width]:<{width}}'"


def write_raw(
    net: Network, path: str | Path, dc_model: str = "dummygen", ltc: bool = True
) -> None:
    """Grava o RAW.

    dc_model controla como os elos CC sao representados:
      "dummygen" (padrao) - cada elo vira dois geradores acoplados: um
          consumindo P no retificador e outro injetando P (menos perdas)
          no inversor, com Q livre. E o modelo usado pelo PWF.jl/
          PowerModels e o que melhor sobrevive a solvers genericos.
      "raw"  - grava a secao two-terminal DC do RAW rev33, mais fiel ao
          formato porem dependente do modelo HVDC do leitor.

    ltc controla se os dados de controle de tap (LTC) do DLIN sao gravados.
    Com False, todo transformador sai com tap fixo. Util com templates do
    DESSEM: o VeraGrid liga o controle de taps por padrao e, num caso que
    nao converge, isso produz erros numericos do LAPACK sem mudar o
    resultado.
    """
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
    dummy_gens: list[tuple[int, float]] = []
    if dc_model == "dummygen":
        for link in net.dc_links:
            if link.rectifier is None or link.inverter is None:
                continue
            if not link.in_service or not link.mw:
                continue
            # perdas na linha CC: I = P/Vcc, perda = I^2 * R
            loss = 0.0
            if link.kv:
                current = link.mw / link.kv
                loss = current * current * link.r_ohm
            dummy_gens.append((link.rectifier.ac_bus, -link.mw))
            dummy_gens.append((link.inverter.ac_bus, link.mw - loss))

    for gen in net.generators:
        status = 1 if gen.in_service else 0
        lines.append(
            f"{gen.bus:>6d},{_q(gen.id, 2)},{gen.pg:>10.3f},{gen.qg:>10.3f},"
            f"{gen.qmax:>10.3f},{gen.qmin:>10.3f},{gen.vs:>8.5f},    0,"
            f"{gen.mbase:>10.3f},0.00000,1.00000,0.00000,0.00000,1.00000,"
            f"{status},{100.0:>7.1f},{gen.pmax:>10.3f},{gen.pmin:>10.3f},"
            "   1,1.0000,   0,1.0000,   0,1.0000,   0,1.0000,0, 1.0000"
        )
    for i, (bus, p) in enumerate(dummy_gens):
        # Gerador "dummy" de elo CC: P especificado, Q livre.
        lines.append(
            f"{bus:>6d},{_q(f'D{i % 90:02d}', 2)},{p:>10.3f},{0.0:>10.3f},"
            f"{9999.0:>10.3f},{-9999.0:>10.3f},{1.0:>8.5f},    0,"
            f"{100.0:>10.3f},0.00000,1.00000,0.00000,0.00000,1.00000,"
            f"1,{100.0:>7.1f},{abs(p) + 1:>10.3f},{-abs(p) - 1:>10.3f},"
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
            # Ordem no RAW rev33: ... GI,BI,GJ,BJ,ST,MET,LEN,O1,F1...
            # ST e o status do ramo e MET o terminal de medicao. Inverter
            # os dois faz TODO ramo desligado do deck entrar em servico.
            f"{status},1,   0.0,   1,1.0000,   0,1.0000,   0,1.0000,   0,1.0000"
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
        # Registro 3: WINDV1 NOMV1 ANG1 RATA RATB RATC COD1 CONT1 RMA1 RMI1
        #             VMA1 VMI1 NTP1 TAB1 CR1 CX1
        if ltc and tr.ltc and tr.controlled_bus:
            # COD1=1: controle de tensao na barra CONT1, tap em [RMI1, RMA1],
            # tensao alvo = tensao especificada da barra controlada no
            # DBAR, com banda de +-0.01 pu.
            vb = net.buses.get(tr.controlled_bus)
            vt = vb.vm if vb is not None else 1.0
            ctrl = (f"1,{tr.controlled_bus:>6d},{tr.tap_max:>8.5f},{tr.tap_min:>8.5f},"
                    f"{vt + 0.01:>8.5f},{vt - 0.01:>8.5f},{tr.n_taps:>3d}")
        else:
            ctrl = "0,     0, 1.50000, 0.51000, 1.50000, 0.51000,159"
        lines.append(
            f"{tr.windv1:.5f},  {tr.angle:.3f},   0.000,"
            f"{tr.rate_a:>7.2f},{tr.rate_b:>7.2f},{tr.rate_c:>7.2f},"
            f"{ctrl}, 0, 0.00000, 0.00000"
        )
        lines.append(f"{tr.windv2:.5f},  0.000")
    lines.append("0 / END OF TRANSFORMER DATA, BEGIN AREA DATA")

    # --- Area data ---
    for a in net.areas:
        lines.append(
            f"{a.number:>6d},{0:>6d},{a.exchange:>10.3f},{10.0:>8.3f},"
            f"{_q(a.name, 12)}"
        )
    lines.append("0 / END OF AREA DATA, BEGIN TWO-TERMINAL DC DATA")

    skipped_dc: list[int] = []

    # --- Two-terminal DC data (3 registros por elo) ---
    # O nome do elo identifica o registro no RAW e precisa ser unico. Os
    # nomes do ANAREDE tem ate 20 caracteres e o RAW so 12, o que fazia
    # "ELOCC-FOZ-IBIUNA-P1..P4" colidirem todos em "ELOCC-FOZ-IB".
    for link in (net.dc_links if dc_model == "raw" else []):
        rect, inv = link.rectifier, link.inverter
        if rect is None or inv is None:
            continue
        # Nota: nem todo elo CC e HVDC de transmissao. Retificadores
        # industriais (ex. os elos "Alumar" das linhas de cubas de
        # aluminio) operam com Ebas na casa de 0.7-0.9 kV e limites de
        # tap propositalmente amplos. Isso e dado legitimo, entao o
        # writer nao rejeita esses elos - apenas sinaliza os que parecem
        # ter ficado sem os registros DCNV/DCCV correspondentes.
        if rect.ebas_kv == 0.0 and inv.ebas_kv == 0.0:
            skipped_dc.append(link.number)
        suffix = str(link.number)
        raw_name = f"{link.name[: 12 - len(suffix) - 1]}_{suffix}"
        mdc = 1 if link.in_service else 0
        setvl = link.mw if link.mw else 1.0
        vschd = link.kv if link.kv else 1.0
        # Registro 0: NAME MDC RDC SETVL VSCHD VCMOD RCOMP DELTI METER
        #             DCVMIN CCCITMX CCCACC  (12 campos)
        lines.append(
            f"{_q(raw_name, 12)},{mdc},{link.r_ohm:>10.5f},{setvl:>10.3f},"
            f"{vschd:>10.3f},{0.0:>8.3f},{0.0:>8.3f},{0.0:>8.3f},"
            f"{_q('I', 1)},{0.0:>8.3f},{20:>4d},{0.0:>8.3f}"
        )
        # Registros 1 e 2 (retificador, inversor): IP NB ANMX ANMN RC XC
        #   EBAS TR TAP TMX TMN STP IC IF IT ID XCAP  (17 campos)
        for c in (rect, inv):
            lines.append(
                f"{c.ac_bus:>6d},{c.bridges:>3d},{c.angle_max:>8.3f},"
                f"{c.angle_min:>8.3f},{0.0:>8.4f},{c.xc_pct:>9.5f},"
                f"{c.ebas_kv:>9.3f},{1.0:>8.5f},{1.0:>8.5f},"
                f"{c.tap_max:>8.5f},{c.tap_min:>8.5f},{0.00625:>9.5f},"
                f"{0:>6d},{0:>6d},{0:>6d},{_q('1', 2)},{0.0:>8.3f}"
            )
    if skipped_dc:
        net.add_warning(
            f"{len(skipped_dc)} elo(s) CC com tensao base de conversor "
            f"zerada, o que sugere que os registros DCNV/DCCV "
            f"correspondentes nao foram encontrados: {skipped_dc[:10]}."
        )
    lines.append("0 / END OF TWO-TERMINAL DC DATA, BEGIN VOLTAGE SOURCE CONVERTER DATA")

    # --- VSC DC line data (3 registros por elo) ---
    # Um conversor controla a tensao CC (TYPE 1) e o outro a potencia
    # (TYPE 2); o RAW exige exatamente um de cada por elo.
    for v in net.vsc_links:
        mdc = 1 if v.in_service else 0
        smax = v.mva_base if v.mva_base else abs(v.mw)
        qlim = 0.5 * smax if smax else 9999.0
        lines.append(f"{_q(v.name[:12], 12)},{mdc},{v.r_ohm:>10.5f}")
        # conversor 1 (retificador): controle de potencia, entrando no elo
        lines.append(
            f"{v.rectifier_bus:>6d},2,1,{v.mw:>11.3f},{1.0:>9.5f},"
            f"{0.0:>8.3f},{0.0:>8.3f},{0:>4d},{smax:>10.3f},{0.0:>10.3f},"
            f"{1.0:>7.4f},{qlim:>10.3f},{-qlim:>10.3f},{0:>6d},{100.0:>7.1f}"
        )
        # conversor 2 (inversor): controle de tensao CC
        lines.append(
            f"{v.inverter_bus:>6d},1,1,{v.vcc_kv:>11.3f},{1.0:>9.5f},"
            f"{0.0:>8.3f},{0.0:>8.3f},{0:>4d},{smax:>10.3f},{0.0:>10.3f},"
            f"{1.0:>7.4f},{qlim:>10.3f},{-qlim:>10.3f},{0:>6d},{100.0:>7.1f}"
        )
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
    for sh in net.switched_shunts:
        status = 1 if sh.in_service else 0
        blocks = ""
        for n_steps, step_mvar in sh.blocks[:8]:
            blocks += f",{int(n_steps):>4d},{step_mvar:>10.3f}"
        lines.append(
            f"{sh.bus:>6d},{sh.modsw},{0},{1.0:>7.4f},{sh.v_max:>8.5f},"
            f"{sh.v_min:>8.5f},{sh.controlled_bus:>6d},{100.0:>7.1f},"
            f"{_q('', 12)},{sh.binit:>10.3f}{blocks}"
        )
    lines.append("0 /END OF SWITCHED SHUNT DATA, BEGIN GNE DEVICE DATA")
    lines.append("0 /END OF GNE DEVICE DATA")
    lines.append("Q")

    path.write_text("\n".join(lines) + "\n", encoding="latin-1")
