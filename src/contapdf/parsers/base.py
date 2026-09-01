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
from contapdf.layout.columns import amount_columns, detect, is_amount
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
    elif s.endswith("-"):
        # Signo al final: asi imprime un banco la reversa de un cargo
        # ('287,000.00-'), y el saldo corrido confirma que es negativo.
        negativo = True
        s = s[:-1]
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
    # Deja que una columna alineada a la derecha reciba texto. Hace falta
    # en el auxiliar, donde el numero de movimiento vive en una; en la
    # balanza sobra y le meteria los encabezados a las celdas de monto.
    texto_en_montos: bool = False

    @property
    def headers(self) -> tuple[str, ...]:
        return tuple(c.header for c in self.columns)

    @property
    def montos(self) -> tuple[ColumnSpec, ...]:
        return tuple(c for c in self.columns if c.align == "right")

    @property
    def textos(self) -> tuple[ColumnSpec, ...]:
        return tuple(c for c in self.columns if c.align != "right")

    def indice_de(self, word: Word, *, max_distance: float = 40.0) -> int | None:
        """La columna de esta palabra.

        Los montos se ubican por su BORDE DERECHO contra el de la columna,
        no por su centro: es lo que los mantiene en su sitio aunque encima
        pase un texto que se traslapa. El resto va por cercania del centro.
        """
        if is_amount(word.text) and self.montos:
            return self._monto_mas_cercano(word)

        centro = (word.x0 + word.x1) / 2
        candidatas = self.textos or self.columns
        # La contencion le gana a la cercania solo cuando el formato lo
        # pide: si ninguna columna de texto contiene la palabra, se
        # consideran todas y gana la mas angosta.
        if self.texto_en_montos and not any(
                c.x_min - 6 <= centro <= c.x_max + 6 for c in candidatas):
            contienen = [c for c in self.columns
                         if c.x_min - 6 <= centro <= c.x_max + 6]
            if contienen:
                return min(contienen, key=lambda c: c.x_max - c.x_min).index

        elegida, menor = None, math.inf
        for col in candidatas:
            if col.x_min - 6 <= centro <= col.x_max + 6:
                distancia = 0.0
            else:
                distancia = min(abs(centro - col.x_min), abs(centro - col.x_max))
            if distancia < menor:
                elegida, menor = col, distancia
        return elegida.index if elegida is not None and menor < max_distance else None

    def _monto_mas_cercano(self, word: Word) -> int | None:
        """El monto va a la columna cuyo borde derecho tiene mas cerca.

        La tolerancia es la mitad de la separacion entre columnas: alcanza
        para una fila de totales impresa con otra fuente (Business Pro la
        corre hasta 24pt) sin llegar nunca a la columna vecina.
        """
        bordes = sorted(c.x_max for c in self.montos)
        if len(bordes) > 1:
            limite = min(b - a for a, b in zip(bordes, bordes[1:])) / 2
        else:
            limite = 40.0
        elegida, menor = None, math.inf
        for col in self.montos:
            distancia = abs(word.x1 - col.x_max)
            if distancia < menor:
                elegida, menor = col, distancia
        return elegida.index if elegida is not None and menor < limite else None


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
        dentro = lines_within(lines, region)
        columnas = assign(lines, region,
                          _texto_y_montos(dentro, tol=tol, min_support=min_support))
        if columnas:
            detectadas.append(columnas)

    if not detectadas:
        return None

    # La base es la deteccion con MAS columnas de la muestra: fundir dos
    # columnas pierde informacion, pero ninguna pagina inventa una columna
    # que no exista, asi que la mas detallada es la mas fiel.
    base = max(detectadas, key=len)
    union = [replace(c) for c in base]
    for otras in detectadas:
        if otras is base:
            continue
        if len(otras) != len(union):
            _LOG.info("la muestra no coincide: %s columnas contra %s; "
                      "me quedo con la mas detallada", len(otras), len(union))
            continue
        for acumulada, otra in zip(union, otras):
            acumulada.x_min = min(acumulada.x_min, otra.x_min)
            acumulada.x_max = max(acumulada.x_max, otra.x_max)
            acumulada.support += otra.support
            if not acumulada.header:
                acumulada.header = otra.header
    return Layout(columns=tuple(union))


def _texto_y_montos(lines: Sequence[Line], *, tol: float,
                    min_support: int) -> list[ColumnSpec]:
    """Columnas de texto de detect() + columnas de monto sin fundir.

    detect() funde por traslape, que es lo correcto cuando una columna de
    texto ancha se parte en varios anclajes. Pero cuando la descripcion se
    imprime ENCIMA de los importes, ese mismo merge se traga las columnas
    numericas. Tomarlas aparte las conserva en los dos casos.
    """
    montos = amount_columns(lines, tol=tol, min_support=min_support)
    bordes = {round(c.x_max, 1) for c in montos}
    textos = [c for c in detect(lines, tol=tol, min_support=min_support)
              if round(c.x_max, 1) not in bordes]

    columnas = sorted(textos + montos, key=lambda c: c.x_min)
    for i, col in enumerate(columnas):
        col.index = i
    return columnas


def celdas(line: Line, layout: Layout) -> dict[int, str]:
    """Reparte las palabras del renglon entre las columnas del layout.

    Una columna alineada a la derecha lleva UN valor por renglon, asi que
    si le tocan varias palabras se queda con la que mejor cierra contra su
    borde. Es lo que descarta el texto que se imprime encima: un '15%' de
    la descripcion tambien parece numero, pero no termina donde termina la
    columna.
    """
    partes: dict[int, list[Word]] = {}
    for word in line.words:
        indice = layout.indice_de(word)
        if indice is not None:
            partes.setdefault(indice, []).append(word)

    montos = {c.index: c for c in layout.montos}
    salida: dict[int, str] = {}
    for indice, palabras in partes.items():
        columna = montos.get(indice)
        if columna is not None and len(palabras) > 1:
            mejor = min(palabras, key=lambda w: abs(w.x1 - columna.x_max))
            salida[indice] = mejor.text
        else:
            salida[indice] = " ".join(w.text for w in sorted(palabras,
                                                             key=lambda w: w.x0))
    return salida


def lineas_de_tabla(page: Page) -> list[Line]:
    """Los renglones que caen dentro de la zona de tabla de la pagina."""
    lines = group(page.words)
    region = find_table_region(lines)
    if region is None:
        return []
    return lines_within(lines, region)


def renglones_de_tabla(page: Page, layout: Layout) -> list[dict[int, str]]:
    """Los renglones de la zona de tabla de una pagina, ya en celdas."""
    return [celdas(ln, layout) for ln in lineas_de_tabla(page)]


class Parser(Protocol):
    """Lo unico que comparten todos los parsers: Document entra, datos salen."""

    def parse(self, document: Document) -> object:
        ...
