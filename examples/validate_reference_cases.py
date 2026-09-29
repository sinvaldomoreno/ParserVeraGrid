"""Valida o parser contra casos de referencia ANAREDE ja resolvidos.

Um deck PWF gravado pelo ANAREDE guarda, nos campos V e A do DBAR, a
solucao de fluxo de potencia daquele caso. Isso permite uma validacao
muito mais forte do que "o arquivo abriu sem erro":

  1. converte o .pwf para .raw com o pwf2raw;
  2. roda um fluxo de potencia proprio (VeraGrid) no .raw gerado;
  3. compara a solucao obtida com a solucao gravada no proprio deck.

Um erro de coluna, de escala (%, pu, Mvar) ou de classificacao
linha/transformador aparece imediatamente como divergencia de tensao.

Os angulos so podem ser comparados a menos de um offset constante,
porque a referencia angular pode ser outra - por isso o script remove a
mediana antes de comparar.

Uso:
    python examples/validate_reference_cases.py <dir_com_pwfs> [n_casos] [x_floor]
"""
from __future__ import annotations

import glob
import sys
import tempfile
from pathlib import Path

import numpy as np

from pwf2raw import PwfReader, write_raw


def validate(pwf_path: str, x_floor: float | None = None) -> dict:
    import VeraGridEngine.api as gce

    name = Path(pwf_path).name
    net = PwfReader(pwf_path).parse()
    if x_floor:
        for e in list(net.branches) + list(net.transformers):
            if abs(e.x) < x_floor:
                e.x = x_floor if e.x >= 0 else -x_floor

    with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as fh:
        raw_path = fh.name
    write_raw(net, raw_path)

    grid = gce.open_file(raw_path)
    opt = gce.PowerFlowOptions(
        gce.SolverType.NR, verbose=0, max_iter=40,
        control_q=False, retry_with_other_methods=True,
    )
    pf = gce.PowerFlowDriver(grid=grid, options=opt)
    pf.run()
    converged = bool(pf.results.converged)
    source = "convergido"

    if not converged:
        # Quando todos os metodos falham, o que o mecanismo de retry
        # devolve nao e utilizavel: o 'error' e um valor-sentinela (ex.:
        # 5027 em varios casos distintos) e a tensao pode nao refletir o
        # caso. A iteracao do Newton-Raphson PURO, ao contrario, reproduz
        # o ANAREDE na grande maioria das barras mesmo sem convergir
        # (2035_7: dV mediano 0,0005 pu). E ela que medimos.
        opt = gce.PowerFlowOptions(
            gce.SolverType.NR, verbose=0, max_iter=150,
            control_q=False, retry_with_other_methods=False,
        )
        pf = gce.PowerFlowDriver(grid=grid, options=opt)
        pf.run()
        source = "NR puro, nao convergido"

    out = {"name": name, "buses": len(net.buses),
           "converged": converged, "source": source,
           "error": float(pf.results.error)}

    # A qualidade e medida SEMPRE, convirja ou nao. O flag de
    # convergencia e um indicador ruim de correcao do modelo aqui:
    # no caso 2035_7 o NR nao converge e mesmo assim reproduz a solucao
    # do ANAREDE com ΔV mediano de 0.0005 pu e 95% das barras dentro de
    # 0.02 pu, enquanto IWAMOTO e FASTDECOUPLED "convergem" (erro 1e-8)
    # para uma solucao espuria com 33 graus de erro de angulo. O
    # residuo e norma infinita: basta um punhado de barras nao
    # assentar para o flag cair, ainda que o resto da rede esteja certo.

    v = pf.results.voltage
    # O writer grava as barras em ordem crescente de numero, e o leitor
    # do VeraGrid preserva essa ordem.
    sol = dict(zip(sorted(net.buses), v))
    dv, da = [], []
    for n, b in net.buses.items():
        vv = sol.get(n)
        if vv is None or not b.in_service or abs(vv) < 1e-6:
            continue
        dv.append(abs(vv) - b.vm)
        d = np.degrees(np.angle(vv)) - b.va
        da.append((d + 180) % 360 - 180)
    dv = np.array(dv)
    da = np.array(da)
    da = (da - np.median(da) + 180) % 360 - 180
    out.update(
        compared=dv.size,
        dv_p50=float(np.percentile(np.abs(dv), 50)),
        dv_p95=float(np.percentile(np.abs(dv), 95)),
        dv_ok=float((np.abs(dv) < 0.02).mean()),
        da_p50=float(np.percentile(np.abs(da), 50)),
    )
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    d = Path(sys.argv[1])
    files = sorted(glob.glob(str(d / "*.PWF"))) + sorted(glob.glob(str(d / "*.pwf")))
    if len(sys.argv) > 2 and sys.argv[2] != "all":
        k = int(sys.argv[2])
        step = max(1, len(files) // k)
        files = files[::step][:k]
    merge_tol = float(sys.argv[3]) if len(sys.argv) > 3 else None

    print(f"{len(files)} caso(s), merge_tol={merge_tol}")
    print(f"{'caso':<40} {'conv':<5} {'ΔV p50':>8} {'ΔV p95':>8} "
          f"{'<0.02pu':>8} {'Δang p50':>9}")
    print("(nos casos 'nao', a qualidade e da iteracao do NR puro)")
    print("-" * 86)
    n_ok = 0
    for f in files:
        r = validate(f, merge_tol)
        n_ok += r["converged"]
        flag = "sim" if r["converged"] else "nao"
        print(f"{r['name'][:40]:<40} {flag:<5} {r['dv_p50']:>8.4f} "
              f"{r['dv_p95']:>8.4f} {100 * r['dv_ok']:>7.1f}% "
              f"{r['da_p50']:>9.2f}")
    print("-" * 86)
    print(f"{n_ok}/{len(files)} convergiram. Lembrete: o flag de convergencia "
          f"mede se TODAS as barras assentaram, nao se o modelo esta certo; "
          f"a concordancia com o ANAREDE e a medida de correcao.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
