"""Etiquetado de columnas: de coordenadas a nombres.

Separado de columns.py a proposito. columns.py es geometria pura y se
testea sin heuristicas de texto; aqui vive la semantica, que ademas
necesita saber donde empieza la tabla (layout.region).
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import replace

from contapdf.ir import ColumnSpec, Line, Word
from contapdf.layout.columns import is_amount
from contapdf.layout.region import Region, lines_within


def _distance(word: Word, column: ColumnSpec, pad: float) -> float:
    center = (word.x0 + word.x1) / 2
    if column.x_min - pad <= center <= column.x_max + pad:
        return 0.0
    return min(abs(center - column.x_min), abs(center - column.x_max))


def _header_block(lines: Sequence[Line], max_lines: int,
                  pitch_factor: float) -> list[Line]:
    """Los renglones de etiquetas al inicio de la region, de arriba a abajo.

    La region empieza en el encabezado, asi que el bloque son los renglones
    sin montos que van antes del primer renglon de datos. De esos, el de
    hasta abajo es el renglon de etiquetas; los de arriba solo cuentan si
    estan MAS APRETADOS que el interlineado de los datos.

    Ese es el criterio que separa una etiqueta partida en dos renglones
    ('Saldo Inicial' / 'Deudor', 6.5pt en la balanza) de un titulo de
    seccion ('DETALLE DE OPERACIONES', 19.1pt en el estado de cuenta, con
    datos a 10pt). Un titulo se compone suelto; una etiqueta partida, no.
    """
    encabezado: list[Line] = []
    for ln in lines:
        if any(is_amount(w.text) for w in ln.words):
            break
        encabezado.append(ln)
    if not encabezado:
        return []
    encabezado = encabezado[-max_lines:]

    datos = lines[len(encabezado):]
    pitches = [b.top - a.top for a, b in zip(datos, datos[1:])]
    if len(pitches) < 2:
        return encabezado[-1:]
    limite = statistics.median(pitches) * pitch_factor

    bloque = [encabezado[-1]]
    for ln in reversed(encabezado[:-1]):
        if bloque[0].top - ln.top > limite:
            break
        bloque.insert(0, ln)
    return bloque


def assign(lines: Sequence[Line], region: Region | None,
           columns: Sequence[ColumnSpec], *, max_distance: float = 40.0,
           max_header_lines: int = 4, pitch_factor: float = 1.3) -> list[ColumnSpec]:
    """Devuelve las columnas con 'header' lleno. No muta las que recibe.

    Cada palabra del encabezado va a la columna mas cercana a su centro, y
    se descarta si ninguna queda a menos de 'max_distance': en el estado de
    cuenta hay etiquetas ('Depósitos') cuya columna no existe en esa pagina
    porque ningun movimiento la usa.
    """
    etiquetadas = [replace(c) for c in columns]
    if region is None or not etiquetadas:
        return etiquetadas

    partes: dict[int, list[tuple[float, float, str]]] = {}
    for ln in _header_block(lines_within(lines, region), max_header_lines,
                            pitch_factor):
        for w in ln.words:
            elegida, menor, ancho = None, float("inf"), float("inf")
            for col in etiquetadas:
                d = _distance(w, col, pad=6.0)
                # Cuando varias columnas contienen la etiqueta gana la mas
                # angosta: hay documentos donde una columna de texto ancha
                # se imprime encima de las numericas y las contiene a todas,
                # y si gana ella las de monto se quedan sin nombre.
                if d < menor or (d == menor and col.x_max - col.x_min < ancho):
                    elegida, menor, ancho = col, d, col.x_max - col.x_min
            if elegida is not None and menor < max_distance:
                partes.setdefault(elegida.index, []).append((w.top, w.x0, w.text))

    for col in etiquetadas:
        col.header = " ".join(t for _, _, t in sorted(partes.get(col.index, [])))
    return etiquetadas
