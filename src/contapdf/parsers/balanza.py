"""Parser de balanza de comprobacion."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, replace
from decimal import Decimal

from contapdf.ir import Document, Page
from contapdf.parsers.base import (
    Layout,
    detectar_layout,
    es_cuenta,
    normalizar,
    parse_monto,
    renglones_de_tabla,
)

_LOG = logging.getLogger(__name__)

# Campo canonico -> encabezados que lo nombran, ya normalizados. El orden
# importa: 'cuenta' reclama la columna del numero antes de que 'nombre'
# reclame la del texto, que en estas balanzas se llama igual.
_MAPA = (
    ("cuenta", ("no cuenta", "num cuenta", "numero de cuenta", "cuenta contable")),
    ("naturaleza", ("naturaleza", "nat")),
    ("nombre", ("cuenta", "nombre", "nombre de la cuenta", "descripcion")),
    ("saldo_ini_deudor", ("saldo inicial deudor", "saldo anterior deudor")),
    ("saldo_ini_acreedor", ("saldo inicial acreedor", "saldo anterior acreedor")),
    ("debe", ("debe", "cargos")),
    ("haber", ("haber", "abonos")),
    ("saldo_fin_deudor", ("saldo final deudor", "saldo actual deudor")),
    ("saldo_fin_acreedor", ("saldo final acreedor", "saldo actual acreedor")),
)
_MONTOS = ("saldo_ini_deudor", "saldo_ini_acreedor", "debe", "haber",
           "saldo_fin_deudor", "saldo_fin_acreedor")


class LayoutDesconocido(ValueError):
    """El layout no trae las columnas que una balanza necesita."""


@dataclass(frozen=True)
class FilaBalanza:
    """Un renglon de la balanza. 'nivel' y 'cuenta_padre' son derivados."""

    cuenta: str
    nivel: int
    cuenta_padre: str
    naturaleza: str
    nombre: str
    saldo_ini_deudor: Decimal
    saldo_ini_acreedor: Decimal
    debe: Decimal
    haber: Decimal
    saldo_fin_deudor: Decimal
    saldo_fin_acreedor: Decimal


@dataclass(frozen=True)
class Totales:
    """La fila 'Totales' que el PDF trae al final."""

    debe: Decimal
    haber: Decimal


@dataclass(frozen=True)
class Balanza:
    filas: tuple[FilaBalanza, ...]
    totales: Totales | None

    def __iter__(self) -> Iterator[FilaBalanza]:
        return iter(self.filas)


def mapear_columnas(layout: Layout) -> dict[str, int]:
    """Asocia cada campo canonico con el indice de su columna.

    Por encabezado y no por posicion: un PDF con una columna de mas correria
    todos los indices y el mapeo saldria mal sin que nada avisara.
    """
    disponibles = {c.index: normalizar(c.header) for c in layout.columns}
    mapa: dict[str, int] = {}
    for campo, nombres in _MAPA:
        for indice, header in sorted(disponibles.items()):
            if header in nombres:
                mapa[campo] = indice
                del disponibles[indice]
                break

    faltantes = [campo for campo, _ in _MAPA if campo not in mapa]
    if faltantes:
        raise LayoutDesconocido(
            "el layout no parece una balanza; faltan las columnas: "
            + ", ".join(faltantes)
        )
    return mapa


def _derivar(cuenta: str) -> tuple[int, str]:
    partes = cuenta.split("-")
    return len(partes), "-".join(partes[:-1]) if len(partes) > 1 else ""


@dataclass(frozen=True)
class BalanzaParser:
    """Convierte un Document de balanza en filas validables.

    'paginas_muestra' acota cuantas paginas se guardan en memoria para
    deducir el layout antes de emitir la primera fila. El documento se
    recorre UNA sola vez: reabrirlo cuesta un parseo completo del PDF.
    """

    paginas_muestra: int = 3

    def parse(self, document: Document, *, layout: Layout | None = None) -> Balanza:
        filas: list[FilaBalanza] = []
        totales: list[Totales] = []
        mapa = mapear_columnas(layout) if layout is not None else None
        buffer: list[Page] = []

        for page in document.open_pages():
            if layout is None:
                buffer.append(page)
                if len(buffer) < self.paginas_muestra:
                    continue
                layout = detectar_layout(buffer)
                if layout is None:
                    # Ninguna de las paginas juntadas trae tabla (portadas,
                    # anexos). Se suelta la mas vieja para no crecer sin fin.
                    buffer.pop(0)
                    continue
                mapa = mapear_columnas(layout)
                for pendiente in buffer:
                    self._procesar(pendiente, layout, mapa, filas, totales)
                buffer.clear()
            else:
                self._procesar(page, layout, mapa, filas, totales)

        if buffer:
            layout = detectar_layout(buffer)
            if layout is not None:
                mapa = mapear_columnas(layout)
                for pendiente in buffer:
                    self._procesar(pendiente, layout, mapa, filas, totales)

        if len(totales) > 1:
            _LOG.warning("el documento trae %s filas de totales; uso la ultima",
                         len(totales))
        return Balanza(filas=tuple(filas), totales=totales[-1] if totales else None)

    def _procesar(self, page: Page, layout: Layout, mapa: dict[str, int],
                  filas: list[FilaBalanza], totales: list[Totales]) -> None:
        for celdas in renglones_de_tabla(page, layout):
            cuenta = celdas.get(mapa["cuenta"], "").strip()
            nombre = celdas.get(mapa["nombre"], "").strip()

            if es_cuenta(cuenta):
                filas.append(self._fila(celdas, mapa, cuenta, nombre))
            elif cuenta:
                continue  # el encabezado se repite en cada pagina
            elif normalizar(nombre).startswith("totales"):
                totales.append(Totales(debe=parse_monto(celdas.get(mapa["debe"], "")),
                                       haber=parse_monto(celdas.get(mapa["haber"], ""))))
            elif nombre and filas:
                # Nombre de cuenta partido en dos renglones: el segundo no
                # trae numero de cuenta ni importes.
                filas[-1] = replace(filas[-1],
                                    nombre=f"{filas[-1].nombre} {nombre}".strip())

    def _fila(self, celdas: dict[int, str], mapa: dict[str, int],
              cuenta: str, nombre: str) -> FilaBalanza:
        nivel, padre = _derivar(cuenta)
        montos = {campo: parse_monto(celdas.get(mapa[campo], ""))
                  for campo in _MONTOS}
        return FilaBalanza(
            cuenta=cuenta,
            nivel=nivel,
            cuenta_padre=padre,
            naturaleza=celdas.get(mapa["naturaleza"], "").strip(),
            nombre=nombre,
            **montos,
        )
