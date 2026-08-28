"""Parser de balanza de comprobacion.

Procesa formatos distintos sin ramas por documento. Lo que cambia entre
uno y otro se resuelve por dos vias:

  - el vocabulario PROPONE el mapeo de columnas y el checksum DISPONE
    (PLAN 2): un mapeo que no hace cuadrar la aritmetica es incorrecto;
  - lo que el documento declara se lee, lo que no declara se deriva.
    La naturaleza de la cuenta y si es acumulativa son ejemplos: un
    formato las imprime y el otro no.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from contapdf.ir import Document, Page
from contapdf.parsers.base import (
    Layout,
    celdas,
    detectar_layout,
    es_cuenta,
    normalizar,
    parse_monto,
    lineas_de_tabla,
)

_LOG = logging.getLogger(__name__)

_CERO = Decimal("0.00")
_TOLERANCIA = Decimal("0.01")
_MARCAS_ACUMULATIVA = ("acum", "acumulativa", "acumulativo")
_MARCAS_DETALLE = ("deta", "detalle")
_NOMBRES_TOTALES = ("totales", "total", "sumas", "suma")


@dataclass(frozen=True)
class Forma:
    """Una manera conocida de imprimir una balanza.

    'campos' va en orden de prioridad: 'cuenta' reclama la columna del
    numero antes de que 'nombre' reclame la del texto, que en varias
    balanzas se llama igual.
    """

    nombre: str
    campos: tuple[tuple[str, tuple[str, ...], bool], ...]  # campo, sinonimos, obligatorio


_CUENTA = ("no cuenta", "num cuenta", "numero de cuenta", "numero cuenta",
           "cuenta contable", "codigo", "cuenta")
_NOMBRE = ("nombre", "descripcion", "nombre de la cuenta", "concepto", "cuenta")
_NATURALEZA = ("naturaleza", "nat")

# Dos formas medidas sobre documentos reales. La primera parte el saldo en
# deudor y acreedor; la segunda trae una sola columna con signo.
_FORMAS = (
    Forma("deudor_acreedor", (
        ("cuenta", _CUENTA, True),
        ("naturaleza", _NATURALEZA, False),
        ("nombre", _NOMBRE, True),
        ("saldo_ini_deudor", ("saldo inicial deudor", "saldo anterior deudor"), True),
        ("saldo_ini_acreedor", ("saldo inicial acreedor", "saldo anterior acreedor"), True),
        ("debe", ("debe", "cargos"), True),
        ("haber", ("haber", "abonos", "creditos"), True),
        ("saldo_fin_deudor", ("saldo final deudor", "saldo actual deudor"), True),
        ("saldo_fin_acreedor", ("saldo final acreedor", "saldo actual acreedor"), True),
    )),
    Forma("saldo_con_signo", (
        ("cuenta", _CUENTA, True),
        ("naturaleza", _NATURALEZA, False),
        ("nombre", _NOMBRE, True),
        ("saldo_inicial", ("saldo anterior", "saldo inicial", "saldo previo"), True),
        ("debe", ("cargos", "debe"), True),
        ("haber", ("creditos", "abonos", "haber"), True),
        ("saldo_mes", ("saldo mes", "saldo del mes", "movimiento"), False),
        ("saldo_final", ("saldo actual", "saldo final"), True),
    )),
)

_MONTOS_SPLIT = ("saldo_ini_deudor", "saldo_ini_acreedor", "debe", "haber",
                 "saldo_fin_deudor", "saldo_fin_acreedor")


class LayoutDesconocido(ValueError):
    """El layout no trae las columnas que una balanza necesita."""


@dataclass(frozen=True)
class FilaBalanza:
    """Un renglon de la balanza.

    'nivel', 'cuenta_padre' y 'es_acumulativa' se derivan cuando el
    documento no los imprime. 'naturaleza' tambien: hay formatos que la
    declaran en una columna y otros donde sale de la aritmetica.
    """

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
    es_acumulativa: bool = False


@dataclass(frozen=True)
class Totales:
    """La fila de totales que el PDF trae al final ('Totales', 'SUMAS')."""

    debe: Decimal
    haber: Decimal


@dataclass(frozen=True)
class Balanza:
    filas: tuple[FilaBalanza, ...]
    totales: Totales | None
    forma: str = ""

    def __iter__(self) -> Iterator[FilaBalanza]:
        return iter(self.filas)


def _puntaje(etiqueta: str, sinonimos: Sequence[str]) -> int:
    """3 si el encabezado es exactamente el sinonimo, 2 si lo contiene.

    La coincidencia por contencion hace falta porque hay encabezados que
    llegan con basura pegada: en Business Pro el titulo de seccion cae
    dentro del bloque de encabezado y la etiqueta sale como
    'DEL MES *** * CREDITOS'.
    """
    plano = normalizar(etiqueta)
    if not plano:
        return 0
    palabras = plano.split()
    mejor = 0
    for s in sinonimos:
        objetivo = s.split()
        if plano == s:
            return 3
        for i in range(len(palabras) - len(objetivo) + 1):
            if palabras[i:i + len(objetivo)] == objetivo:
                mejor = max(mejor, 2)
    return mejor


def _candidatos(layout: Layout, forma: Forma) -> dict[str, list[tuple[int, int]]]:
    salida: dict[str, list[tuple[int, int]]] = {}
    for campo, sinonimos, _ in forma.campos:
        opciones = [(_puntaje(c.header, sinonimos), c.index) for c in layout.columns]
        salida[campo] = sorted(((p, i) for p, i in opciones if p > 0),
                               key=lambda t: (-t[0], t[1]))
    return salida


def _combinar(forma: Forma, candidatos: dict[str, list[tuple[int, int]]],
              maximo: int) -> list[dict[str, int]]:
    """Todas las asignaciones consistentes, de mejor a peor puntaje."""
    salida: list[tuple[int, dict[str, int]]] = []

    def avanzar(i: int, usados: set[int], parcial: dict[str, int], puntos: int) -> None:
        if len(salida) >= maximo:
            return
        if i == len(forma.campos):
            salida.append((puntos, dict(parcial)))
            return
        campo, _, obligatorio = forma.campos[i]
        for puntaje, indice in candidatos[campo]:
            if indice in usados:
                continue
            parcial[campo] = indice
            avanzar(i + 1, usados | {indice}, parcial, puntos + puntaje)
            del parcial[campo]
        if not obligatorio:
            avanzar(i + 1, usados, parcial, puntos)

    avanzar(0, set(), {}, 0)
    salida.sort(key=lambda t: -t[0])
    return [m for _, m in salida]


def proponer_mapeos(layout: Layout, *, maximo: int = 40) -> list[dict[str, int]]:
    """Mapeos campo -> indice de columna, del mas plausible al menos.

    Solo son propuestas: el vocabulario no basta para decidir. Quien las
    consume tiene que verificarlas contra la aritmetica del documento.
    """
    propuestas: list[dict[str, int]] = []
    for forma in _FORMAS:
        candidatos = _candidatos(layout, forma)
        if any(not candidatos[campo] for campo, _, obl in forma.campos if obl):
            continue
        propuestas.extend(_combinar(forma, candidatos, maximo))
    return propuestas[:maximo]


def _forma_de(mapeo: dict[str, int]) -> Forma:
    return _FORMAS[0] if "saldo_ini_deudor" in mapeo else _FORMAS[1]


def _faltantes(layout: Layout) -> list[str]:
    """Los campos obligatorios que ninguna forma logro nombrar."""
    mejor: list[str] = []
    for forma in _FORMAS:
        candidatos = _candidatos(layout, forma)
        faltan = [campo for campo, _, obl in forma.campos
                  if obl and not candidatos[campo]]
        if not mejor or len(faltan) < len(mejor):
            mejor = faltan
    return mejor


def _significativos(cuenta: str) -> tuple[list[str], int]:
    """Segmentos de la cuenta y cuantos son significativos.

    Hay catalogos que rellenan a lo ancho: 0400-0001-0000-0000 es una
    cuenta de nivel 2, no de nivel 4. Los segmentos finales todo-ceros son
    relleno. Ninguna cuenta de los documentos medidos usa un segmento
    todo-ceros con significado.
    """
    partes = cuenta.split("-")
    fin = len(partes)
    while fin > 1 and set(partes[fin - 1]) == {"0"}:
        fin -= 1
    return partes, fin


def _derivar(cuenta: str) -> tuple[int, str]:
    partes, fin = _significativos(cuenta)
    if fin <= 1:
        return 1, ""
    cabeza = partes[:fin - 1]
    if fin == len(partes):
        return fin, "-".join(cabeza)  # sin relleno: el padre es el prefijo
    relleno = ["0" * len(p) for p in partes[fin - 1:]]
    return fin, "-".join(cabeza + relleno)


def _naturaleza_derivada(inicial: Decimal, final: Decimal,
                         debe: Decimal, haber: Decimal) -> str:
    """D, A o '' segun cual identidad sostiene el renglon.

    Medido en 225 renglones: el movimiento del periodo es debe - haber sin
    depender de la naturaleza, y es el signo con que se aplica al saldo lo
    que la distingue. Si no hubo movimiento neto, el renglon no la revela.
    """
    movimiento = debe - haber
    if movimiento == _CERO:
        return ""
    if abs(inicial + movimiento - final) <= _TOLERANCIA:
        return "D"
    if abs(inicial - movimiento - final) <= _TOLERANCIA:
        return "A"
    return ""


@dataclass(frozen=True)
class _Cruda:
    """Lo leido de un renglon, antes de decidir naturaleza y jerarquia."""

    cuenta: str
    nombre: str
    naturaleza: str
    marca: str
    montos: dict[str, Decimal]


def _celda(datos: dict[int, str], mapeo: dict[str, int], campo: str) -> str:
    indice = mapeo.get(campo)
    return "" if indice is None else datos.get(indice, "").strip()


def _marca_de(texto: Sequence[str]) -> str:
    for palabra in texto:
        plano = normalizar(palabra)
        if plano in _MARCAS_ACUMULATIVA:
            return "acumulativa"
        if plano in _MARCAS_DETALLE:
            return "detalle"
    return ""


class BalanzaParser:
    """Convierte un Document de balanza en filas validables."""

    def __init__(self, paginas_muestra: int = 3) -> None:
        self.paginas_muestra = paginas_muestra

    # --- lectura de renglones -------------------------------------------
    def _crudas(self, page: Page, layout: Layout,
                mapeo: dict[str, int]) -> tuple[list[_Cruda], Totales | None]:
        forma = _forma_de(mapeo)
        campos = [c for c, _, _ in forma.campos
                  if c not in ("cuenta", "nombre", "naturaleza")]
        filas: list[_Cruda] = []
        totales: Totales | None = None

        for line in lineas_de_tabla(page):
            datos = celdas(line, layout)
            cuenta = _celda(datos, mapeo, "cuenta")
            nombre = _celda(datos, mapeo, "nombre")
            montos = {c: parse_monto(_celda(datos, mapeo, c)) for c in campos
                      if _celda(datos, mapeo, c)}

            if es_cuenta(cuenta):
                filas.append(_Cruda(
                    cuenta=cuenta,
                    nombre=" ".join(p for p in nombre.split()
                                    if normalizar(p) not in
                                    _MARCAS_ACUMULATIVA + _MARCAS_DETALLE),
                    naturaleza=_celda(datos, mapeo, "naturaleza").upper()[:1],
                    marca=_marca_de([w.text for w in line.words]),
                    montos=montos,
                ))
            elif cuenta:
                continue  # el encabezado se repite en cada pagina
            elif any(normalizar(nombre).startswith(t) for t in _NOMBRES_TOTALES):
                if "debe" in montos and "haber" in montos:
                    totales = Totales(debe=montos["debe"], haber=montos["haber"])
            elif nombre and filas:
                # Nombre partido en dos renglones: el segundo no trae ni
                # numero de cuenta ni importes.
                filas[-1] = replace(filas[-1],
                                    nombre=f"{filas[-1].nombre} {nombre}".strip())
        return filas, totales

    # --- verificacion aritmetica ----------------------------------------
    def verifica(self, layout: Layout, paginas: Sequence[Page],
                 mapeo: dict[str, int], *, minimo: int = 5,
                 proporcion: float = 0.9) -> bool:
        """True si el mapeo propuesto hace cuadrar la aritmetica.

        Es el paso que convierte al diccionario de sinonimos en una pista y
        no en una fuente de verdad: dos encabezados pueden llamarse igual y
        significar cosas distintas, pero solo un mapeo cuadra.
        """
        crudas: list[_Cruda] = []
        for page in paginas:
            crudas.extend(self._crudas(page, layout, mapeo)[0])
        if len(crudas) < minimo:
            return False

        buenas = 0
        for cruda in crudas:
            m = cruda.montos
            if "debe" not in m or "haber" not in m:
                continue
            movimiento = m["debe"] - m["haber"]
            if "saldo_mes" in m and abs(m["saldo_mes"] - movimiento) > _TOLERANCIA:
                # El saldo del mes rompe la simetria entre debe y haber:
                # sin el, invertir las dos columnas cuadraria igual.
                return False
            if "saldo_ini_deudor" in m:
                inicial = m["saldo_ini_deudor"] - m.get("saldo_ini_acreedor", _CERO)
                final = m["saldo_fin_deudor"] - m.get("saldo_fin_acreedor", _CERO)
                if abs(inicial + movimiento - final) <= _TOLERANCIA:
                    buenas += 1
            else:
                if _naturaleza_derivada(m.get("saldo_inicial", _CERO),
                                        m.get("saldo_final", _CERO),
                                        m["debe"], m["haber"]) or movimiento == _CERO:
                    buenas += 1
        return buenas >= len(crudas) * proporcion

    # --- armado de filas -------------------------------------------------
    def _fila(self, cruda: _Cruda, naturaleza: str) -> FilaBalanza:
        nivel, padre = _derivar(cruda.cuenta)
        m = cruda.montos
        if "saldo_ini_deudor" in m:
            montos = {c: m.get(c, _CERO) for c in _MONTOS_SPLIT}
        else:
            inicial, final = m.get("saldo_inicial", _CERO), m.get("saldo_final", _CERO)
            acreedora = naturaleza == "A"
            montos = {
                "saldo_ini_deudor": _CERO if acreedora else inicial,
                "saldo_ini_acreedor": inicial if acreedora else _CERO,
                "debe": m.get("debe", _CERO),
                "haber": m.get("haber", _CERO),
                "saldo_fin_deudor": _CERO if acreedora else final,
                "saldo_fin_acreedor": final if acreedora else _CERO,
            }
        return FilaBalanza(cuenta=cruda.cuenta, nivel=nivel, cuenta_padre=padre,
                           naturaleza=naturaleza, nombre=cruda.nombre,
                           es_acumulativa=cruda.marca == "acumulativa", **montos)

    def _resolver(self, crudas: Sequence[_Cruda]) -> tuple[FilaBalanza, ...]:
        """Deriva lo que el documento no declara: naturaleza y jerarquia."""
        naturaleza: dict[str, str] = {}
        for cruda in crudas:
            m = cruda.montos
            if cruda.naturaleza in ("D", "A"):
                naturaleza[cruda.cuenta] = cruda.naturaleza
            else:
                naturaleza[cruda.cuenta] = _naturaleza_derivada(
                    m.get("saldo_inicial", _CERO), m.get("saldo_final", _CERO),
                    m.get("debe", _CERO), m.get("haber", _CERO))

        # Sin movimiento neto el renglon no revela su naturaleza: la hereda
        # de la cuenta padre, que si la revelo.
        for cruda in sorted(crudas, key=lambda c: _derivar(c.cuenta)[0]):
            if naturaleza[cruda.cuenta]:
                continue
            padre = _derivar(cruda.cuenta)[1]
            while padre and not naturaleza.get(padre):
                padre = _derivar(padre)[1]
            naturaleza[cruda.cuenta] = naturaleza.get(padre, "") or "D"

        filas = [self._fila(c, naturaleza[c.cuenta]) for c in crudas]

        # El marcador explicito manda; si el documento no lo trae, es
        # acumulativa la cuenta que tenga hijas presentes.
        if not any(c.marca for c in crudas):
            padres = {f.cuenta_padre for f in filas if f.cuenta_padre}
            filas = [replace(f, es_acumulativa=f.cuenta in padres) for f in filas]
        return tuple(filas)

    # --- API --------------------------------------------------------------
    def parse(self, document: Document, *, layout: Layout | None = None,
              mapeo: dict[str, int] | None = None) -> Balanza:
        """Lee el documento en UNA sola pasada y devuelve filas validables."""
        muestra: list[Page] = []
        crudas: list[_Cruda] = []
        totales: Totales | None = None
        listo = layout is not None and mapeo is not None

        for page in document.open_pages():
            if not listo:
                muestra.append(page)
                if len(muestra) < self.paginas_muestra:
                    continue
                layout, mapeo = self._resolver_layout(muestra, layout, mapeo)
                if layout is None:
                    muestra.pop(0)  # ninguna de estas paginas trae tabla
                    continue
                listo = True
                for pendiente in muestra:
                    nuevas, tot = self._crudas(pendiente, layout, mapeo)
                    crudas.extend(nuevas)
                    totales = tot or totales
                muestra.clear()
            else:
                nuevas, tot = self._crudas(page, layout, mapeo)
                crudas.extend(nuevas)
                totales = tot or totales

        if muestra:
            layout, mapeo = self._resolver_layout(muestra, layout, mapeo)
            if layout is not None:
                for pendiente in muestra:
                    nuevas, tot = self._crudas(pendiente, layout, mapeo)
                    crudas.extend(nuevas)
                    totales = tot or totales

        if layout is None or mapeo is None:
            raise LayoutDesconocido("no se encontro ninguna tabla de balanza")
        return Balanza(filas=self._resolver(crudas), totales=totales,
                       forma=_forma_de(mapeo).nombre)

    def _resolver_layout(self, muestra: Sequence[Page], layout: Layout | None,
                         mapeo: dict[str, int] | None
                         ) -> tuple[Layout | None, dict[str, int] | None]:
        layout = layout or detectar_layout(muestra)
        if layout is None:
            return None, None
        if mapeo is not None:
            return layout, mapeo

        propuestas = proponer_mapeos(layout)
        for propuesta in propuestas:
            if self.verifica(layout, muestra, propuesta):
                _LOG.info("mapeo aceptado (%s): %s", _forma_de(propuesta).nombre,
                          sorted(propuesta))
                return layout, propuesta

        faltan = _faltantes(layout)
        if faltan:
            raise LayoutDesconocido(
                "el layout no parece una balanza; faltan las columnas: "
                + ", ".join(faltan))
        raise LayoutDesconocido(
            f"ninguno de los {len(propuestas)} mapeos propuestos hace cuadrar "
            "la aritmetica del documento")


def mapear_columnas(layout: Layout) -> dict[str, int]:
    """El mapeo mas plausible por vocabulario, sin verificar aritmetica."""
    propuestas = proponer_mapeos(layout)
    if not propuestas:
        raise LayoutDesconocido(
            "el layout no parece una balanza; faltan las columnas: "
            + ", ".join(_faltantes(layout)))
    return propuestas[0]
