"""Deduplicacion de tokens repetidos.

Hay documentos que dibujan el mismo contenido varias veces: la familia
'manufacturas' repite x5 y su auxiliar x25, en coordenadas identicas;
Santander repite x2 con un corrimiento minimo para simular negritas. La
repeticion ahoga el clustering de columnas -- dos de esos documentos
detectan UNA sola columna -- asi que hay que quitarla antes de mirar la
geometria.

El criterio es contenido identico Y coordenada casi identica DENTRO del
mismo renglon. Los tres a la vez: deduplicar de mas borraria valores
legitimamente repetidos, y dos renglones con 0.00 en la misma columna son
dos datos, no uno.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from contapdf.ir import Page, Word

# 0.1 pt: absorbe el corrimiento del falso negrita (0.03 pt medido en
# Santander) sin llegar a juntar dos palabras distintas.
_PRECISION = 10


def _clave(word: Word) -> tuple[str, int, int]:
    return (word.text, round(word.x0 * _PRECISION), round(word.top * _PRECISION))


def multiplicador(words: Sequence[Word]) -> int:
    """Cuantas veces se repite el token mas repetido. 1 = sin repeticion."""
    if not words:
        return 1
    conteo = Counter(_clave(w) for w in words)
    return max(conteo.values())


def deduplicar(words: Sequence[Word]) -> tuple[Word, ...]:
    """Deja una sola copia de cada token repetido, en su primera aparicion."""
    vistos: set[tuple[str, int, int]] = set()
    salida: list[Word] = []
    for word in words:
        clave = _clave(word)
        if clave in vistos:
            continue
        vistos.add(clave)
        salida.append(word)
    return tuple(salida)


def deduplicar_pagina(page: Page) -> Page:
    """La misma pagina sin tokens repetidos. Si no los trae, es la misma."""
    limpias = deduplicar(page.words)
    if len(limpias) == len(page.words):
        return page
    return Page(number=page.number, width=page.width, height=page.height,
                words=limpias, ruling_lines=page.ruling_lines)
