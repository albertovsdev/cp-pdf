"""Exportacion a Excel.

PLAN 1.3: si la validacion falla no se entrega un Excel limpio. Las filas
afectadas se marcan y el detalle va en una hoja aparte.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from contapdf.parsers.balanza import Balanza
from contapdf.validate.rules import Discrepancia

_ENCABEZADOS = ("cuenta", "nivel", "cuenta_padre", "naturaleza", "nombre",
                "saldo_ini_deudor", "saldo_ini_acreedor", "debe", "haber",
                "saldo_fin_deudor", "saldo_fin_acreedor", "es_acumulativa")
_MONTOS = ("saldo_ini_deudor", "saldo_ini_acreedor", "debe", "haber",
           "saldo_fin_deudor", "saldo_fin_acreedor")
_FORMATO_MONTO = "#,##0.00"
_ANCHOS = (14, 6, 14, 5, 42, 16, 18, 16, 16, 18, 18, 14)


def exportar_balanza(balanza: Balanza, discrepancias: Sequence[Discrepancia],
                     destino: Path) -> Path:
    """Escribe el .xlsx en 'destino' y devuelve la ruta.

    La ruta llega como parametro: el nucleo no decide donde escribir, para
    que cada trabajo mande a su propio directorio de tenant.
    """
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Balanza"

    negrita = Font(bold=True)
    alerta = PatternFill(fill_type="solid", start_color="FFF4CCCC",
                         end_color="FFF4CCCC")

    hoja.append(list(_ENCABEZADOS))
    for celda in hoja[1]:
        celda.font = negrita
    for columna, ancho in zip(hoja.iter_cols(min_row=1, max_row=1), _ANCHOS):
        hoja.column_dimensions[columna[0].column_letter].width = ancho
    hoja.freeze_panes = "A2"

    marcadas = {d.indice for d in discrepancias if d.indice >= 0}
    for indice, fila in enumerate(balanza.filas):
        hoja.append([getattr(fila, campo) for campo in _ENCABEZADOS])
        renglon = hoja[hoja.max_row]
        for celda, campo in zip(renglon, _ENCABEZADOS):
            if campo in _MONTOS:
                celda.number_format = _FORMATO_MONTO
            if indice in marcadas:
                celda.fill = alerta

    if discrepancias:
        detalle = libro.create_sheet("Validacion")
        detalle.append(["fila", "regla", "esperado", "obtenido"])
        for celda in detalle[1]:
            celda.font = negrita
        for d in discrepancias:
            detalle.append([d.fila, d.regla, d.esperado, d.obtenido])
            for celda in detalle[detalle.max_row][2:]:
                celda.number_format = _FORMATO_MONTO
        for columna, ancho in zip(detalle.iter_cols(min_row=1, max_row=1),
                                  (16, 20, 18, 18)):
            detalle.column_dimensions[columna[0].column_letter].width = ancho
        detalle.freeze_panes = "A2"

    libro.save(str(destino))
    return destino
