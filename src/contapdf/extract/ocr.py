"""Extraccion por OCR: rasterizar la pagina y leerla con Tesseract.

Existe por DOS motivos, no uno:

  a) PDFs sin capa de texto (escaneos), el caso clasico;
  b) paginas con capa de texto MUTILADA -- caracteres que no estan en el
     archivo. Ninguna estrategia de extraccion los recupera, pero la
     pagina impresa si los muestra.

Produce el mismo IR que pdf_text y pdf_chars, con run=0, asi que layout/
y parsers/ no distinguen de donde vino el texto.

Tesseract y no OCR neuronal: el servidor es un i5-3470 sin AVX2 y las
librerias modernas lo dan por hecho. Cuesta 2-5 s por pagina en ese CPU,
asi que el OCR va en carril aparte; el reintento del caso (b) es de
paginas sueltas y por eso si es barato.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path

import pypdfium2 as pdfium

from contapdf.ir import Document, Page, Word

_LOG = logging.getLogger(__name__)
_DPI = 300
_IDIOMA = "spa"
_BINARIO = "tesseract"
_PSM = "6"  # un bloque uniforme de texto: es lo que es una tabla contable
_CONFIANZA = 40.0
_COLUMNAS_TSV = 12


class TesseractAusente(RuntimeError):
    """No hay binario de Tesseract con el que leer la pagina."""


def hay_tesseract(*, binario: str = _BINARIO) -> bool:
    """Si se puede hacer OCR. Nunca lanza: quien llama decide que hacer."""
    return shutil.which(binario) is not None


def _tsv_a_palabras(tsv: str, numero: int, escala: float,
                    confianza_minima: float) -> list[Word]:
    """Convierte la salida TSV de Tesseract al IR.

    Las cajas vienen en pixeles del render; el IR habla en puntos de PDF.
    Sin la conversion, layout/ estaria detectando columnas en otro sistema
    de coordenadas.
    """
    palabras: list[Word] = []
    for linea in tsv.splitlines()[1:]:
        campos = linea.split("\t")
        if len(campos) < _COLUMNAS_TSV:
            continue
        texto = campos[11].strip()
        if not texto:
            continue
        try:
            izquierda, arriba = float(campos[6]), float(campos[7])
            ancho, alto = float(campos[8]), float(campos[9])
            confianza = float(campos[10])
        except ValueError:
            continue
        if confianza < confianza_minima:
            continue
        palabras.append(Word(
            text=texto,
            x0=izquierda / escala,
            x1=(izquierda + ancho) / escala,
            top=arriba / escala,
            bottom=(arriba + alto) / escala,
            size=alto / escala,
            bold=False,
            page=numero,
            run=0,
        ))
    return palabras


def leer_pagina(path: str | Path, numero: int, *, dpi: int = _DPI,
                idioma: str = _IDIOMA, binario: str = _BINARIO,
                psm: str = _PSM, confianza_minima: float = _CONFIANZA) -> Page:
    """OCR de UNA pagina. Es la unidad del reintento del caso (b)."""
    if not hay_tesseract(binario=binario):
        raise TesseractAusente(
            f"no se encontro el binario de tesseract ({binario!r}); "
            "sin el no se puede leer una pagina por OCR")

    escala = dpi / 72
    documento = pdfium.PdfDocument(str(path))
    try:
        pagina = documento[numero - 1]
        imagen = pagina.render(scale=escala).to_pil()
        ancho_pt, alto_pt = pagina.get_width(), pagina.get_height()
    finally:
        documento.close()

    with tempfile.TemporaryDirectory() as carpeta:
        destino = Path(carpeta) / f"p{numero}.png"
        imagen.save(destino)
        proceso = subprocess.run(
            [binario, str(destino), "stdout", "-l", idioma, "--psm", psm, "tsv"],
            capture_output=True, text=True, check=False)
    if proceso.returncode != 0:
        raise TesseractAusente(
            f"tesseract fallo en la pagina {numero}: "
            f"{proceso.stderr.strip()[:200]}")

    palabras = _tsv_a_palabras(proceso.stdout, numero, escala, confianza_minima)
    palabras.sort(key=lambda w: (w.top, w.x0))
    return Page(number=numero, width=float(ancho_pt), height=float(alto_pt),
                words=tuple(palabras), ruling_lines=0)


def _iter_pages(path: Path, page_numbers: tuple[int, ...] | None, dpi: int,
                idioma: str, binario: str, psm: str,
                confianza_minima: float) -> Iterator[Page]:
    documento = pdfium.PdfDocument(str(path))
    try:
        total = len(documento)
    finally:
        documento.close()
    for numero in (page_numbers or range(1, total + 1)):
        if not 1 <= numero <= total:
            continue
        yield leer_pagina(path, numero, dpi=dpi, idioma=idioma, binario=binario,
                          psm=psm, confianza_minima=confianza_minima)


def extract(path: str | Path, *, page_numbers: Sequence[int] | None = None,
            dpi: int = _DPI, idioma: str = _IDIOMA, binario: str = _BINARIO,
            psm: str = _PSM, confianza_minima: float = _CONFIANZA) -> Document:
    """Abre un PDF y entrega sus paginas leidas por OCR, una por una."""
    source = Path(path)
    if not hay_tesseract(binario=binario):
        raise TesseractAusente(
            f"no se encontro el binario de tesseract ({binario!r}); "
            "instalalo o procesa el documento por texto nativo")

    objetivo = tuple(page_numbers) if page_numbers is not None else None
    documento = pdfium.PdfDocument(str(source))
    try:
        page_count = len(documento)
    finally:
        documento.close()

    return Document(
        source=str(source), page_count=page_count,
        open_pages=lambda: _iter_pages(source, objetivo, dpi, idioma, binario,
                                       psm, confianza_minima))
