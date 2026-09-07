"""M3 (fase 8d): el mensaje de `cfdi_cruzado` en las TRES salidas.

La 8a corrigio «no cuadra el dato, no el importe». La pagina web lo muestra
bien; el Excel sigue escribiendo `esperado 0.00 / obtenido 0.00`. La
pregunta es donde llego el arreglo y donde no. Se comparan los tres caminos
que consumen la MISMA `Discrepancia`: el CLI, el Excel y la vista web.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

import openpyxl  # noqa: E402
from conftest import REAL_PDFS  # noqa: E402

from contapdf import cli  # noqa: E402
from contapdf.export.excel import exportar_polizas  # noqa: E402
from contapdf.pipeline import procesar_polizas  # noqa: E402
from contapdf.web.vista import _discrepancia  # noqa: E402

nombre = sys.argv[1] if len(sys.argv) > 1 else "poliza"
destino_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/tmp")

resultado = procesar_polizas(REAL_PDFS[nombre])
cobertura = resultado.cobertura
cruzadas = [d for d in cobertura.discrepancias if d.regla == "cfdi_cruzado"]

print(f"documento                       {nombre}")
print(f"discrepancias de cfdi_cruzado   {len(cruzadas)}")
print(f"de ellas con esperado==obtenido {sum(1 for d in cruzadas
                                             if d.esperado == d.obtenido)}")
print()
print("La Discrepancia es UNA sola; lo que cambia es quien la formatea.")
print("`Discrepancia.esperado/obtenido` son `Decimal` obligatorios, asi que")
print("una regla que cruza identidades no tiene donde decir que no hay")
print("importe: rellena los dos con cero.")
print()

muestra = cruzadas[0]
print(f"--- el caso de muestra: {muestra.fila} ---")
print(f"  el dato crudo    esperado={muestra.esperado} "
      f"obtenido={muestra.obtenido}")

# 1) La vista web
print(f"  1) web           {_discrepancia(muestra)}")

# 2) El CLI
buffer = io.StringIO()
cli._cola(cobertura, None, buffer, plantilla=None, reutilizada=False)
linea = next((ln for ln in buffer.getvalue().splitlines()
              if muestra.fila in ln and "cfdi_cruzado" in ln), "(no impresa)")
print(f"  2) CLI           {linea.strip()}")

# 3) El Excel
salida = destino_dir / f"m3-{nombre}.xlsx"
exportar_polizas(resultado.libro, cobertura, salida)
hoja = openpyxl.load_workbook(salida)["Validacion"]
for fila in hoja.iter_rows(min_row=2, values_only=True):
    if fila[0] == muestra.fila and fila[1] == "cfdi_cruzado":
        print(f"  3) Excel         fila={fila[0]} regla={fila[1]} "
              f"esperado={fila[2]} obtenido={fila[3]}")
        break
else:
    print("  3) Excel         (no encontrada en el bloque de detalle)")

print()
print("--- donde vive la correccion hoy ---")
print("  web/vista.py::_discrepancia deduce `numerica = esperado != obtenido`")
print("  y deja los dos campos en blanco cuando son iguales. Es una")
print("  INFERENCIA local de la capa web; ni el CLI ni el exportador la")
print("  hacen, y no pueden hacerla sin repetirla.")
