"""Representacion intermedia compartida por toda la extraccion.

Texto nativo y OCR producen exactamente esto, asi que los parsers no saben
de donde vino el texto y se pueden testear sin instalar Tesseract.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class Word:
    """Una palabra con su caja en coordenadas de pagina (top crece hacia abajo)."""

    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    size: float
    bold: bool
    page: int


@dataclass
class Line:
    """Un renglon logico: las palabras que comparten banda vertical."""

    words: list[Word]
    top: float
    bottom: float
    page: int


@dataclass
class ColumnSpec:
    """Una columna detectada.

    'align' dice por que borde se agrupo: los montos comparten x1 y el texto
    comparte x0. x_min/x_max son la extension observada, no el ancla.
    """

    index: int
    align: str  # 'left' | 'right'
    x_min: float
    x_max: float
    support: int
    header: str = ""


@dataclass(frozen=True)
class Page:
    """Una pagina ya extraida. Es la unidad de trabajo del sistema."""

    number: int
    width: float
    height: float
    words: tuple[Word, ...]
    ruling_lines: int = 0

    @property
    def has_text_layer(self) -> bool:
        return bool(self.words)


@dataclass(frozen=True)
class Document:
    """Un PDF abierto.

    No guarda las paginas: guarda COMO abrirlas. Con documentos de 968
    paginas en un servidor compartido, materializarlas todas no es opcional
    que se pueda dejar para despues.
    """

    source: str
    page_count: int
    open_pages: Callable[[], Iterator[Page]]
