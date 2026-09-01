"""Eleccion de estrategia de extraccion.

pdf_text es el default y sirve para casi todo. pdf_chars cuesta mas y solo
hace falta cuando el documento imprime texto encimado. La eleccion se
decide con una MUESTRA y se puede imponer: es lo que la fase 4 guardara en
la plantilla, para no volver a detectarla en cada corrida.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from pathlib import Path

from contapdf.extract import pdf_chars, pdf_text
from contapdf.extract.dedup import deduplicar_pagina, multiplicador
from contapdf.extract.tokens import separar_fecha_pegada
from contapdf.ir import Document, Page, Word

_LOG = logging.getLogger(__name__)
_RE_MONTO = re.compile(r"-?\d{1,3}(,\d{3})*\.\d{2}")
_RE_MONTO_SOLO = re.compile(r"^-?\d{1,3}(,\d{3})*\.\d{2}$")


def tokens_contaminados(words: Sequence[Word]) -> list[Word]:
    """Palabras que mezclan glifos de dos corridas distintas.

    La firma es que la palabra CONTIENE un monto sin SER un monto: o trae
    letras pegadas ('SERDAN-228,200.69'), o trae dos montos seguidos
    ('1,185.22-227,015.47'). Una palabra sana es el monto entero o no
    contiene ninguno.
    """
    sucias: list[Word] = []
    for w in words:
        texto = w.text
        if _RE_MONTO_SOLO.match(texto):
            continue
        hallados = list(_RE_MONTO.finditer(texto))
        if not hallados:
            continue
        if len(hallados) > 1 or any(c.isalpha() for c in texto):
            sucias.append(w)
    return sucias


def palabras_traslapadas(words: Sequence[Word]) -> int:
    """Palabras que se pisan en x dentro del mismo renglon.

    Es la firma de una columna impresa ENCIMA de otra: al ordenar por x
    las dos se intercalan y ninguna queda legible. Distinto de los glifos
    pegados, que producen una sola palabra invalida.
    """
    por_renglon: dict[int, list[Word]] = {}
    for w in words:
        por_renglon.setdefault(round(w.top), []).append(w)
    traslapadas = 0
    for renglon in por_renglon.values():
        ordenadas = sorted(renglon, key=lambda w: w.x0)
        for a, b in zip(ordenadas, ordenadas[1:]):
            if b.x0 < a.x1 - 0.5:
                traslapadas += 1
    return traslapadas


def esta_contaminada(path: str | Path, *, paginas_muestra: int = 2,
                     umbral_traslape: float = 0.02) -> bool:
    """True si conviene extraer por corridas en vez de por palabras.

    Medido sobre seis documentos reales: Business Pro da 27 tokens
    contaminados y los otros cinco dan cero. Basta con que aparezca uno:
    cada token contaminado es un renglon que se leeria mal.
    """
    documento = pdf_text.extract(path)
    paginas = documento.open_pages()
    try:
        for numero, page in enumerate(paginas, start=1):
            if tokens_contaminados(page.words):
                return True
            # Medido: el libro diario da 0.219 de palabras traslapadas y
            # los otros cinco documentos dan exactamente 0.
            if page.words and (palabras_traslapadas(page.words)
                               / len(page.words)) > umbral_traslape:
                return True
            if numero >= paginas_muestra:
                break
    finally:
        paginas.close()
    return False


def extraer(path: str | Path, *, estrategia: str | None = None,
            page_numbers: Sequence[int] | None = None,
            paginas_muestra: int = 2) -> tuple[Document, str]:
    """Devuelve (documento, nombre de la estrategia usada)."""
    if estrategia is None:
        estrategia = ("pdf_chars"
                      if esta_contaminada(path, paginas_muestra=paginas_muestra)
                      else "pdf_text")
        _LOG.info("estrategia de extraccion elegida para %s: %s", path, estrategia)

    if estrategia == "pdf_chars":
        documento = pdf_chars.extract(path, page_numbers=page_numbers)
    elif estrategia == "pdf_text":
        documento = pdf_text.extract(path, page_numbers=page_numbers)
    else:
        raise ValueError(f"estrategia desconocida: {estrategia!r}")
    return _normalizado(documento), estrategia


def _normalizado(documento: Document) -> Document:
    """El mismo documento sin repeticiones y con los tokens pegados sueltos.

    Va aqui y no en los extractores: son propiedades del archivo, no de la
    manera de leerlo, y las dos estrategias las sufren igual. Una pagina
    que no traiga ninguna de las dos sale intacta, asi que los documentos
    que ya funcionaban no cambian.
    """
    abrir = documento.open_pages

    def paginas():
        for page in abrir():
            limpia = deduplicar_pagina(page)
            if limpia is not page:
                _LOG.info("pagina %s: repeticion x%s quitada", page.number,
                          multiplicador(page.words))
            sueltas = separar_fecha_pegada(limpia.words)
            if len(sueltas) != len(limpia.words):
                limpia = Page(number=limpia.number, width=limpia.width,
                              height=limpia.height, words=sueltas,
                              ruling_lines=limpia.ruling_lines)
            yield limpia

    return Document(source=documento.source, page_count=documento.page_count,
                    open_pages=paginas)
