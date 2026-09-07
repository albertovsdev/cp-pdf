"""Objetivo 3 (fase 8d): lo que la hoja `Polizas` puede y no puede afirmar.

Antes de partir la columna en declarado y leido hay que saber sobre que
casos se decide: cuantas polizas no cerraron dentro de lo leido (que es lo
que `completa` significa HOY), cuantas no declaran totales, y cuantas
difieren entre lo declarado y la suma de sus movimientos.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from conftest import REAL_PDFS  # noqa: E402

from contapdf.pipeline import procesar_polizas  # noqa: E402

_CERO = Decimal(0)

for nombre in (sys.argv[1:] or ["poliza", "diario-general"]):
    resultado = procesar_polizas(REAL_PDFS[nombre])
    libro = resultado.libro
    leido: dict[str, list[Decimal]] = {}
    for m in libro.movimientos:
        par = leido.setdefault(m.poliza_id, [_CERO, _CERO])
        par[0] += m.debe
        par[1] += m.haber

    incompletas = sin_totales = difieren = sin_movimientos = 0
    for p in libro.polizas:
        if not p.completa:
            incompletas += 1
        if p.total_debe is None or p.total_haber is None:
            sin_totales += 1
            continue
        debe, haber = leido.get(p.poliza_id, [_CERO, _CERO])
        if p.poliza_id not in leido:
            sin_movimientos += 1
        if p.total_debe != debe or p.total_haber != haber:
            difieren += 1

    regla = next(r for r in resultado.cobertura.reglas
                 if r.regla == "partida_doble")
    fallan = {d.fila for d in regla.discrepancias}
    difieren_ids = {
        p.poliza_id for p in libro.polizas
        if p.total_debe is not None and p.total_haber is not None
        and (p.total_debe, p.total_haber) != tuple(
            leido.get(p.poliza_id, [_CERO, _CERO]))
    }

    print(f"=== {nombre} ===")
    print(f"  polizas                             {len(libro.polizas)}")
    print(f"  movimientos                         {len(libro.movimientos)}")
    print(f"  con completa=False (bloque cortado) {incompletas}")
    print(f"  sin totales declarados (None)       {sin_totales}")
    print(f"  sin ningun movimiento leido         {sin_movimientos}")
    print(f"  declarado != leido                  {difieren}")
    print(f"  partida_doble: {regla.evaluados} de {regla.aplicables} evaluados,"
          f" {len(regla.discrepancias)} con diferencia")
    print(f"  las que difieren y las que fallan la regla son las mismas: "
          f"{'SI' if difieren_ids == fallan else 'NO'}"
          f" ({len(difieren_ids & fallan)} en comun)")
    print()
