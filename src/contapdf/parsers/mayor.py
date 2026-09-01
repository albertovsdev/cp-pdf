"""Parser de Libro Mayor.

Un tipo de documento nuevo, no una variante: la unidad no es un renglon ni
un bloque de movimientos, es una CUENTA-ANIO -- encabezado con su saldo
inicial y doce filas, una por mes.

Sale en dos tablas relacionadas y no en una plana. La razon de peso es que
'ninguna fila huerfana' se vuelve un invariante verificable: todo mes
apunta a una cuenta que existe. Aplanarlo repetiria el saldo inicial doce
veces y dejaria el cruce con la balanza sin donde vivir.

Lo que este documento tiene y ningun otro: las secciones se parten entre
paginas. La cuenta abre en el ultimo renglon de una pagina y sus meses
caen en la siguiente, asi que la identidad se arrastra a traves del salto.
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
_TOLERANCIA = Decimal("0.01")

_RE_MONTO = re.compile(r"^-?[\d,]*\.\d{2}$")
_RE_CUENTA = re.compile(r"^\d{3,}[-\d]*\d$")
_X_IZQUIERDA = 60.0
_ETIQUETA_INICIAL = ("inicial", "saldo inicial")

_MESES = ("ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO",
          "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE")


@dataclass(frozen=True)
class CuentaMayor:
    """Una cuenta del mayor, con lo que el documento declara de ella."""

    cuenta: str
    nombre_cuenta: str
    saldo_inicial: Decimal | None
    saldo_final: Decimal | None
    total_cargos: Decimal | None
    total_abonos: Decimal | None
    pagina_inicio: int = 0
    # 'D' o 'A', derivada de sus doce meses; '' si no se pudo determinar.
    # Medido: 34 de las 49 cuentas encadenan con +cargos-abonos y 11 con
    # el signo invertido. Cablear una sola identidad rompe las otras.
    naturaleza: str = ""


@dataclass(frozen=True)
class MesMayor:
    """Un mes de una cuenta. 'orden' va explicito para no parsear nombres."""

    cuenta: str
    orden: int
    periodo: str
    cargos: Decimal
    abonos: Decimal
    saldo: Decimal | None
    acum_cargos: Decimal | None
    acum_abonos: Decimal | None
    pagina: int = 0


@dataclass(frozen=True)
class Mayor:
    cuentas: tuple[CuentaMayor, ...]
    meses: tuple[MesMayor, ...]
    forma: str = ""
    mapeo: Mapeo | None = None

    def __iter__(self) -> Iterator[CuentaMayor]:
        return iter(self.cuentas)


def _es_monto(texto: str) -> bool:
    t = texto.strip()
    return bool(t) and bool(_RE_MONTO.match(t))


def _orden_de(periodo: str) -> int:
    plano = normalizar(periodo).upper()
    for indice, mes in enumerate(_MESES, start=1):
        if plano == normalizar(mes).upper():
            return indice
    return 0


class MayorParser:
    """Convierte un Document de Libro Mayor en cuentas y meses."""

    def __init__(self, paginas_muestra: int = 2) -> None:
        self.paginas_muestra = paginas_muestra

    # --- clasificacion ---------------------------------------------------
    def _abre_cuenta(self, line: Line) -> tuple[str, str] | None:
        """'1120-000-000 BANCOS' -> (cuenta, nombre)."""
        if not line.words or line.words[0].x0 > _X_IZQUIERDA:
            return None
        primera = line.words[0]
        if not _RE_CUENTA.match(primera.text) or _es_monto(primera.text):
            return None
        if any(_es_monto(w.text) for w in line.words):
            return None
        nombre = " ".join(w.text for w in line.words[1:]).strip()
        return primera.text, nombre

    def _saldo_inicial(self, line: Line) -> Decimal | None:
        """'Inicial 101,304.75 Acumulados' -> el saldo con que abre."""
        if not line.words:
            return None
        etiqueta = normalizar(" ".join(w.text for w in line.words[:2]))
        if not any(etiqueta.startswith(e) for e in _ETIQUETA_INICIAL):
            return None
        montos = [w.text for w in line.words if _es_monto(w.text)]
        return parse_monto(montos[0]) if montos else _CERO

    def _es_mes(self, line: Line) -> int:
        return _orden_de(line.words[0].text) if line.words else 0

    # --- lectura ---------------------------------------------------------
    def _leer(self, paginas: Sequence[Page], layout: Layout
              ) -> tuple[list[CuentaMayor], list[MesMayor]]:
        anclas = self._anclas(layout)
        cuentas: list[CuentaMayor] = []
        meses: list[MesMayor] = []
        # La cuenta abierta sobrevive al salto de pagina: la seccion puede
        # empezar en el ultimo renglon de una y seguir en la siguiente.
        abierta: str | None = None

        for page in paginas:
            lineas = group(page.words)
            region = find_table_region(lineas)
            candidatas = lines_within(lineas, region) if region else lineas
            # La cuenta puede abrir arriba de la zona de tabla.
            for line in lineas:
                nueva = self._abre_cuenta(line)
                if nueva is not None:
                    abierta = nueva[0]
                    cuentas.append(CuentaMayor(
                        cuenta=nueva[0], nombre_cuenta=nueva[1],
                        saldo_inicial=None, saldo_final=None,
                        total_cargos=None, total_abonos=None,
                        pagina_inicio=page.number))
                    continue

                if abierta is None:
                    continue

                inicial = self._saldo_inicial(line)
                if inicial is not None and cuentas and cuentas[-1].saldo_inicial is None:
                    cuentas[-1] = replace(cuentas[-1], saldo_inicial=inicial)
                    continue

                orden = self._es_mes(line)
                if orden and (line in candidatas or region is None):
                    meses.append(self._mes(line, abierta, orden, anclas,
                                           page.number))

        return self._cerrar(cuentas, meses), meses

    def _anclas(self, layout: Layout) -> list[float]:
        """Los cinco bordes derechos: cargos, abonos, saldo y los acumulados."""
        return sorted(c.x_max for c in layout.montos)

    def _mes(self, line: Line, cuenta: str, orden: int, anclas: Sequence[float],
             pagina: int) -> MesMayor:
        valores: dict[int, Decimal] = {}
        for word in line.words:
            if not _es_monto(word.text) or not anclas:
                continue
            indice = min(range(len(anclas)), key=lambda i: abs(word.x1 - anclas[i]))
            valores[indice] = parse_monto(word.text)
        return MesMayor(
            cuenta=cuenta, orden=orden, periodo=line.words[0].text,
            cargos=valores.get(0, _CERO), abonos=valores.get(1, _CERO),
            saldo=valores.get(2), acum_cargos=valores.get(3),
            acum_abonos=valores.get(4), pagina=pagina)

    def _naturaleza(self, inicial: Decimal | None,
                    meses: Sequence[MesMayor]) -> str:
        """Cual de las dos identidades sostiene la cadena de esta cuenta.

        Un mes con cargos == abonos no la revela (las dos cuadran), asi
        que decide la mayoria de los que si la revelan.
        """
        if inicial is None:
            return ""
        deudora = acreedora = 0
        anterior = inicial
        for mes in sorted(meses, key=lambda m: m.orden):
            if mes.saldo is None:
                anterior = mes.saldo
                continue
            if anterior is not None and mes.cargos != mes.abonos:
                movimiento = mes.cargos - mes.abonos
                deudora += abs(anterior + movimiento - mes.saldo) <= _TOLERANCIA
                acreedora += abs(anterior - movimiento - mes.saldo) <= _TOLERANCIA
            anterior = mes.saldo
        if deudora == acreedora:
            return ""
        return "D" if deudora > acreedora else "A"

    def _cerrar(self, cuentas: Sequence[CuentaMayor],
                meses: Sequence[MesMayor]) -> list[CuentaMayor]:
        """Rellena el resumen de cada cuenta con lo que el ultimo mes declara.

        Se LEE del documento, no se calcula: el mayor ya imprime los
        acumulados. El checksum los verifica contra la suma.
        """
        ultimo: dict[str, MesMayor] = {}
        for mes in meses:
            actual = ultimo.get(mes.cuenta)
            if actual is None or mes.orden > actual.orden:
                ultimo[mes.cuenta] = mes
        cerradas = []
        for cuenta in cuentas:
            fin = ultimo.get(cuenta.cuenta)
            suyos = [m for m in meses if m.cuenta == cuenta.cuenta]
            naturaleza = self._naturaleza(cuenta.saldo_inicial, suyos)
            cerradas.append(replace(cuenta, naturaleza=naturaleza) if fin is None
                            else replace(
                                cuenta, saldo_final=fin.saldo,
                                total_cargos=fin.acum_cargos,
                                total_abonos=fin.acum_abonos,
                                naturaleza=naturaleza))
        return cerradas

    # --- API --------------------------------------------------------------
    def parse(self, document: Document, *, layout: Layout | None = None,
              mapeo: "dict[str, int] | Mapeo | None" = None) -> Mayor:
        paginas = list(document.open_pages())
        if not paginas:
            raise LayoutDesconocido("el documento no trajo paginas")
        layout = layout or detectar_layout(paginas[:self.paginas_muestra])
        if layout is None:
            raise LayoutDesconocido("no se encontro la tabla del libro mayor")

        cuentas, meses = self._leer(paginas, layout)
        if not cuentas:
            raise LayoutDesconocido("no se encontro ninguna cuenta")

        conocido = mapeo if isinstance(mapeo, Mapeo) else None
        descripcion = conocido or Mapeo(
            campos={}, forma="mayor", verificado_por="aritmetica",
            orientacion_verificada=True, filas_afectadas=0)
        return Mayor(cuentas=tuple(cuentas), meses=tuple(meses),
                     forma=descripcion.forma, mapeo=descripcion)
