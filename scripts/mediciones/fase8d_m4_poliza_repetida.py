"""M4 (fase 8d): por que `P00476` sale dos veces en el detalle de Validacion.

Dos comprobantes distintos de la misma poliza fallando por separado es
legitimo; el mismo caso contado dos veces no lo es. El bloque de detalle
del Excel lista `cobertura.discrepancias`, o sea las de TODAS las reglas
juntas, asi que hay que mirar de que regla viene cada aparicion.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from conftest import REAL_PDFS  # noqa: E402

from contapdf.pipeline import procesar_polizas  # noqa: E402

nombre = sys.argv[1] if len(sys.argv) > 1 else "poliza"
objetivo = sys.argv[2] if len(sys.argv) > 2 else "P00476"
resultado = procesar_polizas(REAL_PDFS[nombre])
libro, cobertura = resultado.libro, resultado.cobertura

repetidas = Counter(d.fila for d in cobertura.discrepancias)
print(f"documento                  {nombre}")
print(f"discrepancias en total     {len(cobertura.discrepancias)}")
print(f"filas distintas            {len(repetidas)}")
mas_de_una = {f: n for f, n in repetidas.items() if n > 1}
print(f"filas que salen mas de una vez: {len(mas_de_una)}")
for fila, veces in sorted(mas_de_una.items())[:10]:
    reglas = [d.regla for d in cobertura.discrepancias if d.fila == fila]
    print(f"  {fila}  x{veces}  reglas={reglas}")

print()
print(f"--- {objetivo} en detalle ---")
suyas = [d for d in cobertura.discrepancias if d.fila == objetivo]
for d in suyas:
    print(f"  regla={d.regla:16} indice={d.indice:6} "
          f"esperado={d.esperado} obtenido={d.obtenido}")

poliza = next((p for p in libro.polizas if p.poliza_id == objetivo), None)
if poliza is not None:
    print(f"  poliza: tipo={poliza.tipo!r} fecha={poliza.fecha!r} "
          f"folio={poliza.folio!r}")
    print(f"          descripcion={poliza.descripcion!r}")
cfdis = [c for c in libro.cfdi if c.poliza_id == objetivo]
print(f"  CFDI atados a esta poliza: {len(cfdis)}")
for c in cfdis:
    dentro = c.documento in (poliza.descripcion if poliza else "")
    print(f"    documento={c.documento!r} uuid={c.uuid!r} "
          f"cruza={'si' if dentro else 'NO'}")
print()
print("veredicto: "
      + ("dos comprobantes distintos, cada uno con su fallo"
         if len(suyas) == len([c for c in cfdis
                               if c.documento not in (poliza.descripcion if poliza else "")])
         else "las apariciones NO coinciden con los CFDI que fallan"))
