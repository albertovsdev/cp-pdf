"""Piezas comunes a todos los parsers.

Un parser toma un Document y devuelve datos: no imprime, no escribe
archivos y no depende del directorio actual.
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Protocol

from contapdf.ir import ColumnSpec, Document, Line, Page, Word
from contapdf.layout.columns import detect
from contapdf.layout.headers import assign
from contapdf.layout.lines import group
from contapdf.layout.region import find_table_region, lines_within

_LOG = logging.getLogger(__name__)

_RE_DECIMAL = re.compile(r"^\d+(\.\d+)?$|^\.\d+$")
# Base de 3 digitos o mas, con subcuentas opcionales: 101, 101-01,
# 102-01-0001. Mas permisivo que el de layout/columns.py a proposito: aqui
# ya se sabe que la celda es la columna de cuenta, asi que no hay riesgo de
# confundir un folio con una cuenta.
_RE_CUENTA = re.compile(r"^\d{3,}(-\d{1,6})*$")


def parse_monto(texto: str) -> Decimal:
    """Convierte el texto de una celda de dinero a Decimal.

    Unico lugar donde se parsea dinero en todo el sistema. En float, 0.10
    no es exacto y la suma de cientos de renglones acumula error hasta
    romper la validacion por un descuadre que el documento no tiene.

    Acepta separadores de miles, '$', signo negativo y la convencion
    contable de parentesis. La celda vacia vale cero: en estas balanzas los
    ceros vienen impresos, pero un OCR puede perderlos.
    """
    s = texto.strip()
    if not s:
        return Decimal(0)

    negativo = s.startswith("(") and s.endswith(")")
    if negativo:
        s = s[1:-1]
    s = s.replace("$", "").replace(",", "").replace(" ", "").strip()
    if s.startswith("-"):
        negativo = True
        s = s[1:]
    if not s:
        return Decimal(0)
    if not _RE_DECIMAL.match(s):
        raise ValueError(f"no es un monto: {texto!r}")

    try:
        valor = Decimal(s)
    except InvalidOperation as exc:  # pragma: no cover - _RE_DECIMAL ya filtro
        raise ValueError(f"no es un monto: {texto!r}") from exc
    return -valor if negativo else valor


def es_cuenta(texto: str) -> bool:
    """True si la celda contiene un numero de cuenta contable."""
    return bool(_RE_CUENTA.match(texto.strip()))


def normalizar(texto: str) -> str:
    """Minusculas, sin acentos y sin puntuacion: para comparar encabezados.

    'Saldo Inicial Deudor' y 'SALDO INICIAL DEUDOR' son la misma columna.
    """
    plano = unicodedata.normalize("NFKD", texto.lower())
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", plano).split())


@dataclass(frozen=True)
class Layout:
    """Las columnas de la tabla, ya detectadas y etiquetadas."""

    columns: tuple[ColumnSpec, ...]

    @property
    def headers(self) -> tuple[str, ...]:
        return tuple(c.header for c in self.columns)

    def indice_de(self, word: Word, *, max_distance: float = 40.0) -> int | None:
        centro = (word.x0 + word.x1) / 2
        elegida, menor = None, math.inf
        for col in self.columns:
            if col.x_min - 6 <= centro <= col.x_max + 6:
                distancia = 0.0
            else:
                distancia = min(abs(centro - col.x_min), abs(centro - col.x_max))
            if distancia < menor:
                elegida, menor = col, distancia
        return elegida.index if elegida is not None and menor < max_distance else None


def detectar_layout(paginas: Sequence[Page], *, tol: float = 3.0,
                    min_support: int = 3) -> Layout | None:
    """Deduce el layout de una MUESTRA de paginas ya leidas.

    Toma la union horizontal de las columnas de la muestra: cada pagina las
    delimita segun los valores que le tocaron, y un importe mas largo en
    otra pagina puede rebasar el borde. La union evita que ese valor quede
    fuera de su columna.
    """
    detectadas: list[list[ColumnSpec]] = []
    for page in paginas:
        lines = group(page.words)
        region = find_table_region(lines)
        if region is None:
            continue
        columnas = assign(lines, region,
                          detect(lines_within(lines, region), tol=tol,
                                 min_support=min_support))
        if columnas:
            detectadas.append(columnas)

    if not detectadas:
        return None

    union = [replace(c) for c in detectadas[0]]
    for otras in detectadas[1:]:
        if len(otras) != len(union):
            _LOG.warning("la muestra no coincide: %s columnas contra %s; "
                         "me quedo con la primera", len(otras), len(union))
            continue
        for acumulada, otra in zip(union, otras):
            acumulada.x_min = min(acumulada.x_min, otra.x_min)
            acumulada.x_max = max(acumulada.x_max, otra.x_max)
            acumulada.support += otra.support
            if not acumulada.header:
                acumulada.header = otra.header
    return Layout(columns=tuple(union))


def celdas(line: Line, layout: Layout) -> dict[int, str]:
    """Reparte las palabras del renglon entre las columnas del layout."""
    partes: dict[int, list[tuple[float, str]]] = {}
    for word in line.words:
        indice = layout.indice_de(word)
        if indice is not None:
            partes.setdefault(indice, []).append((word.x0, word.text))
    return {i: " ".join(t for _, t in sorted(trozos))
            for i, trozos in partes.items()}


def renglones_de_tabla(page: Page, layout: Layout) -> list[dict[int, str]]:
    """Los renglones de la zona de tabla de una pagina, ya en celdas."""
    lines = group(page.words)
    region = find_table_region(lines)
    if region is None:
        return []
    return [celdas(ln, layout) for ln in lines_within(lines, region)]


class Parser(Protocol):
    """Lo unico que comparten todos los parsers: Document entra, datos salen."""

    def parse(self, document: Document) -> object:
        ...
