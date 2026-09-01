"""Eleccion de estrategia de extraccion.

pdf_text es el default y sirve para casi todo. pdf_chars cuesta mas y solo
hace falta cuando el documento imprime texto encimado. El OCR cuesta ~21 s
por documento y solo se justifica cuando el archivo es ilegible de raiz.
La eleccion se decide con una MUESTRA y se puede imponer: es lo que la
plantilla guarda, para no volver a detectarla en cada corrida.

Tres senales, cada una con su umbral medido:

| Senal | Que delata | Estrategia |
|---|---|---|
| tokens contaminados | glifos de dos corridas en una palabra | `pdf_chars` |
| palabras traslapadas | una columna impresa encima de otra | `pdf_chars` |
| fraccion en CID | el PDF no trae el mapa que traduce glifos | `ocr` |

La decision viaja con su MOTIVO y con las tres senales medidas: elegir OCR
cuesta veinte veces mas que no elegirlo, y esa decision no puede quedarse
en un log.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from contapdf.extract import ocr, pdf_chars, pdf_text
from contapdf.extract.dedup import deduplicar_pagina, multiplicador
from contapdf.extract.tokens import separar_fecha_pegada
from contapdf.ir import Document, Page, Word

_LOG = logging.getLogger(__name__)
_RE_MONTO = re.compile(r"-?\d{1,3}(,\d{3})*\.\d{2}")
_RE_MONTO_SOLO = re.compile(r"^-?\d{1,3}(,\d{3})*\.\d{2}$")
_MARCA_CID = "(cid:"
# Medido sobre los 27 fixtures reales: el documento ilegible da 98.8% de su
# muestra en CID y el siguiente da 0.55%. No hay nada en medio. El umbral se
# pone en la mitad a proposito: lo que justifica releer TODO por OCR es que
# el documento sea ilegible, no que traiga un sello digital en CID. Eso
# ultimo lo cubre reintento.reintentar_cid, pagina por pagina.
_UMBRAL_CID = 0.5


@dataclass(frozen=True)
class Decision:
    """Que estrategia se eligio, por que, y con que numeros."""

    estrategia: str
    motivo: str
    senales: dict = field(default_factory=dict)


def fraccion_cid(words: Sequence[Word]) -> float:
    """Que parte de las palabras vino en CID sin mapa ToUnicode.

    Fraccion y no conteo: un documento de 900 paginas con veinte tokens en
    CID esta sano, y uno de cuatro paginas con doscientos no.
    """
    if not words:
        return 0.0
    return sum(1 for w in words if _MARCA_CID in w.text) / len(words)


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


def _medir(path: str | Path, paginas_muestra: int) -> dict:
    """Las tres senales sobre la muestra, en una sola pasada."""
    documento = pdf_text.extract(path)
    paginas = documento.open_pages()
    contaminados = traslapadas = palabras = en_cid = 0
    try:
        for numero, page in enumerate(paginas, start=1):
            contaminados += len(tokens_contaminados(page.words))
            traslapadas += palabras_traslapadas(page.words)
            palabras += len(page.words)
            en_cid += sum(1 for w in page.words if _MARCA_CID in w.text)
            if numero >= paginas_muestra:
                break
    finally:
        paginas.close()
    return {"tokens_contaminados": contaminados,
            "palabras_traslapadas": traslapadas,
            "palabras": palabras,
            "fraccion_traslape": traslapadas / palabras if palabras else 0.0,
            "fraccion_cid": en_cid / palabras if palabras else 0.0}


def decidir(path: str | Path, *, paginas_muestra: int = 2,
            umbral_traslape: float = 0.02,
            umbral_cid: float = _UMBRAL_CID,
            binario: str = "tesseract") -> Decision:
    """Que estrategia usar para este archivo, con el porque y las cifras.

    El CID se evalua PRIMERO: cuando el archivo no trae el mapa de glifos,
    ni pdf_text ni pdf_chars lo salvan, porque el problema no es como se lee
    sino que las letras no estan en el archivo.
    """
    senales = _medir(path, paginas_muestra)

    if senales["fraccion_cid"] >= umbral_cid:
        porcentaje = senales["fraccion_cid"] * 100
        if not ocr.hay_tesseract(binario=binario):
            return Decision(
                estrategia="pdf_text", senales=senales,
                motivo=(f"{porcentaje:.1f}% de la muestra viene en CID sin mapa "
                        f"ToUnicode y pedia OCR, pero tesseract no esta "
                        f"instalado ({binario!r}): el documento va a salir "
                        "ilegible"))
        return Decision(
            estrategia="ocr", senales=senales,
            motivo=(f"{porcentaje:.1f}% de la muestra viene en CID sin mapa "
                    "ToUnicode: el PDF no trae la tabla que traduce glifos a "
                    "letras, asi que se relee por OCR"))

    if senales["tokens_contaminados"]:
        return Decision(
            estrategia="pdf_chars", senales=senales,
            motivo=(f"{senales['tokens_contaminados']} token(s) contaminado(s): "
                    "una sola palabra mezcla glifos de dos corridas distintas"))

    if senales["fraccion_traslape"] > umbral_traslape:
        return Decision(
            estrategia="pdf_chars", senales=senales,
            motivo=(f"{senales['fraccion_traslape']:.3f} de las palabras se "
                    "traslapan: hay texto encimado"))

    return Decision(estrategia="pdf_text", senales=senales,
                    motivo="texto nativo limpio en la muestra")


def esta_contaminada(path: str | Path, *, paginas_muestra: int = 2,
                     umbral_traslape: float = 0.02) -> bool:
    """True si conviene extraer por corridas en vez de por palabras.

    Medido sobre seis documentos reales: Business Pro da 27 tokens
    contaminados y los otros cinco dan cero. Basta con que aparezca uno:
    cada token contaminado es un renglon que se leeria mal.
    """
    return decidir(path, paginas_muestra=paginas_muestra,
                   umbral_traslape=umbral_traslape,
                   umbral_cid=2.0).estrategia == "pdf_chars"


def extraer_con_motivo(path: str | Path, *, estrategia: str | None = None,
                       page_numbers: Sequence[int] | None = None,
                       paginas_muestra: int = 2,
                       umbral_cid: float = _UMBRAL_CID,
                       ) -> tuple[Document, Decision]:
    """Devuelve (documento, decision) con el porque de la estrategia."""
    if estrategia is None:
        decision = decidir(path, paginas_muestra=paginas_muestra,
                           umbral_cid=umbral_cid)
        _LOG.info("estrategia para %s: %s (%s)", path, decision.estrategia,
                  decision.motivo)
    else:
        decision = Decision(estrategia=estrategia,
                            motivo="impuesta por quien llama o por la plantilla")

    if decision.estrategia == "pdf_chars":
        documento = pdf_chars.extract(path, page_numbers=page_numbers)
    elif decision.estrategia == "pdf_text":
        documento = pdf_text.extract(path, page_numbers=page_numbers)
    elif decision.estrategia == "ocr":
        documento = ocr.extract(path, page_numbers=page_numbers)
    else:
        raise ValueError(f"estrategia desconocida: {decision.estrategia!r}")
    return _normalizado(documento), decision


def extraer(path: str | Path, *, estrategia: str | None = None,
            page_numbers: Sequence[int] | None = None,
            paginas_muestra: int = 2) -> tuple[Document, str]:
    """Devuelve (documento, nombre de la estrategia usada).

    La firma de siempre. Quien necesite el porque usa extraer_con_motivo.
    """
    documento, decision = extraer_con_motivo(
        path, estrategia=estrategia, page_numbers=page_numbers,
        paginas_muestra=paginas_muestra)
    return documento, decision.estrategia


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
