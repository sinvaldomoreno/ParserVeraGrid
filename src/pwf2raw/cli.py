from __future__ import annotations

import argparse
import sys

from .pwf_reader import PwfReader
from .raw_writer import write_raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pwf2raw",
        description=(
            "Converte um arquivo ANAREDE (.pwf) para PSS/E RAW (rev 33), "
            "formato que pode ser aberto diretamente no VeraGrid/GridCal."
        ),
    )
    parser.add_argument("input", help="Caminho do arquivo .pwf de entrada")
    parser.add_argument("output", help="Caminho do arquivo .raw de saída")
    parser.add_argument(
        "--dc-status", choices=["file", "on", "off"], default="file",
        help=("Estado dos elos CC: 'file' respeita o campo Estado do DELO "
              "(padrao), 'on' forca energizados, 'off' forca bloqueados"),
    )
    parser.add_argument(
        "--dessem-deck", metavar="DIR", default=None,
        help=("Diretorio de um deck DESSEM do ONS. O .pwf e so a rede; o "
              "despacho fica nos relatorios pdo_*.dat. Com esta opcao o "
              "despacho termico e renovavel e injetado por numero de barra"),
    )
    parser.add_argument(
        "--dessem-period", default="auto", metavar="N|auto",
        help=("Periodo do DESSEM (1-48) cujo despacho sera aplicado. 'auto' "
              "(padrao) escolhe o periodo cuja geracao total mais se "
              "aproxima da carga do .pwf mais ~3%% de perdas"),
    )
    parser.add_argument(
        "--curtail", action="store_true",
        help=("Com --dessem-deck: corta a geracao renovavel excedente para "
              "fechar o balanco com a carga + ~3%% de perdas. O resultado "
              "inicial do DESSEM nao contem o curtailment do tempo real"),
    )
    parser.add_argument(
        "--merge-z", type=float, default=None, metavar="TOL",
        help=("Funde os nos ligados por ramos de impedancia abaixo de TOL pu "
              "num no equivalente (tratamento de zero-impedance branch). "
              "Preserva a fisica; muda a numeracao interna de barras"),
    )
    parser.add_argument(
        "--x-floor", type=float, default=None, metavar="X",
        help=("Impoe um piso de reatancia (pu) nos ramos de impedancia "
              "desprezivel. ATENCAO: isso modifica a rede em relacao ao "
              "deck original; use apenas se precisar forcar convergencia"),
    )
    parser.add_argument(
        "--no-ltc", action="store_true",
        help="Grava todos os transformadores com tap fixo (sem controle LTC)",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Roda o diagnostico estrutural do caso apos a leitura",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Mostra avisos detalhados"
    )
    args = parser.parse_args(argv)

    reader = PwfReader(args.input, dc_status=args.dc_status)
    net = reader.parse()

    print(f"Lido: {net.summary()}")
    if net.warnings:
        print(f"{len(net.warnings)} aviso(s):")
        for w in net.warnings if args.verbose else net.warnings[:10]:
            print(f"  - {w}")
        if not args.verbose and len(net.warnings) > 10:
            print(f"  ... (+{len(net.warnings) - 10}, use -v para ver todos)")

    if args.dessem_deck:
        from .dessem import apply_dispatch, best_period
        period = args.dessem_period
        if period == "auto":
            load = sum(l.p for l in net.loads if l.in_service)
            period, bal = best_period(args.dessem_deck, load)
            print(f"Periodo DESSEM escolhido: {period} "
                  f"(saldo geracao-carga {bal:+.1%})")
        print(apply_dispatch(net, args.dessem_deck, period=period,
                             pwf_path=args.input,
                             curtail=args.curtail).describe())

    if args.merge_z:
        from .zbranch import floor_residual_impedance, merge_zero_impedance
        rep = merge_zero_impedance(net, args.merge_z)
        print(rep.describe())
        # Transformadores ideais com tap != 1 e ramos de reatancia
        # negativa nao podem ser fundidos (a relacao de tensao entre os
        # dois nos e real). Para esses, poucos, impomos reatancia
        # minima e listamos o que mudou.
        changed = floor_residual_impedance(net, args.merge_z, args.merge_z)
        if changed:
            print(
                f"Piso de reatancia {args.merge_z:g} pu aplicado a "
                f"{len(changed)} elemento(s) que nao podiam ser fundidos:"
            )
            for c in changed[:10]:
                print(f"  - {c}")
            if len(changed) > 10:
                print(f"  ... (+{len(changed) - 10})")

    if args.x_floor:
        n = 0
        for e in list(net.branches) + list(net.transformers):
            if abs(e.x) < args.x_floor:
                e.x = args.x_floor if e.x >= 0 else -args.x_floor
                n += 1
        print(
            f"AVISO: piso de reatancia {args.x_floor:g} pu aplicado a {n} "
            f"ramo(s). A rede gravada difere do deck original."
        )

    if args.check:
        from .diagnostics import diagnose
        print()
        print(diagnose(net).format())
        print()

    write_raw(net, args.output, ltc=not args.no_ltc)
    print(f"Gravado: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
