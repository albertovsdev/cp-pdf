"""Deteccion de columnas por alineacion.

Los montos van alineados a la derecha: lo que comparten es x1. El texto va
alineado a la izquierda: comparte x0. Agrupar todo por x0 produce decenas de
columnas falsas, una por cada largo de monto.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from contapdf.ir import ColumnSpec, Line, Word

_RE_NUMERIC = re.compile(r"^[\d.,\-$()%/:]+$")
# Base de 3 digitos o mas y cualquier numero de segmentos: hay
# catalogos reales con 0400-0000-0000-0000 y 1110-000-000. La regla
# estrecha de scripts/dump_layout.py existe por PRIVACIDAD (con base
# de 4 hacia match con folios y fechas, y se filtraban sin enmascarar)
# y ahi se queda. Aqui no hay dato que proteger: una cuenta tomada
# por monto se agrupa por x1 y degrada la deteccion en silencio.
_RE_CUENTA = re.compile(r"^\d{3,}(-\d+)*$")
_RE_FECHA = re.compile(r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$")
# Forma que un monto y una cuenta con puntos comparten exactamente:
# '101.01' y '999.99' son indistinguibles mirando el texto. Solo la
# POSICION las separa, asi que la decide quien sabe en que columna cae.
_RE_AMBIGUA = re.compile(r"^\d{1,6}(\.\d{1,6})+$")
# Minimo de renglones que tienen que abrir en la misma x para creer que
# ahi hay una columna de cuenta y no una coincidencia.
_MIN_ZONA = 5


def is_amount(text: str, *, en_columna_de_cuenta: bool = False) -> bool:
    """True solo para MONTOS, que son los que van alineados a la derecha.

    Las cuentas contables (100-01) y las fechas (01-01-2025) tambien son
    "numericas", pero van alineadas a la izquierda: su borde derecho varia
    con el largo y tratarlas como montos impide detectar su columna.

    Hay catalogos que separan con punto ('101.01.01'), y esa forma es
    IDENTICA a la de un importe. Ninguna regla sobre el texto puede
    distinguirlas; lo unico que las separa es donde caen. Por eso quien
    sabe que la palabra esta en la columna de cuenta lo dice con
    'en_columna_de_cuenta', y ahi la forma ambigua se lee como texto.
    El parametro es aditivo: sin el, la funcion se comporta igual que
    siempre.
    """
    s = text.strip()
    if not s or not any(c.isdigit() for c in s):
        return False
    if _RE_CUENTA.match(s) or _RE_FECHA.match(s):
        return False
    if en_columna_de_cuenta and _RE_AMBIGUA.match(s):
        return False
    return bool(_RE_NUMERIC.match(s))


def zona_de_cuenta(lines: Sequence[Line], tol: float = 3.0) -> tuple[float, float] | None:
    """El tramo de x donde abren los renglones, o None si no hay tal cosa.

    Es la columna que arranca cada fila. Se calcula sin mirar el contenido
    -- solo la posicion de la primera palabra de cada renglon -- porque el
    contenido es justo lo ambiguo.
    """
    primeras = [ln.words[0] for ln in lines if ln.words]
    if len(primeras) < _MIN_ZONA:
        return None
    grupos = _cluster([w.x0 for w in primeras], tol)
    mayor = max(grupos, key=len)
    if len(mayor) < _MIN_ZONA:
        return None
    miembros = [w for w in primeras if mayor[0] - tol <= w.x0 <= mayor[-1] + tol]
    return min(w.x0 for w in miembros), max(w.x1 for w in miembros)


@dataclass(frozen=True)
class _Candidate:
    align: str
    anchor: float  # x1 si es 'right', x0 si es 'left'
    x_min: float
    x_max: float
    support: int


def _cluster(values: Sequence[float], tol: float) -> list[list[float]]:
    """Agrupa valores cercanos cortando cuando el hueco supera la tolerancia.

    Alcanza con esto: las columnas de un PDF estan bien separadas entre si.
    """
    if not values:
        return []
    ordered = sorted(values)
    groups: list[list[float]] = [[ordered[0]]]
    for v in ordered[1:]:
        if v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return groups


def _words_of(lines: Iterable[Line]) -> list[Word]:
    return [w for ln in lines for w in ln.words]


def _candidates(words: Sequence[Word], tol: float, min_support: int,
                zona: tuple[float, float] | None = None) -> list[_Candidate]:
    def es_monto(word: Word) -> bool:
        dentro = zona is not None and zona[0] - tol <= word.x0 <= zona[1] + tol
        return is_amount(word.text, en_columna_de_cuenta=dentro)

    montos = [w for w in words if es_monto(w)]
    textos = [w for w in words if not es_monto(w)]

    found: list[_Candidate] = []
    for grupo, align, edge in ((montos, "right", "x1"), (textos, "left", "x0")):
        for cluster in _cluster([getattr(w, edge) for w in grupo], tol):
            if len(cluster) < min_support:
                continue
            anchor = sum(cluster) / len(cluster)
            miembros = [w for w in grupo
                        if abs(getattr(w, edge) - anchor) <= tol * 2]
            if not miembros:
                continue
            found.append(_Candidate(
                align=align,
                anchor=anchor,
                x_min=min(w.x0 for w in miembros),
                x_max=max(w.x1 for w in miembros),
                support=len(cluster),
            ))

    # Una columna real tiene una palabra por renglon, asi que su soporte se
    # parece al de las demas. Los textos sueltos de encabezado o metadatos
    # generan columnas con soporte muy bajo. El umbral se compara contra la
    # mediana, no contra un numero fijo, para que se adapte igual a un
    # documento de 5 renglones que a uno de 500.
    if found:
        soportes = sorted(c.support for c in found)
        mediana = soportes[len(soportes) // 2]
        piso = max(min_support, mediana * 0.25)
        found = [c for c in found if c.support >= piso]

    return sorted(found, key=lambda c: c.x_min)


def _merge_overlapping(cands: Sequence[_Candidate]) -> list[ColumnSpec]:
    """Funde columnas cuyas extensiones horizontales se traslapan.

    Pasa cuando una columna de texto ancha (el nombre de cuenta) genera
    varios anclajes por la indentacion jerarquica, o cuando parte de sus
    valores se clasifico con la otra alineacion. Si se traslapan, es una.
    """
    merged: list[ColumnSpec] = []
    for c in cands:
        if merged and c.x_min < merged[-1].x_max:
            prev = merged[-1]
            if c.support > prev.support:
                prev.align = c.align
            prev.x_min = min(prev.x_min, c.x_min)
            prev.x_max = max(prev.x_max, c.x_max)
            prev.support += c.support
        else:
            merged.append(ColumnSpec(index=0, align=c.align, x_min=c.x_min,
                                     x_max=c.x_max, support=c.support))
    for i, col in enumerate(merged):
        col.index = i
    return merged


def detect(lines: Sequence[Line], *, tol: float = 3.0,
           min_support: int = 3) -> list[ColumnSpec]:
    """Detecta las columnas de los renglones dados, de izquierda a derecha.

    Conviene pasarle solo los renglones de la tabla (ver layout.region): con
    la pagina completa, los metadatos y el sello digital corren los clusters.
    """
    return _merge_overlapping(_candidates(_words_of(lines), tol, min_support,
                                          zona_de_cuenta(lines, tol)))


def amount_columns(lines: Sequence[Line], *, tol: float = 3.0,
                   min_support: int = 3) -> list[ColumnSpec]:
    """Las columnas de monto solas, SIN fundir con las de texto.

    detect() funde columnas que se traslapan, y hay documentos donde la
    descripcion se imprime encima de los importes: ahi el merge se traga
    las columnas numericas. Estas se sostienen igual, porque el borde
    derecho de un monto no depende de que haya texto encima.
    """
    columnas = [
        ColumnSpec(index=0, align="right", x_min=c.x_min, x_max=c.x_max,
                   support=c.support)
        for c in _candidates(_words_of(lines), tol, min_support,
                             zona_de_cuenta(lines, tol))
        if c.align == "right"
    ]
    for i, col in enumerate(columnas):
        col.index = i
    return columnas


def amount_anchors(lines: Sequence[Line], *, tol: float = 3.0,
                   min_support: int = 3) -> list[float]:
    """Los x1 donde se apilan los montos, sin fundir columnas.

    Es la firma horizontal de la tabla: sirve para reconocer que renglones
    son parte de ella (ver layout.region). Va sin fundir porque ahi importa
    el borde exacto, no la extension de la columna.
    """
    return [c.anchor for c in _candidates(_words_of(lines), tol, min_support,
                                          zona_de_cuenta(lines, tol))
            if c.align == "right"]
