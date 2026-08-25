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
        "-v", "--verbose", action="store_true", help="Mostra avisos detalhados"
    )
    args = parser.parse_args(argv)

    reader = PwfReader(args.input)
    net = reader.parse()

    print(f"Lido: {net.summary()}")
    if net.warnings:
        print(f"{len(net.warnings)} aviso(s):")
        for w in net.warnings if args.verbose else net.warnings[:10]:
            print(f"  - {w}")
        if not args.verbose and len(net.warnings) > 10:
            print(f"  ... (+{len(net.warnings) - 10}, use -v para ver todos)")

    write_raw(net, args.output)
    print(f"Gravado: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
