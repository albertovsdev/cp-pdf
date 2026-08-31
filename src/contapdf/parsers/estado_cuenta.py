"""Parser de estado de cuenta bancario.

El documento mas desordenado de los siete. La pagina 1 es puro metadato --
encabezado, domicilio, sello digital, resumen de comisiones -- y la tabla
real empieza en DETALLE DE OPERACIONES: sin layout.region no hay de donde
leer. Un envio SPEI ocupa nueve renglones visuales, asi que la regla de
fila nueva es la misma del auxiliar: el renglon trae dia en la primera
columna, y todo lo que sigue sin dia continua al anterior.

ADVERTENCIA DE ALCANCE: hay UN solo banco en los fixtures. Lo que este
modulo sabe hacer es leer este formato, no "los estados de cuenta". Lo que
queda sin cubrir se declara en la plantilla en vez de suponerse general.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from contapdf.ir import Document, Line, Page
from contapdf.layout.lines import group
from contapdf.layout.region import find_table_region, lines_within
from contapdf.parsers.balanza import LayoutDesconocido, Mapeo
from contapdf.parsers.base import Layout, detectar_layout, normalizar, parse_monto

_LOG = logging.getLogger(__name__)
_CERO = Decimal("0.00")

_RE_MONTO = re.compile(r"^\$?-?[\d,]*\.\d{2}$")
_RE_DIA = re.compile(r"^\d{1,2}$")
_RE_CLABE = re.compile(r"^\d{18}$")
_RE_RFC = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")
_RE_FECHA_LARGA = re.compile(r"\d{1,2}\s+[A-ZÁÉÍÓÚ]{3}\s+\d{4}")
_X_DIA = 55.0

_MESES = (("ENE", "01"), ("FEB", "02"), ("MAR", "03"), ("ABR", "04"),
          ("MAY", "05"), ("JUN", "06"), ("JUL", "07"), ("AGO", "08"),
          ("SEP", "09"), ("OCT", "10"), ("NOV", "11"), ("DIC", "12"))

# Etiquetas del resumen, tal como las imprime el documento.
_RESUMEN = (("saldo_inicial", "saldo inicial"),
            ("depositos", "depositos"),
            ("retiros", "retiros"),
            ("saldo_corte", "saldo al corte"))


@dataclass(frozen=True)
class MetaEstadoCuenta:
    banco: str = ""
    rfc: str = ""
    num_cuenta: str = ""
    clabe: str = ""
    periodo_ini: str = ""
    periodo_fin: str = ""
    saldo_inicial: Decimal | None = None
    depositos: Decimal | None = None
    retiros: Decimal | None = None
    saldo_corte: Decimal | None = None


@dataclass(frozen=True)
class MovimientoBancario:
    dia: str
    fecha: str
    descripcion: str
    referencia: str
    deposito: Decimal
    retiro: Decimal
    saldo: Decimal | None
    pagina: int = 0


@dataclass(frozen=True)
class EstadoCuenta:
    meta: MetaEstadoCuenta
    movimientos: tuple[MovimientoBancario, ...]
    mapeo: Mapeo | None = None

    def __iter__(self) -> Iterator[MovimientoBancario]:
        return iter(self.movimientos)


def _es_monto(texto: str) -> bool:
    t = texto.strip()
    return bool(t) and bool(_RE_MONTO.match(t))


def _fecha_de(dia: str, periodo_ini: str, periodo_fin: str) -> str:
    """dd/mm/aaaa a partir del dia y del periodo que el documento declara.

    Solo cuando el periodo no cruza de mes: si lo cruzara, el dia solo no
    dice a cual de los dos pertenece y se deja vacio en vez de adivinar.
    """
    partes_ini, partes_fin = periodo_ini.split(), periodo_fin.split()
    if len(partes_ini) != 3 or len(partes_fin) != 3:
        return ""
    if partes_ini[1:] != partes_fin[1:]:
        return ""
    abreviatura = partes_ini[1].upper()[:3]
    mes = next((n for a, n in _MESES if a == abreviatura), "")
    return f"{int(dia):02d}/{mes}/{partes_ini[2]}" if mes else ""


class EstadoCuentaParser:
    """Convierte un Document de estado de cuenta en metadata + movimientos."""

    def __init__(self, paginas_muestra: int = 2) -> None:
        self.paginas_muestra = paginas_muestra

    # --- metadata --------------------------------------------------------
    def _meta(self, paginas: Sequence[Page]) -> MetaEstadoCuenta:
        campos: dict[str, object] = {}
        for page in paginas:
            for line in group(page.words):
                self._banco(line, campos)
                self._identificadores(line, campos)
                self._periodo(line, campos)
                self._resumen(line, campos)
        return MetaEstadoCuenta(**campos)  # type: ignore[arg-type]

    def _banco(self, line: Line, campos: dict) -> None:
        """El nombre del banco se imprime ENCIMA del domicilio.

        Sin separar por corrida salen entrelazados; con ella, la corrida
        que nombra a la institucion es una sola.
        """
        if "banco" in campos:
            return
        for run in {w.run for w in line.words}:
            texto = " ".join(w.text for w in sorted(line.words, key=lambda w: w.x0)
                             if w.run == run)
            plano = normalizar(texto)
            if "banca" in plano.split() and "institucion" in plano:
                campos["banco"] = texto.strip()
                return

    def _identificadores(self, line: Line, campos: dict) -> None:
        textos = [w.text for w in line.words]
        plano = normalizar(" ".join(textos))
        for texto in textos:
            limpio = texto.strip().rstrip(":")
            if _RE_CLABE.match(limpio):
                campos.setdefault("clabe", limpio)
            elif _RE_RFC.match(limpio):
                campos.setdefault("rfc", limpio)
        if "numero de cuenta" in plano and "num_cuenta" not in campos:
            # El numero va justo despues de la etiqueta.
            for i, texto in enumerate(textos):
                if normalizar(texto) == "cuenta" and i + 1 < len(textos):
                    siguiente = textos[i + 1].strip()
                    if siguiente.isdigit():
                        campos["num_cuenta"] = siguiente
                        return

    def _periodo(self, line: Line, campos: dict) -> None:
        if "periodo_ini" in campos:
            return
        texto = " ".join(w.text for w in line.words)
        if "periodo" not in normalizar(texto):
            return
        fechas = _RE_FECHA_LARGA.findall(texto)
        if len(fechas) >= 2:
            campos["periodo_ini"], campos["periodo_fin"] = fechas[0], fechas[1]

    def _resumen(self, line: Line, campos: dict) -> None:
        texto = normalizar(" ".join(w.text for w in line.words))
        montos = [w.text for w in line.words if _es_monto(w.text)]
        if not montos:
            return
        for campo, etiqueta in _RESUMEN:
            if campo in campos:
                continue
            if texto.startswith(etiqueta):
                campos[campo] = parse_monto(montos[0])
                return

    # --- movimientos -----------------------------------------------------
    def _anclas(self, layout: Layout) -> dict[str, float]:
        """El borde derecho de deposito, retiro y saldo, por su encabezado.

        No por posicion: los simbolos '$' forman columnas propias y tomar
        las tres mas a la derecha mete el importe en la casilla vecina.
        """
        etiquetas = {"depositos": "deposito", "deposito": "deposito",
                     "retiros": "retiro", "retiro": "retiro",
                     "saldo": "saldo", "saldos": "saldo"}
        anclas: dict[str, float] = {}
        for columna in layout.montos:
            campo = etiquetas.get(normalizar(columna.header))
            if campo and campo not in anclas:
                anclas[campo] = columna.x_max
        return anclas

    def _movimientos(self, paginas: Sequence[Page], layout: Layout,
                     meta: MetaEstadoCuenta) -> list[MovimientoBancario]:
        anclas = self._anclas(layout)
        movimientos: list[MovimientoBancario] = []

        for page in paginas:
            lineas = group(page.words)
            region = find_table_region(lineas)
            if region is None:
                continue
            for line in lines_within(lineas, region):
                if not line.words:
                    continue
                primera = line.words[0]
                if primera.x0 < _X_DIA and _RE_DIA.match(primera.text):
                    movimientos.append(self._movimiento(line, anclas, meta,
                                                        page.number))
                elif movimientos:
                    # Sin dia: es la continuacion del movimiento anterior.
                    # Se pega SIN separador porque el documento envuelve el
                    # bloque a lo ancho y parte las palabras a la mitad:
                    # 'CON' + 'CEPTO:' es una sola palabra cortada.
                    cola = " ".join(w.text for w in line.words
                                    if not _es_monto(w.text))
                    if cola:
                        movimientos[-1] = replace(
                            movimientos[-1],
                            descripcion=f"{movimientos[-1].descripcion}{cola}")
        return movimientos

    def _movimiento(self, line: Line, anclas: dict[str, float],
                    meta: MetaEstadoCuenta, pagina: int) -> MovimientoBancario:
        montos = [w for w in line.words if _es_monto(w.text)]
        valores: dict[str, Decimal] = {}
        for word in montos:
            if not anclas:
                continue
            campo = min(anclas, key=lambda c: abs(word.x1 - anclas[c]))
            valores[campo] = parse_monto(word.text)

        descripcion = " ".join(w.text for w in line.words[1:]
                               if not _es_monto(w.text) and w.text != "$")
        return MovimientoBancario(
            dia=line.words[0].text,
            fecha=_fecha_de(line.words[0].text, meta.periodo_ini, meta.periodo_fin),
            descripcion=descripcion.strip(),
            referencia="",
            deposito=valores.get("deposito", _CERO),
            retiro=valores.get("retiro", _CERO),
            saldo=valores.get("saldo"),
            pagina=pagina,
        )

    # --- API --------------------------------------------------------------
    def parse(self, document: Document, *, layout: Layout | None = None,
              mapeo: "dict[str, int] | Mapeo | None" = None) -> EstadoCuenta:
        paginas = list(document.open_pages())
        if not paginas:
            raise LayoutDesconocido("el documento no trajo paginas")

        con_tabla = [p for p in paginas
                     if find_table_region(group(p.words)) is not None]
        layout = layout or detectar_layout(con_tabla[:self.paginas_muestra]
                                           or paginas[:self.paginas_muestra])
        if layout is None:
            raise LayoutDesconocido("no se encontro la tabla de movimientos")

        meta = self._meta(paginas)
        movimientos = self._movimientos(paginas, layout, meta)
        if not movimientos:
            raise LayoutDesconocido("no se encontro ningun movimiento")

        conocido = mapeo if isinstance(mapeo, Mapeo) else None
        descripcion = conocido or Mapeo(
            campos={}, forma="edocta", verificado_por="aritmetica",
            orientacion_verificada=True, filas_afectadas=0)
        return EstadoCuenta(meta=meta, movimientos=tuple(movimientos),
                            mapeo=descripcion)
