"""Acota el analisis a la zona de la tabla.

Sin esto, la pagina 1 de un estado de cuenta detecta una sola columna: el
clustering ve el domicilio del banco, el resumen de comisiones y el sello
digital, y ninguno respeta la rejilla de la tabla.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

from contapdf.ir import Line
from contapdf.layout.columns import amount_anchors, is_amount


class Region(NamedTuple):
    """Franja vertical de la pagina, en coordenadas de pdfplumber."""

    top: float
    bottom: float


def _anchors_hit(line: Line, anchors: Sequence[float], tol: float) -> int:
    """Cuantas columnas de monto DISTINTAS toca el renglon.

    Distintas importa: dos numeros pegados al mismo borde derecho (el '9 de
    9' del pie de pagina) no son un renglon de tabla.
    """
    tocadas: set[int] = set()
    for w in line.words:
        if not is_amount(w.text):
            continue
        for i, anchor in enumerate(anchors):
            if abs(w.x1 - anchor) <= tol:
                tocadas.add(i)
                break
    return len(tocadas)


def _runs(indexes: Sequence[int], max_gap: int) -> list[list[int]]:
    """Parte los renglones de datos en bloques, tolerando huecos cortos.

    El hueco existe porque hay renglones que pertenecen a la tabla sin traer
    montos: la descripcion que sigue en la linea de abajo, el 'Conciliado'
    del auxiliar. Un hueco largo si separa bloques distintos del documento.
    """
    bloques: list[list[int]] = []
    for i in indexes:
        if bloques and i - bloques[-1][-1] <= max_gap + 1:
            bloques[-1].append(i)
        else:
            bloques.append([i])
    return bloques


def find_table_region(
    lines: Sequence[Line],
    *,
    tol: float = 3.0,
    min_support: int = 3,
    min_amount_columns: int = 2,
    max_gap_lines: int = 8,
    max_header_lines: int = 3,
) -> Region | None:
    """Devuelve (top, bottom) de la tabla, o None si la pagina no tiene una.

    La tabla es el bloque mas grande de renglones que tocan al menos
    'min_amount_columns' columnas de monto distintas, extendido hacia arriba
    sobre sus renglones de encabezado. None no es un error: la pagina 398 del
    auxiliar es un bloque de totales y no tiene renglones de movimiento.
    """
    anchors = amount_anchors(lines, tol=tol, min_support=min_support)
    if not anchors:
        return None

    datos = [i for i, ln in enumerate(lines)
             if _anchors_hit(ln, anchors, tol * 2) >= min_amount_columns]
    if not datos:
        return None

    bloques = _runs(datos, max_gap_lines)
    mejor = max(bloques, key=lambda b: (len(b),
                                        lines[b[-1]].bottom - lines[b[0]].top))

    inicio = mejor[0]
    tope = max(-1, inicio - max_header_lines)
    for i in range(inicio - 1, tope, -1):
        ln = lines[i]
        # El encabezado no trae montos y trae varias etiquetas ('Saldo
        # Inicial' / 'Deudor'). Un renglon de una sola palabra ya es otra
        # cosa: un titulo de seccion o un numero de pagina suelto.
        if len(ln.words) < 2 or any(is_amount(w.text) for w in ln.words):
            break
        inicio = i

    return Region(top=lines[inicio].top, bottom=lines[mejor[-1]].bottom)


def lines_within(lines: Sequence[Line], region: Region | None) -> list[Line]:
    """Los renglones cuyo centro cae dentro de la region.

    Por el centro y no por top/bottom: un renglon de celdas altas asoma
    fuera de la franja por unos puntos sin dejar de pertenecer a ella.
    """
    if region is None:
        return list(lines)
    return [ln for ln in lines
            if region.top <= (ln.top + ln.bottom) / 2 <= region.bottom]
