"""Fase 8d, objetivo 1: que reglas cuadran habiendo evaluado cero casos.

Recorre los 27 fixtures reales, corre el pipeline del tipo que le
corresponde a cada uno y lista TODA regla con `evaluados == 0`, con su
estado. Las que salen en CUADRA son la combinacion prohibida.

No es un test: necesita los PDFs reales de fixtures/real/, que estan en
.gitignore. Sin ellos se salta el documento y lo dice.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from conftest import REAL_PDFS  # noqa: E402

from contapdf.pipeline import (  # noqa: E402
    procesar_auxiliar,
    procesar_balanza,
    procesar_estado_cuenta,
    procesar_mayor,
    procesar_polizas,
)

_POR_TIPO = (
    ("balanza", procesar_balanza),
    ("auxiliar", procesar_auxiliar),
    ("mayor", procesar_mayor),
    ("edocta", procesar_estado_cuenta),
)


def _procesar_de(nombre: str):
    for prefijo, procesar in _POR_TIPO:
        if nombre.startswith(prefijo):
            return procesar
    return procesar_polizas


def main() -> int:
    ceros: list[tuple[str, str, str, int | None, str]] = []
    saltados: list[tuple[str, str]] = []
    for nombre in sorted(REAL_PDFS):
        pdf = REAL_PDFS[nombre]
        if not pdf.exists():
            saltados.append((nombre, "el PDF no esta en fixtures/real/"))
            continue
        try:
            cobertura = _procesar_de(nombre)(pdf).cobertura
        except Exception as exc:  # noqa: BLE001 -- se reporta, no se traga
            saltados.append((nombre, f"{type(exc).__name__}: {exc}"))
            continue
        print(f"{nombre:24} {cobertura.resumen()}", flush=True)
        for regla in cobertura.reglas:
            if regla.evaluados == 0:
                ceros.append((nombre, regla.regla, regla.estado,
                              regla.aplicables, regla.motivo))

    print("\n" + "=" * 78)
    print("REGLAS CON evaluados == 0")
    print("=" * 78)
    print(f"{'documento':24} {'regla':20} {'estado':15} {'aplic':>6}  motivo")
    for nombre, regla, estado, aplicables, motivo in ceros:
        marca = "  <-- PROHIBIDA" if estado == "cuadra" else ""
        print(f"{nombre:24} {regla:20} {estado:15} "
              f"{aplicables if aplicables is not None else '-':>6}  "
              f"{motivo[:60]}{marca}")
    prohibidas = [c for c in ceros if c[2] == "cuadra"]
    print(f"\ncon evaluados == 0: {len(ceros)}; de esas en CUADRA: "
          f"{len(prohibidas)}")
    docs = sorted({c[0] for c in prohibidas})
    print(f"documentos afectados: {len(docs)} -> {', '.join(docs) or 'ninguno'}")
    if saltados:
        print("\n--- no medidos ---")
        for nombre, motivo in saltados:
            print(f"  {nombre:24} {motivo}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        traceback.print_exc()
        raise SystemExit(1) from None
