"""M1 (fase 8b): clasificar los 563 subtotales huerfanos de auxiliar-gume.

La 8a afirmo, desde tres ejemplos, que los huerfanos eran cuentas
acumulativas. Aqui se clasifican LOS 563 y, sobre todo, se mide el unico
numero que decide si hay defecto: el importe que no se leyo.
"""
import sys
from collections import defaultdict
from decimal import Decimal

sys.path.insert(0, "tests")
from conftest import REAL_PDFS

from contapdf.pipeline import procesar_auxiliar

aux = procesar_auxiliar(REAL_PDFS["auxiliar-gume"]).auxiliar
subtotales = [f for f in aux.filas if f.es_subtotal]
movimientos = [f for f in aux.filas if not f.es_subtotal]
con_movimiento = {f.cuenta for f in movimientos if f.cuenta}

print(f"filas                  {len(aux.filas)}")
print(f"subtotales             {len(subtotales)}")
print(f"cuentas con subtotal   {len({s.cuenta for s in subtotales})}")
print(f"movimientos            {len(movimientos)}")
print(f"cuentas con movimiento {len(con_movimiento)}")

huerfanos = [s for s in subtotales if s.cuenta not in con_movimiento]
print(f"huerfanos              {len(huerfanos)}")


def acumulativa(cuenta: str) -> bool:
    """Termina en un segmento de ceros: es una cuenta de nivel superior."""
    partes = (cuenta or "").split("-")
    return len(partes) > 1 and set(partes[-1]) == {"0"}


def importe(f) -> Decimal:
    return sum(abs(x) for x in (f.debe, f.haber) if x is not None)


grupos = defaultdict(list)
for s in huerfanos:
    grupos[(acumulativa(s.cuenta), importe(s) != 0)].append(s)

print()
print(f"{'clase':<14}{'con importe':>12}{'en ceros':>10}")
for acum in (True, False):
    print(f"{'acumulativa' if acum else 'de detalle':<14}"
          f"{len(grupos[(acum, True)]):>12}{len(grupos[(acum, False)]):>10}")

detalle_con_importe = grupos[(False, True)]
print()
print("cuentas de detalle con importe en el subtotal y SIN movimientos: "
      f"{len(detalle_con_importe)}")
print(f"importe no leido por esa via: {sum(importe(s) for s in detalle_con_importe)}")
for s in detalle_con_importe[:5]:
    print(f"  {s.cuenta} pag {s.pagina} debe {s.debe} haber {s.haber}")
