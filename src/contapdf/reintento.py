"""Reintento por pagina, disparado por la aritmetica.

Hay paginas cuyo texto nativo esta mutilado: los caracteres no estan en el
archivo y ninguna estrategia de extraccion los recupera. La pagina impresa
si los muestra, asi que la salida es rasterizarla y pasarla por OCR.

Lo que decide QUE paginas se reintentan no es una lista fija sino la
aritmetica: un dato que no se pudo leer, o un saldo corrido que se rompe
sin explicacion. Eso convierte a la validacion en parte del pipeline de
extraccion y no solo en su control de calidad.

El reintento es por PAGINA. Rehacer el documento entero por OCR cuesta
horas en el servidor de destino; rehacer las paginas que fallaron cuesta
segundos.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import re

from contapdf.extract import ocr
from contapdf.extract.strategy import extraer
from contapdf.ir import Document, Page
from contapdf.parsers.auxiliar import Auxiliar, AuxiliarParser, FilaAuxiliar
from contapdf.parsers.base import Layout

_LOG = logging.getLogger(__name__)
_TOLERANCIA = Decimal("0.01")
# Un monto bien formado o nada. El OCR lee '1,025,814.4' de una celda que
# la propia pagina imprimio truncada: aceptarlo meteria un numero
# equivocado, que es peor que dejar la celda vacia.
_RE_MONTO_OCR = re.compile(r"^-?\d{1,3}(,\d{3})*\.\d{2}$")
_RE_PARECE_MONTO = re.compile(r"^-?[\d,]+\.\d{1,3}$")
_BANDA = 4.0   # pt de holgura vertical: el OCR no clava el renglon
_BORDE = 18.0  # pt de holgura contra el borde derecho de la columna


@dataclass(frozen=True)
class PaginaSospechosa:
    pagina: int
    motivo: str


@dataclass(frozen=True)
class Reintento:
    """Que se reintento, que se recupero y por que no se pudo mas."""

    paginas: tuple[int, ...]
    recuperados: int
    ilegibles: int
    # Celdas donde el OCR si leyo algo, pero mal formado: la pagina las
    # imprime truncadas. Se cuentan aparte porque no son un fallo del OCR
    # sino del documento.
    truncados: int
    disponible: bool
    motivo: str


def paginas_a_reintentar(auxiliar: Auxiliar) -> list[PaginaSospechosa]:
    """Las paginas que la aritmetica senala, no una lista fija.

    Dos senales: un dato que no se pudo leer, y un saldo que no encadena
    aunque todos sus numeros se hayan leido. La segunda es la que delata
    una pagina mutilada cuyos huecos ni siquiera se notaron.
    """
    movimientos = [f for f in auxiliar.filas if not f.es_subtotal]
    motivos: dict[int, str] = {}

    anterior: Decimal | None = None
    cuenta = ""
    for fila in movimientos:
        if fila.cuenta != cuenta:
            cuenta, anterior = fila.cuenta, fila.saldo_inicial_cuenta
        if fila.saldo is None:
            motivos.setdefault(fila.pagina, "dato ilegible en la capa de texto")
            anterior = None
            continue
        if anterior is not None:
            esperado = anterior + fila.debe - fila.haber
            if abs(esperado - fila.saldo) > _TOLERANCIA:
                motivos[fila.pagina] = "el saldo corrido se rompe sin explicacion"
        anterior = fila.saldo

    return [PaginaSospechosa(pagina=p, motivo=m)
            for p, m in sorted(motivos.items()) if p]


def _documento_de(page) -> Document:
    return Document(source=f"ocr:{page.number}", page_count=1,
                    open_pages=lambda: iter([page]))


def _movimientos_de(auxiliar: Auxiliar, pagina: int) -> list[FilaAuxiliar]:
    return [f for f in auxiliar.filas if f.pagina == pagina and not f.es_subtotal]


def reintentar_ilegibles(pdf: str | Path, auxiliar: Auxiliar, *,
                         binario: str = "tesseract", dpi: int = 300,
                         parser: AuxiliarParser | None = None) -> Reintento:
    """Relee por OCR las paginas que la aritmetica senalo.

    Devuelve cuantos datos recupero de verdad. Si no hay OCR disponible lo
    declara y no recupera nada: degradar limpio es preferible a fallar, y
    mentir sobre lo recuperado seria peor que las dos cosas.
    """
    sospechosas = tuple(s.pagina for s in paginas_a_reintentar(auxiliar))
    ilegibles = sum(1 for f in auxiliar.filas
                    if not f.es_subtotal and f.saldo is None)

    if not sospechosas:
        return Reintento(paginas=(), recuperados=0, ilegibles=ilegibles,
                         truncados=0,
                         disponible=ocr.hay_tesseract(binario=binario),
                         motivo="la aritmetica no senalo ninguna pagina")

    if not ocr.hay_tesseract(binario=binario):
        return Reintento(
            paginas=sospechosas, recuperados=0, ilegibles=ilegibles,
            truncados=0, disponible=False,
            motivo=(f"tesseract no esta instalado ({binario!r}): "
                    f"{len(sospechosas)} pagina(s) quedan sin reintentar"))

    columna = _columna_de_saldo(pdf, auxiliar)
    if columna is None:
        return Reintento(
            paginas=sospechosas, recuperados=0, ilegibles=ilegibles,
            truncados=0, disponible=True,
            motivo="no se pudo ubicar la columna de saldo para releerla")

    recuperados = 0
    truncados = 0
    fallidas = 0
    for numero in sospechosas:
        faltantes = [f for f in _movimientos_de(auxiliar, numero)
                     if f.saldo is None]
        if not faltantes:
            continue
        try:
            pagina = ocr.leer_pagina(pdf, numero, binario=binario, dpi=dpi)
        except Exception as exc:  # el OCR de una pagina no tumba el documento
            _LOG.warning("el reintento de la pagina %s fallo: %s", numero, exc)
            fallidas += 1
            continue
        for fila in faltantes:
            leido = _valor_en(pagina, fila.top, columna)
            if leido is None:
                continue
            if _RE_MONTO_OCR.match(leido):
                recuperados += 1
            else:
                truncados += 1

    motivo = (f"{len(sospechosas)} pagina(s) reintentadas por OCR; "
              f"{recuperados} de {ilegibles} datos recuperados")
    if truncados:
        motivo += (f"; {truncados} celdas venian truncadas en la propia "
                   "pagina y no se aceptaron")
    if fallidas:
        motivo += f"; {fallidas} pagina(s) no se pudieron rasterizar"
    return Reintento(paginas=sospechosas, recuperados=recuperados,
                     ilegibles=ilegibles, truncados=truncados, disponible=True,
                     motivo=motivo)


def _columna_de_saldo(pdf: str | Path, auxiliar: Auxiliar) -> tuple[float, float] | None:
    """El borde derecho de la columna de saldo, para volver a esa celda."""
    if auxiliar.mapeo is None or "saldo" not in auxiliar.mapeo.campos:
        return None
    documento, _ = extraer(pdf, page_numbers=[1, 2, 3])
    paginas = list(documento.open_pages())
    layout: Layout | None = AuxiliarParser()._layout(paginas)
    if layout is None:
        return None
    indice = auxiliar.mapeo.campos["saldo"]
    for columna in layout.columns:
        if columna.index == indice:
            return columna.x_min, columna.x_max
    return None


def _valor_en(pagina: Page, top: float,
              columna: tuple[float, float]) -> str | None:
    """Lo que el OCR leyo en esa celda, o None si no leyo nada usable.

    Se busca la palabra en la misma banda vertical y contra el mismo borde
    derecho. Si no hay ninguna, no se inventa: la celda sigue vacia.
    """
    x_min, x_max = columna
    for word in pagina.words:
        if abs(word.top - top) > _BANDA:
            continue
        if not (x_min - _BORDE <= word.x1 <= x_max + _BORDE):
            continue
        texto = word.text.strip()
        if _RE_PARECE_MONTO.match(texto) and any(c.isdigit() for c in texto):
            return texto
    return None
