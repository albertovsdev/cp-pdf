"""M2 (fase 8d): como se cuenta el universo de la regla `jerarquia`.

La regla reporta sobre `balanza` 56 aplicables y 52 evaluados -- 4
relaciones sin evaluar -- y el motivo nombra 2 cuentas padre. Al filtrar el
Excel por esas cuentas salen 2 filas. Los tres numeros no se explican entre
si a simple vista; esto los descompone.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from conftest import REAL_PDFS  # noqa: E402

from contapdf.pipeline import procesar_balanza  # noqa: E402
from contapdf.validate.rules import _hijas_directas  # noqa: E402

nombre = sys.argv[1] if len(sys.argv) > 1 else "balanza"
resultado = procesar_balanza(REAL_PDFS[nombre])
filas = resultado.balanza.filas
regla = next(r for r in resultado.cobertura.reglas if r.regla == "jerarquia")

presentes = {f.cuenta for f in filas}
por_cuenta = {f.cuenta: f for f in filas}
padres_referidos = {f.cuenta_padre for f in filas if f.cuenta_padre}
# `_hijas_directas` recibe la FILA del padre, no su numero: el criterio es
# `cuenta_padre == padre.cuenta AND nivel == padre.nivel + 1`.
con_hijas = [f for f in filas if _hijas_directas(filas, f)]
huerfanos = sorted(padres_referidos - presentes)
presentes_sin_hijas = sorted(
    c for c in padres_referidos & presentes
    if not _hijas_directas(filas, por_cuenta[c]))

print(f"documento                       {nombre}")
print(f"renglones                       {len(filas)}")
print()
print("--- lo que la regla reporta ---")
print(f"aplicables                      {regla.aplicables}")
print(f"evaluados                       {regla.evaluados}")
print(f"sin evaluar                     {regla.aplicables - regla.evaluados}")
print(f"motivo                          {regla.motivo}")
print()
print("--- de donde sale cada numero ---")
print(f"padres distintos referidos      {len(padres_referidos)}"
      f"  x2 (debe y haber) = {len(padres_referidos) * 2}")
print(f"padres que SI estan y con hijas {len(con_hijas)}"
      f"  x2 = {len(con_hijas) * 2}")
print(f"padres referidos y ausentes     {len(huerfanos)} -> {huerfanos}")
print(f"padres presentes sin hijas      {len(presentes_sin_hijas)}"
      f" -> {presentes_sin_hijas}")
print()
cuadra = len(padres_referidos) - len(con_hijas) == len(huerfanos) + len(presentes_sin_hijas)
print(f"los tres numeros se explican    {'SI' if cuadra else 'NO'}")
print()
print("--- filtrar el Excel por las cuentas del motivo ---")
for cuenta in huerfanos:
    contienen = [f.cuenta for f in filas if cuenta in f.cuenta]
    hijas = [f.cuenta for f in filas if f.cuenta_padre == cuenta]
    print(f"  {cuenta}: como cuenta propia {'si' if cuenta in presentes else 'NO'};"
          f" filas cuyo numero la contiene {len(contienen)} -> {contienen[:6]};"
          f" filas que la declaran padre {len(hijas)} -> {hijas[:6]}")
