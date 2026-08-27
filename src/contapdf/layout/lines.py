"""Agrupamiento de palabras en renglones logicos."""

from __future__ import annotations

from collections.abc import Sequence

from contapdf.ir import Line, Word

_LOOKBACK = 3


def group(words: Sequence[Word], tol: float = 2.5) -> list[Line]:
    """Agrupa palabras en renglones por SOLAPAMIENTO vertical.

    Agrupar por 'top' falla en tablas con celdas altas: en las polizas el
    importe esta centrado en la celda y su 'top' difiere ~6pt del de la
    etiqueta, aunque sea el mismo renglon logico.

    Criterio: una palabra entra al renglon si su centro vertical cae dentro
    del alto acumulado del renglon, mas la tolerancia. Es mas permisivo que
    comparar 'top' y aun asi no se traga la fila siguiente, porque el centro
    de otra fila queda fuera del rango.
    """
    ordered = sorted(words, key=lambda w: (w.top, w.x0))

    grupos: list[list[Word]] = []
    spans: list[tuple[float, float]] = []

    for word in ordered:
        center = (word.top + word.bottom) / 2
        colocada = False
        # Solo se revisan los ultimos renglones abiertos: la lista viene
        # ordenada por 'top', asi que mas atras ya no puede haber solape.
        for i in range(len(grupos) - 1, max(-1, len(grupos) - 1 - _LOOKBACK), -1):
            top, bottom = spans[i]
            if top - tol <= center <= bottom + tol:
                grupos[i].append(word)
                spans[i] = (min(top, word.top), max(bottom, word.bottom))
                colocada = True
                break
        if not colocada:
            grupos.append([word])
            spans.append((word.top, word.bottom))

    lines = [
        Line(
            words=sorted(g, key=lambda w: w.x0),
            top=span[0],
            bottom=span[1],
            page=g[0].page,
        )
        for g, span in zip(grupos, spans)
    ]
    lines.sort(key=lambda ln: (ln.top, ln.words[0].x0))
    return lines
