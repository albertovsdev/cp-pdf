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
from contapdf.validate.rules import NO_VERIFICABLE, Cobertura

_ENCABEZADOS = ("cuenta", "nivel", "cuenta_padre", "naturaleza", "nombre",
                "saldo_ini_deudor", "saldo_ini_acreedor", "debe", "haber",
                "saldo_fin_deudor", "saldo_fin_acreedor", "es_acumulativa")
_MONTOS = ("saldo_ini_deudor", "saldo_ini_acreedor", "debe", "haber",
           "saldo_fin_deudor", "saldo_fin_acreedor")
_FORMATO_MONTO = "#,##0.00"
_ANCHOS = (14, 6, 14, 5, 42, 16, 18, 16, 16, 18, 18, 14)


def _detalle(regla) -> str:
    partes = []
    if regla.exactas:
        partes.append(f"{regla.exactas} exacta"
                      + ("s" if regla.exactas != 1 else ""))
    if regla.con_tolerancia:
        partes.append(f"{len(regla.con_tolerancia)} dentro de tolerancia: "
                      + ", ".join(regla.con_tolerancia[:5]))
    if regla.discrepancias:
        partes.append(f"{len(regla.discrepancias)} con diferencia")
    return "; ".join(partes) or f"{regla.comprobaciones} comprobaciones"


def exportar_balanza(balanza: Balanza, cobertura: Cobertura,
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

    discrepancias = cobertura.discrepancias
    marcadas = {d.indice for d in discrepancias if d.indice >= 0}
    for indice, fila in enumerate(balanza.filas):
        hoja.append([getattr(fila, campo) for campo in _ENCABEZADOS])
        renglon = hoja[hoja.max_row]
        for celda, campo in zip(renglon, _ENCABEZADOS):
            if campo in _MONTOS:
                celda.number_format = _FORMATO_MONTO
            if indice in marcadas:
                celda.fill = alerta

    # La hoja de validacion va siempre, aunque no haya discrepancias: un
    # resultado sin su cobertura no se entrega (PLAN 2).
    detalle = libro.create_sheet("Validacion")
    detalle.append(["regla", "estado", "detalle"])
    for celda in detalle[1]:
        celda.font = negrita
    for regla in cobertura.reglas:
        detalle.append([regla.regla, regla.estado,
                        regla.motivo if regla.estado == NO_VERIFICABLE
                        else _detalle(regla)])
    detalle.append([])
    detalle.append(["fila", "regla", "esperado", "obtenido"])
    for celda in detalle[detalle.max_row]:
        celda.font = negrita
    for d in discrepancias:
        detalle.append([d.fila, d.regla, d.esperado, d.obtenido])
        for celda in detalle[detalle.max_row][2:]:
            celda.number_format = _FORMATO_MONTO
    for columna, ancho in zip(detalle.iter_cols(min_row=1, max_row=1),
                              (18, 18, 60)):
        detalle.column_dimensions[columna[0].column_letter].width = ancho
    detalle.freeze_panes = "A2"

    libro.save(str(destino))
    return destino
