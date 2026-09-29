"""Roda a validacao em blocos, salvando o progresso em disco.

Permite retomar de onde parou se o processo for interrompido, o que
importa quando o corpus tem ~100 casos grandes.

Uso: python examples/run_validation.py <dir> <resultados.jsonl> [n_por_bloco]
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

from validate_reference_cases import validate


def main() -> int:
    d, out = Path(sys.argv[1]), Path(sys.argv[2])
    chunk = int(sys.argv[3]) if len(sys.argv) > 3 else 6

    files = sorted(glob.glob(str(d / "*.PWF"))) + sorted(glob.glob(str(d / "*.pwf")))
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["name"])

    todo = [f for f in files if Path(f).name not in done]
    print(f"total={len(files)} feitos={len(done)} restantes={len(todo)}")

    for f in todo[:chunk]:
        try:
            r = validate(f)
        except Exception as e:  # nao deixar um caso ruim parar o lote
            r = {"name": Path(f).name, "converged": False, "error": -1.0,
                 "exception": repr(e)[:200]}
        with out.open("a") as fh:
            fh.write(json.dumps(r) + "\n")
        flag = "sim" if r.get("converged") else "NAO"
        print(f"  {r['name'][:44]:<44} {flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
