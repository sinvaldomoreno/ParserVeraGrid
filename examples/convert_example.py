"""Exemplo de uso programático do pwf2raw (sem passar pela CLI)."""
from pathlib import Path

from pwf2raw import PwfReader, write_raw

HERE = Path(__file__).parent
INPUT = HERE.parent / "tests" / "data" / "mini_4bus.pwf"
OUTPUT = HERE / "mini_4bus.raw"


def main() -> None:
    net = PwfReader(INPUT).parse()
    print(f"Lido de {INPUT.name}: {net.summary()}")

    for w in net.warnings:
        print("aviso:", w)

    write_raw(net, OUTPUT)
    print(f"Gravado em {OUTPUT}")

    # A partir daqui, o arquivo pode ser aberto diretamente no VeraGrid:
    #
    #   import VeraGridEngine.api as gce
    #   grid = gce.open_file(str(OUTPUT))


if __name__ == "__main__":
    main()
