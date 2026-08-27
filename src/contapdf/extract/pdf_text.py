"""Extraccion de texto nativo con pdfplumber, pagina por pagina."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from pathlib import Path

import pdfplumber

from contapdf.ir import Document, Page, Word

_LOG = logging.getLogger(__name__)
_EXTRA_ATTRS = ("fontname", "size")


def _to_word(raw: dict, page_number: int) -> Word:
    fontname = str(raw.get("fontname", ""))
    return Word(
        text=raw["text"],
        x0=float(raw["x0"]),
        x1=float(raw["x1"]),
        top=float(raw["top"]),
        bottom=float(raw["bottom"]),
        size=float(raw.get("size") or 0.0),
        bold="bold" in fontname.lower(),
        page=page_number,
    )


def _iter_pages(path: Path, page_numbers: tuple[int, ...] | None) -> Iterator[Page]:
    with pdfplumber.open(str(path)) as pdf:
        total = len(pdf.pages)
        objetivo = page_numbers or range(1, total + 1)
        for number in objetivo:
            if not 1 <= number <= total:
                _LOG.warning("pagina %s fuera de rango (%s tiene %s)",
                             number, path.name, total)
                continue
            page = pdf.pages[number - 1]
            try:
                words = tuple(
                    _to_word(w, number)
                    for w in page.extract_words(extra_attrs=list(_EXTRA_ATTRS))
                )
                yield Page(
                    number=number,
                    width=float(page.width),
                    height=float(page.height),
                    words=words,
                    ruling_lines=len(page.lines),
                )
            finally:
                # pdfplumber cachea los objetos de cada pagina visitada. Sin
                # esto, recorrer 968 paginas las acumula todas en memoria.
                page.close()


def extract(path: str | Path,
            *, page_numbers: Sequence[int] | None = None) -> Document:
    """Abre un PDF y devuelve un Document que entrega sus paginas al vuelo.

    El PDF se reabre cada vez que se llama a Document.open_pages(): no queda
    ningun descriptor abierto entre llamadas y dos recorridos dan lo mismo.
    'page_numbers' es 1-based y respeta el orden en que se pide.
    """
    source = Path(path)
    objetivo = tuple(page_numbers) if page_numbers is not None else None

    with pdfplumber.open(str(source)) as pdf:
        page_count = len(pdf.pages)

    return Document(
        source=str(source),
        page_count=page_count,
        open_pages=lambda: _iter_pages(source, objetivo),
    )
