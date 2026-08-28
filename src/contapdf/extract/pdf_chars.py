"""Extraccion a nivel de caracter, cortando por corrida del content stream.

Estrategia ALTERNATIVA a pdf_text, no un reemplazo. Existe porque hay
documentos donde la descripcion se imprime encima de las columnas
numericas: pdfplumber junta glifos contiguos en x sin importar que vengan
de corridas de texto distintas, y produce palabras como 'A4N1,608,185.15'
(la descripcion 'AN' intercalada con el importe '41,608,185.15').

Un PDF dibuja el texto por corridas. Dos corridas pueden solaparse en la
pagina, pero los caracteres de una misma corrida salen juntos y avanzando
en x. Cortar por ahi separa lo que la geometria sola no puede.

Produce el mismo IR que pdf_text, asi que layout/ y parsers/ no cambian.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from pathlib import Path

import pdfplumber

from contapdf.ir import Document, Page, Word

_RE_MONTO = re.compile(r"-?\d{1,3}(,\d{3})*\.\d{2}")
_HUECO = 1.2  # pt: separacion minima para cortar palabra dentro de una corrida


def _corridas(chars: Sequence[dict]) -> list[list[dict]]:
    """Parte los caracteres en corridas del content stream.

    Los caracteres llegan en el orden en que el PDF los dibuja. Mientras x
    avanza, es la misma corrida; si retrocede, empezo otra.
    """
    salida: list[list[dict]] = []
    actual: list[dict] = []
    for c in chars:
        if actual and c["x0"] < actual[-1]["x1"] - 0.5:
            salida.append(actual)
            actual = []
        actual.append(c)
    if actual:
        salida.append(actual)
    return salida


def _separar_montos(grupo: list[dict], texto: str) -> list[list[dict]]:
    """Parte un grupo que trae montos pegados a otra cosa.

    Pasa con el signo negativo, que no lleva espacio delante:
    'SERDAN-228,200.69' es descripcion + importe, y
    '1,185.22-227,015.47' son dos importes seguidos.
    """
    hallados = list(_RE_MONTO.finditer(texto))
    if not hallados or hallados[-1].end() != len(texto):
        return [grupo]
    if len(hallados) == 1 and hallados[0].start() == 0:
        return [grupo]  # ya es un monto limpio

    partes: list[list[dict]] = []
    posicion = 0
    for m in hallados:
        if m.start() > posicion:
            partes.append(grupo[posicion:m.start()])
        partes.append(grupo[m.start():m.end()])
        posicion = m.end()
    return partes


def _palabras(corrida: Sequence[dict], hueco: float) -> list[list[dict]]:
    """Corta una corrida en palabras: por espacio y por hueco horizontal."""
    grupos: list[list[dict]] = []
    actual: list[dict] = []
    for c in corrida:
        if c["text"].isspace():
            if actual:
                grupos.append(actual)
                actual = []
            continue
        if actual and c["x0"] - actual[-1]["x1"] > hueco:
            grupos.append(actual)
            actual = []
        actual.append(c)
    if actual:
        grupos.append(actual)

    salida: list[list[dict]] = []
    for g in grupos:
        salida.extend(_separar_montos(g, "".join(c["text"] for c in g)))
    return [g for g in salida if g]


def _to_word(grupo: Sequence[dict], page_number: int) -> Word:
    fontname = str(grupo[0].get("fontname", ""))
    return Word(
        text="".join(c["text"] for c in grupo),
        x0=float(grupo[0]["x0"]),
        x1=float(grupo[-1]["x1"]),
        top=float(min(c["top"] for c in grupo)),
        bottom=float(max(c["bottom"] for c in grupo)),
        size=float(grupo[0].get("size") or 0.0),
        bold="bold" in fontname.lower(),
        page=page_number,
    )


def _iter_pages(path: Path, page_numbers: tuple[int, ...] | None,
                hueco: float) -> Iterator[Page]:
    with pdfplumber.open(str(path)) as pdf:
        total = len(pdf.pages)
        for number in (page_numbers or range(1, total + 1)):
            if not 1 <= number <= total:
                continue
            page = pdf.pages[number - 1]
            try:
                palabras = [
                    _to_word(g, number)
                    for corrida in _corridas(page.chars)
                    for g in _palabras(corrida, hueco)
                ]
                palabras.sort(key=lambda w: (w.top, w.x0))
                yield Page(number=number, width=float(page.width),
                           height=float(page.height), words=tuple(palabras),
                           ruling_lines=len(page.lines))
            finally:
                page.close()


def extract(path: str | Path, *, page_numbers: Sequence[int] | None = None,
            hueco: float = _HUECO) -> Document:
    """Abre un PDF y entrega sus paginas por corridas, una por una."""
    source = Path(path)
    objetivo = tuple(page_numbers) if page_numbers is not None else None

    with pdfplumber.open(str(source)) as pdf:
        page_count = len(pdf.pages)

    return Document(source=str(source), page_count=page_count,
                    open_pages=lambda: _iter_pages(source, objetivo, hueco))
