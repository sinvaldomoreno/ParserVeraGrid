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
    Area,
    Branch,
    Bus,
    DcConverter,
    DcLink,
    FixedShunt,
    Generator,
    Load,
    Network,
    SwitchedShunt,
    Transformer2W,
    VscLink,
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


def _split_sections(
    lines: list[str],
) -> tuple[dict[str, list[str]], dict[str, str], set[str]]:
    """Agrupa as linhas de dados de cada seção reconhecida.

    Ignora a(s) linha(s) de comentário (iniciadas por '(') logo após o
    cabeçalho, e para de coletar ao encontrar o terminador '99999' ou o
    início de outra seção reconhecida.
    """
    blocks: dict[str, list[str]] = {}
    headers: dict[str, str] = {}
    seen_codes: set[str] = set()
    current = None
    for line in lines:
        code4 = line[:4]
        is_code = (
            len(code4) == 4
            and code4.isalpha()
            and code4.isupper()
            and (len(line) == 4 or line[4:5] in (" ", ""))
        )
        if is_code and code4[0] == "D":
            seen_codes.add(code4)
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
            # A PRIMEIRA linha de comentario de cada secao e o cabecalho
            # que delimita os campos; dele derivamos o layout de colunas
            # (ver sections.layout_from_header).
            headers.setdefault(current, line)
            continue
        if stripped == "":
            continue
        blocks[current].append(line)
    return blocks, headers, seen_codes


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
    def __init__(self, path: str | Path, dc_status: str = "file"):
        """
        dc_status controla o estado dos elos CC no modelo resultante:
          "file" (padrao) - respeita o campo Estado do registro DELO
          "on"            - forca todos os elos energizados
          "off"           - forca todos os elos bloqueados
        """
        if dc_status not in ("file", "on", "off"):
            raise ValueError(
                f"dc_status invalido: {dc_status!r} (use 'file', 'on' ou 'off')"
            )
        self.path = Path(path)
        self.dc_status = dc_status
        self._headers: dict[str, str] = {}

    def parse(self) -> Network:
        lines = list(_iter_lines(self.path))
        blocks, headers, seen_codes = _split_sections(lines)
        self._headers = headers
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
        self._parse_dcsc(blocks.get("DCSC", []), net)
        self._parse_dshl(blocks.get("DSHL", []), net)
        self._parse_dbsh(blocks.get("DBSH", []), net)
        self._parse_dcer(blocks.get("DCER", []), net)
        self._parse_dare(blocks.get("DARE", []), net)
        self._parse_dc_network(blocks, net)
        self._parse_dvsc(blocks.get("DVSC", []), net)

        # LTC: barra controlada inexistente (ex.: codigo 999) cai para a
        # barra "para" do proprio transformador.
        for t in net.transformers:
            if t.ltc and t.controlled_bus not in net.buses:
                t.controlled_bus = t.to_bus

        # Elementos ligados a barras desligadas ficam fora de servico.
        for coll in (net.loads, net.fixed_shunts, net.generators,
                     net.switched_shunts):
            for el in coll:
                b = net.buses.get(el.bus)
                if b is not None and not b.in_service:
                    el.in_service = False
        for e in list(net.branches) + list(net.transformers):
            bf, bt = net.buses.get(e.from_bus), net.buses.get(e.to_bus)
            if (bf is not None and not bf.in_service) or (
                bt is not None and not bt.in_service
            ):
                e.in_service = False

        known = (
            sec.SECTIONS_IMPLEMENTED
            | set(sec.SECTIONS_KNOWN_NOT_IMPLEMENTED)
            | {"TITU", "FAGR", "FBAN"}
        )
        for code in sorted(seen_codes - known):
            net.add_warning(
                f"Secao {code} encontrada no arquivo mas desconhecida por "
                f"este parser; seus dados foram ignorados."
            )

        for code in sec.SECTIONS_KNOWN_NOT_IMPLEMENTED:
            if code in blocks and blocks[code]:
                net.add_warning(
                    f"Seção {code} presente no arquivo ({len(blocks[code])} "
                    f"registro(s)) mas ainda não é interpretada por este "
                    f"parser: {sec.SECTIONS_KNOWN_NOT_IMPLEMENTED[code]}."
                )

        return net


    @staticmethod
    def _ltc_fields(line: str, f: dict) -> dict:
        """Dados de controle de tap (LTC) de um registro DLIN.

        Um transformador e LTC quando traz faixa de tap valida
        (Tmn < Tmx). No deck DESSEM de set/2026 sao 2.311 de 7.414
        transformadores. A barra controlada (Bc) e validada depois, em
        parse(), contra as barras existentes.
        """
        tmn = sec.number(line, f["tap_minimum"])
        tmx = sec.number(line, f["tap_maximum"])
        if not (tmn and tmx and tmx > tmn):
            return {}
        return {
            "ltc": True,
            "tap_min": tmn,
            "tap_max": tmx,
            "controlled_bus": sec.integer(line, f["controlled_bus"], default=0) or 0,
            "n_taps": max(sec.integer(line, f["number_of_taps"], default=33) or 33, 2),
        }

    @staticmethod
    def _check_alignment(
        section: str, lines: list[str], fields: dict, net: Network
    ) -> None:
        """Avisa se os registros nao baterem com o layout de colunas.

        Um campo contendo apenas '-' ou '.' e prova de que um numero do
        arquivo ficou partido na fronteira entre dois campos. Sem esse
        aviso o parser produziria numeros errados em silencio.
        """
        hits: dict[str, int] = {}
        flist = list(fields.values())
        for line in lines:
            for name in sec.alignment_symptoms(line, flist):
                hits[name] = hits.get(name, 0) + 1
        if hits:
            worst = sorted(hits.items(), key=lambda kv: -kv[1])[:3]
            detail = ", ".join(f"{n} ({c}x)" for n, c in worst)
            net.add_warning(
                f"Secao {section}: {sum(hits.values())} campo(s) contem "
                f"apenas sinal ou ponto decimal, indicando que o layout de "
                f"colunas nao bate com os registros deste arquivo (campos "
                f"mais afetados: {detail}). Os valores podem estar errados."
            )

    # -- DCSC (compensador serie controlavel) ------------------------
    def _parse_dcsc(self, lines: list[str], net: Network) -> None:
        f = sec.layout_from_header("DCSC", self._headers.get("DCSC", ""), sec.DCSC)
        for line in lines:
            fb = sec.integer(line, f["from_bus"])
            tb = sec.integer(line, f["to_bus"])
            if fb is None or tb is None:
                continue
            x_pct = sec.number(line, f["initial_reactance"])
            if x_pct is None:
                x_pct = sec.number(line, f["min_reactance"], default=0.0) or 0.0
            x = x_pct / 100.0
            # Um TCSC totalmente compensado pode chegar a x=0, o que
            # deixa a matriz de admitancia singular. Um piso minimo
            # mantem o ramo numericamente tratavel.
            if abs(x) < 1e-5:
                x = 1e-5 if x >= 0 else -1e-5
            ckt = sec.integer(line, f["circuit"], default=1) or 1
            rate = sec.number(line, f["normal_capacity"], default=0.0) or 0.0
            net.branches.append(
                Branch(
                    from_bus=fb, to_bus=tb, ckt=str(ckt),
                    r=0.0, x=x, b=0.0,
                    rate_a=rate, rate_b=rate, rate_c=rate,
                    in_service=sec.text(line, f["state"]).upper() != "D",
                )
            )

    # -- DSHL (shunts de linha) --------------------------------------
    def _parse_dshl(self, lines: list[str], net: Network) -> None:
        """Cada extremidade vira um shunt fixo na sua barra terminal.

        O RAW rev 33 nao modela shunt de linha; anexar cada metade a
        barra correspondente e a conversao usual e preserva o balanco
        de reativo, que e o que importa para o fluxo de potencia.
        """
        f = sec.layout_from_header("DSHL", self._headers.get("DSHL", ""), sec.DSHL)
        self._check_alignment("DSHL", lines, f, net)
        for line in lines:
            fb = sec.integer(line, f["from_bus"])
            tb = sec.integer(line, f["to_bus"])
            if fb is None or tb is None:
                continue
            sh_from = sec.number(line, f["shunt_from"])
            sh_to = sec.number(line, f["shunt_to"])
            if sh_from and sec.text(line, f["state_from"]).upper() != "D":
                net.fixed_shunts.append(
                    FixedShunt(bus=fb, id="L", g=0.0, b=sh_from)
                )
            if sh_to and sec.text(line, f["state_to"]).upper() != "D":
                net.fixed_shunts.append(
                    FixedShunt(bus=tb, id="L", g=0.0, b=sh_to)
                )

    # -- DBSH (bancos chaveaveis) ------------------------------------
    def _parse_dbsh(self, lines: list[str], net: Network) -> None:
        """DBSH tem estrutura em dois niveis.

        Uma linha de cabecalho descreve o banco; depois de uma linha de
        comentario "(G  O E ..." vem uma ou mais linhas de grupo, e o
        bloco termina em FBAN. Como `_split_sections` ja removeu as
        linhas de comentario, distinguimos cabecalho de grupo pela
        largura do campo de barra: o cabecalho traz o numero da barra
        nas colunas 1-5, o grupo traz o numero do grupo em 1-2.
        """
        fh, fg = sec.DBSH, sec.DBSH_GROUP
        current: SwitchedShunt | None = None
        for line in lines:
            if line.strip().upper() == "FBAN":
                current = None
                continue
            bus = sec.integer(line, fh["from_bus"])
            # Linha de grupo: o campo de barra (1-5) do cabecalho tem 5
            # colunas; num grupo as colunas 3-5 estao em branco.
            is_group = current is not None and sec.raw(line, 3, 5).strip() == ""
            if is_group:
                units = sec.integer(line, fg["units_operating"], default=None)
                if units is None:
                    units = sec.integer(line, fg["units"], default=0) or 0
                per_unit = sec.number(line, fg["shunt_per_unit"], default=0.0) or 0.0
                if units and per_unit:
                    current.blocks.append((units, per_unit))
                continue
            if bus is None:
                continue
            binit = sec.number(line, fh["q_initial"], default=0.0) or 0.0
            mode_txt = sec.text(line, fh["mode"]).upper()
            current = SwitchedShunt(
                bus=bus,
                binit=binit,
                v_min=sec.number(line, fh["v_min"], default=0.9) or 0.9,
                v_max=sec.number(line, fh["v_max"], default=1.1) or 1.1,
                controlled_bus=sec.integer(line, fh["controlled_bus"], default=0) or 0,
                modsw={"C": 2, "D": 1, "F": 0}.get(mode_txt, 1),
                in_service=sec.text(line, fh["state"]).upper() != "D",
            )
            net.switched_shunts.append(current)

    # -- DCER (compensador estatico) ---------------------------------
    def _parse_dcer(self, lines: list[str], net: Network) -> None:
        f = sec.layout_from_header("DCER", self._headers.get("DCER", ""), sec.DCER)
        for line in lines:
            bus = sec.integer(line, f["bus"])
            if bus is None:
                continue
            qg = sec.number(line, f["reactive_generation"], default=0.0) or 0.0
            qn = sec.number(line, f["min_reactive"], default=0.0) or 0.0
            qx = sec.number(line, f["max_reactive"], default=0.0) or 0.0
            blocks = []
            if qx > 0:
                blocks.append((1, qx))
            if qn < 0:
                blocks.append((1, qn))
            net.switched_shunts.append(
                SwitchedShunt(
                    bus=bus,
                    binit=qg,
                    controlled_bus=sec.integer(line, f["controlled_bus"], default=0) or 0,
                    modsw=2,  # SVC e continuo
                    blocks=blocks,
                    in_service=sec.text(line, f["state"]).upper() != "D",
                )
            )

    # -- DARE (areas) ------------------------------------------------
    def _parse_dare(self, lines: list[str], net: Network) -> None:
        f = sec.DARE
        for line in lines:
            num = sec.integer(line, f["number"])
            if num is None:
                continue
            net.areas.append(
                Area(
                    number=num,
                    name=sec.text(line, f["name"])[:12],
                    exchange=sec.number(line, f["exchange"], default=0.0) or 0.0,
                )
            )

    # -- DVSC (elos HVDC VSC) ----------------------------------------
    def _parse_dvsc(self, lines: list[str], net: Network) -> None:
        f = sec.layout_from_header("DVSC", self._headers.get("DVSC", ""), sec.DVSC)
        for line in lines:
            num = sec.integer(line, f["number"])
            rb = sec.integer(line, f["rectifier_bus"])
            ib = sec.integer(line, f["inverter_bus"])
            if num is None or rb is None or ib is None:
                continue
            state = sec.text(line, f["state"]).upper()
            if self.dc_status == "on":
                in_service = True
            elif self.dc_status == "off":
                in_service = False
            else:
                in_service = state != "D"
            net.vsc_links.append(
                VscLink(
                    number=num,
                    name=sec.text(line, f["name"])[:20],
                    rectifier_bus=rb,
                    inverter_bus=ib,
                    mw=sec.number(line, f["power"], default=0.0) or 0.0,
                    mva_base=sec.number(line, f["power_base"], default=0.0) or 0.0,
                    vcc_kv=sec.number(line, f["vcc"], default=0.0) or 0.0,
                    vcc_base_kv=sec.number(line, f["vcc_base"], default=0.0) or 0.0,
                    r_ohm=sec.number(line, f["r_line"], default=0.0) or 0.0,
                    in_service=in_service,
                )
            )

    # -- Rede CC classica (DELO + DCBA + DCLI + DCNV + DCCV) ---------
    def _parse_dc_network(self, blocks: dict[str, list[str]], net: Network) -> None:
        """Monta os elos CC juntando as cinco secoes.

        DELO da o elo; DCBA as barras CC (e a qual elo pertencem); DCLI
        a resistencia da linha CC; DCNV os conversores (barra CA, barra
        CC, tipo R/I); DCCV o controle de cada conversor. A juncao e
        feita pelo numero do elo, via barra CC do conversor.
        """
        fb, fl, fn, fc, fe = sec.DCBA, sec.DCLI, sec.DCNV, sec.DCCV, sec.DELO

        # barra CC -> numero do elo
        dcbus_link: dict[int, int] = {}
        for line in blocks.get("DCBA", []):
            n = sec.integer(line, fb["number"])
            lk = sec.integer(line, fb["link"])
            if n is not None and lk is not None:
                dcbus_link[n] = lk

        # resistencia total da linha CC por elo
        dc_line_r: dict[int, float] = {}
        for line in blocks.get("DCLI", []):
            a = sec.integer(line, fl["from_bus"])
            r = sec.number(line, fl["resistance"], default=0.0) or 0.0
            lk = dcbus_link.get(a)
            if lk is not None:
                dc_line_r[lk] = dc_line_r.get(lk, 0.0) + r

        # controle por numero de conversor
        ctrl: dict[int, dict] = {}
        for line in blocks.get("DCCV", []):
            n = sec.integer(line, fc["number"])
            if n is None:
                continue
            ctrl[n] = {
                "control_type": sec.text(line, fc["control_type"]).upper(),
                "setpoint": sec.number(line, fc["setpoint"], default=0.0) or 0.0,
                "angle_setpoint": sec.number(line, fc["angle_setpoint"], default=0.0) or 0.0,
                "angle_min": sec.number(line, fc["angle_min"], default=5.0) or 5.0,
                "angle_max": sec.number(line, fc["angle_max"], default=90.0) or 90.0,
                "tap_min": sec.number(line, fc["tap_min"], default=0.9) or 0.9,
                "tap_max": sec.number(line, fc["tap_max"], default=1.1) or 1.1,
            }

        # conversores agrupados por elo
        conv: dict[int, list[DcConverter]] = {}
        for line in blocks.get("DCNV", []):
            n = sec.integer(line, fn["number"])
            ac = sec.integer(line, fn["ac_bus"])
            dc = sec.integer(line, fn["dc_bus"])
            if n is None or ac is None or dc is None:
                continue
            lk = dcbus_link.get(dc)
            if lk is None:
                continue
            c = ctrl.get(n, {})
            conv.setdefault(lk, []).append(
                DcConverter(
                    ac_bus=ac,
                    dc_bus=dc,
                    neutral_bus=sec.integer(line, fn["neutral_bus"], default=0) or 0,
                    kind=(sec.text(line, fn["type"]).upper() or "R"),
                    bridges=sec.integer(line, fn["bridges"], default=1) or 1,
                    xc_pct=sec.number(line, fn["xc_pct"], default=0.0) or 0.0,
                    ebas_kv=sec.number(line, fn["ebas_kv"], default=0.0) or 0.0,
                    control_type=c.get("control_type", ""),
                    setpoint=c.get("setpoint", 0.0),
                    angle_setpoint=c.get("angle_setpoint", 0.0),
                    angle_min=c.get("angle_min", 5.0),
                    angle_max=c.get("angle_max", 90.0),
                    tap_min=c.get("tap_min", 0.9),
                    tap_max=c.get("tap_max", 1.1),
                )
            )

        for line in blocks.get("DELO", []):
            num = sec.integer(line, fe["number"])
            if num is None:
                continue
            cs = conv.get(num, [])
            rect = next((c for c in cs if c.kind == "R"), None)
            inv = next((c for c in cs if c.kind == "I"), None)
            # Potencia de operacao do elo: vem do controle do retificador
            # (DCCV), nao do DELO. So ha suporte para controle de potencia.
            setpoint_mw = 0.0
            if rect is not None:
                setpoint_mw = abs(rect.setpoint)
                if rect.control_type and rect.control_type != "P":
                    net.add_warning(
                        f"Elo CC {num}: tipo de controle do retificador e "
                        f"{rect.control_type!r}; apenas controle de potencia "
                        f"('P') e suportado, o elo ficara com 0 MW."
                    )
                    setpoint_mw = 0.0
            state = sec.text(line, fe["state"]).upper()
            if self.dc_status == "on":
                in_service = True
            elif self.dc_status == "off":
                in_service = False
            else:
                in_service = state != "D"
            if rect is None or inv is None:
                net.add_warning(
                    f"Elo CC {num}: {len(cs)} conversor(es) encontrado(s), mas "
                    f"nao foi possivel identificar o par retificador/inversor; "
                    f"o elo nao sera gravado no RAW."
                )
            net.dc_links.append(
                DcLink(
                    number=num,
                    name=sec.text(line, fe["name"])[:20],
                    kv=sec.number(line, fe["voltage"], default=0.0) or 0.0,
                    mw=setpoint_mw,
                    r_ohm=dc_line_r.get(num, 0.0),
                    in_service=in_service,
                    rectifier=rect,
                    inverter=inv,
                )
            )

        if net.dc_links and self.dc_status == "file":
            off = [lk for lk in net.dc_links if not lk.in_service]
            if len(off) == len(net.dc_links):
                net.add_warning(
                    f"Todos os {len(off)} elos CC estao marcados como "
                    f"desligados (Estado do DELO = 'D'). Eles foram gravados "
                    f"no RAW porem bloqueados (MDC=0), o que deixa ilhados os "
                    f"subsistemas conectados apenas via CC. Use --dc-status on "
                    f"para energiza-los."
                )

    # -- DBAR ------------------------------------------------------
    def _parse_dbar(
        self, lines: list[str], group_kv: dict[str, float], net: Network
    ) -> None:
        f = sec.layout_from_header("DBAR", self._headers.get("DBAR", ""), sec.DBAR)
        self._check_alignment("DBAR", lines, f, net)
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

            # Carga, geracao e shunt de uma barra desligada tambem estao
            # fora de servico. Sem propagar isso, o RAW recebe injecoes
            # "fantasma" em barras desenergizadas (no deck EPE 2035 isso
            # eram ~8 GW de geracao inexistente, o suficiente para
            # inviabilizar o fluxo de potencia).
            alive = bus.in_service

            pl = sec.number(line, f["active_load"])
            ql = sec.number(line, f["reactive_load"])
            if pl or ql:
                net.loads.append(
                    Load(bus=number, id="1", p=pl or 0.0, q=ql or 0.0,
                         in_service=alive)
                )

            bc = sec.number(line, f["capacitor_reactor"])
            if bc:
                net.fixed_shunts.append(
                    FixedShunt(bus=number, id="1", g=0.0, b=bc,
                               in_service=alive)
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
                        in_service=alive,
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
        f = sec.layout_from_header("DLIN", self._headers.get("DLIN", ""), sec.DLIN)
        self._check_alignment("DLIN", lines, f, net)
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
                        **self._ltc_fields(line, f),
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
