"""Parser de auxiliar de cuentas.

Un auxiliar no es una tabla: es una secuencia de SECCIONES. Cada seccion
declara una cuenta con su saldo inicial y debajo van sus movimientos, que
tienen que arrastrar esa identidad. Las dos variantes medidas declaran la
seccion de formas distintas -- una con etiqueta ('Cuenta: 101-01~Caja'),
otra con una fila propia ('1120-001-003 BANORTE 36,030.99') -- y ninguna
de las dos pone esa fila dentro de la zona que detecta layout.region.

De ahi las dos decisiones del modulo: la region sirve para la GEOMETRIA
(donde caen las columnas) pero el contenido se recorre pagina completa, y
cada renglon se clasifica por lo que trae, no por el formato del que
viene.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from contapdf.ir import Document, Line, Page
from contapdf.layout.lines import group
from contapdf.layout.region import find_table_region
from contapdf.parsers.balanza import LayoutDesconocido, Mapeo
from contapdf.parsers.base import (
    Layout,
    celdas,
    detectar_layout,
    normalizar,
    parse_monto,
)

_LOG = logging.getLogger(__name__)
_CERO = Decimal("0.00")
_TOLERANCIA = Decimal("0.01")

_RE_FECHA = re.compile(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$")
_RE_MONTO = re.compile(r"^\$?-?[\d,]*\.\d{2}$")
_RE_CUENTA = re.compile(r"^\d{2,}[-~][\d-]*\d")
_RE_ENTERO = re.compile(r"^\d{1,8}$")
_ETIQUETA_CUENTA = ("cuenta",)
_ETIQUETA_SALDO = ("saldo inicial", "saldo anterior")
_ETIQUETA_SUBTOTAL = ("total", "totales", "suma", "sumas")

# Campo canonico -> como se llama en los encabezados observados. El orden
# importa igual que en la balanza: quien reclama primero se queda con la
# columna.
_CAMPOS = (
    ("fecha", ("fecha", "folio fecha", "numerofecha"), True, "fecha"),
    # 'folio fecha' y 'numerofecha' nombran a los dos campos: el encabezado
    # viene fusionado y quien se queda con cual lo decide la forma del dato.
    ("folio", ("folio", "numero", "num", "no", "numerofecha", "folio fecha"),
     False, "entero"),
    ("tipo_movimiento", ("tipo", "tipo de movimiento"), False, "texto"),
    ("documento", ("documento", "referencia", "concepto"), False, "texto"),
    ("tercero", ("tercero", "concepto del movimiento", "beneficiario",
                 "descripcion", "concepto"), False, "texto"),
    ("debe", ("debe", "cargos", "cargo"), True, "monto"),
    ("haber", ("haber", "abonos", "abono"), True, "monto"),
    ("saldo", ("saldo", "saldos", "saldo final"), True, "monto"),
)
_MONTOS = ("debe", "haber", "saldo")


@dataclass(frozen=True)
class FilaAuxiliar:
    """Un movimiento, con la cuenta de su seccion ya arrastrada."""

    cuenta: str
    nombre_cuenta: str
    saldo_inicial_cuenta: Decimal
    folio: str
    fecha: str
    tipo_movimiento: str
    documento: str
    tercero: str
    debe: Decimal
    haber: Decimal
    # None cuando el documento no lo dejo leer. Rellenarlo con lo que
    # deberia valer seria inventar dato; dejarlo fuera seria perder el
    # movimiento. Se emite el renglon y la cobertura lo declara.
    saldo: Decimal | None
    es_subtotal: bool = False


@dataclass(frozen=True)
class Auxiliar:
    filas: tuple[FilaAuxiliar, ...]
    secciones: int = 0
    forma: str = ""
    mapeo: Mapeo | None = None

    def __iter__(self) -> Iterator[FilaAuxiliar]:
        return iter(self.filas)


@dataclass(frozen=True)
class _Seccion:
    cuenta: str
    nombre: str
    saldo_inicial: Decimal


def _es_fecha(texto: str) -> bool:
    return bool(_RE_FECHA.match(texto.strip()))


def _es_monto(texto: str) -> bool:
    t = texto.strip()
    return bool(t) and bool(_RE_MONTO.match(t))


def _forma_de_celda(texto: str) -> str:
    t = texto.strip()
    if _es_fecha(t):
        return "fecha"
    if _es_monto(t):
        return "monto"
    if _RE_ENTERO.match(t):
        return "entero"
    return "texto"


def _puntaje(etiqueta: str, sinonimos: Sequence[str]) -> int:
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


def _forma_observada(columna: int, muestras: Sequence[dict[int, str]]) -> str:
    """Que suele traer una columna: fechas, montos o texto.

    Hace falta porque hay encabezados que se fusionan ('FOLIO FECHA',
    'NumeroFecha') y dejan una columna sin nombre. El vocabulario no la
    puede reclamar, pero el contenido la delata.
    """
    formas = [_forma_de_celda(m[columna]) for m in muestras
              if m.get(columna, "").strip()]
    if not formas:
        return "vacia"
    for forma in ("fecha", "monto", "entero"):
        if formas.count(forma) >= len(formas) * 0.8:
            return forma
    return "texto"


def proponer_mapeos(layout: Layout, muestras: Sequence[dict[int, str]], *,
                    maximo: int = 60) -> list[dict[str, int]]:
    """Mapeos campo -> columna, del mas plausible al menos.

    Un campo puede reclamar una columna por su encabezado o, si nadie la
    nombro, por la forma de lo que contiene. Lo segundo puntua menos: el
    vocabulario propone primero, pero no puede ser el unico camino cuando
    el encabezado viene fusionado.
    """
    candidatos: dict[str, list[tuple[int, int]]] = {}
    for campo, sinonimos, _, forma in _CAMPOS:
        opciones: list[tuple[int, int]] = []
        for columna in layout.columns:
            puntos = _puntaje(columna.header, sinonimos)
            if not puntos and forma in ("fecha", "monto", "entero"):
                if _forma_observada(columna.index, muestras) == forma:
                    puntos = 1
            if puntos:
                opciones.append((puntos, columna.index))
        candidatos[campo] = sorted(opciones, key=lambda t: (-t[0], t[1]))

    salida: list[tuple[int, dict[str, int]]] = []

    def avanzar(i: int, usados: set[int], parcial: dict[str, int], puntos: int) -> None:
        if len(salida) >= maximo:
            return
        if i == len(_CAMPOS):
            salida.append((puntos, dict(parcial)))
            return
        campo, _, obligatorio, _forma = _CAMPOS[i]
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
    return [m for _, m in salida[:maximo]]


def _faltantes(layout: Layout, muestras: Sequence[dict[int, str]]) -> list[str]:
    propuestas = proponer_mapeos(layout, muestras, maximo=1)
    if propuestas:
        return []
    return [campo for campo, _, obligatorio, _f in _CAMPOS if obligatorio]


class AuxiliarParser:
    """Convierte un Document de auxiliar en movimientos validables."""

    def __init__(self, paginas_muestra: int = 3) -> None:
        self.paginas_muestra = paginas_muestra

    # --- layout ----------------------------------------------------------
    def _layout(self, paginas: Sequence[Page]) -> Layout | None:
        """Geometria de la region, etiquetas de donde esten.

        En las dos variantes el encabezado de columnas cae FUERA de la
        zona de tabla: en una porque la seccion la precede, en la otra
        porque la tabla arranca con una fila de cuenta. Se busca el
        renglon que habla el vocabulario de los campos, no el que esta
        pegado arriba de los datos.
        """
        layout = detectar_layout(paginas)
        if layout is None:
            return None
        etiquetas: dict[int, list[tuple[float, str]]] = {}
        for page in paginas:
            for line in group(page.words):
                if not self._parece_encabezado(line):
                    continue
                for indice, texto in celdas(line, layout).items():
                    etiquetas.setdefault(indice, []).append((line.top, texto))
        if not etiquetas:
            return replace(layout, texto_en_montos=True)
        columnas = []
        for columna in layout.columns:
            trozos = sorted(etiquetas.get(columna.index, []))
            columnas.append(replace(columna,
                                    header=" ".join(t for _, t in trozos).strip()
                                    or columna.header))
        return Layout(columns=tuple(columnas), texto_en_montos=True)

    def _parece_encabezado(self, line: Line) -> bool:
        """Un renglon de encabezado nombra varios campos y no trae importes."""
        if any(_es_monto(w.text) for w in line.words):
            return False
        palabras = normalizar(" ".join(w.text for w in line.words)).split()
        nombrados = {campo for campo, sinonimos, _o, _f in _CAMPOS
                     for s in sinonimos if s in palabras}
        return len(nombrados) >= 2

    # --- clasificacion de renglones -------------------------------------
    def _seccion_etiquetada(self, line: Line) -> tuple[str, str] | None:
        """'Cuenta: 101-01~Caja y efectivo' -> (cuenta, nombre)."""
        textos = [w.text for w in line.words]
        if not textos:
            return None
        if normalizar(textos[0]).rstrip(":") not in _ETIQUETA_CUENTA:
            return None
        resto = textos[1:]
        if not resto or not _RE_CUENTA.match(resto[0]):
            return None
        cuenta, _, cola = resto[0].partition("~")
        nombre = " ".join([cola] + resto[1:]).strip()
        return cuenta, nombre

    def _saldo_etiquetado(self, line: Line) -> Decimal | None:
        textos = [w.text for w in line.words]
        etiqueta = normalizar(" ".join(textos[:2])).rstrip(":")
        if etiqueta not in _ETIQUETA_SALDO:
            return None
        montos = [t for t in textos if _es_monto(t)]
        return parse_monto(montos[-1]) if montos else _CERO

    def _seccion_en_fila(self, line: Line, mapeo: dict[str, int],
                         datos: dict[int, str]) -> tuple[str, str, Decimal] | None:
        """'1120-001-003 BANORTE 0412181252  36,030.99' -> cuenta, nombre, saldo.

        Una fila de cuenta no trae fecha y trae a lo sumo un importe: el
        saldo con el que abre la seccion.
        """
        primero = line.words[0]
        if primero.x0 > 80 or not re.match(r"^\d{3,}[-\d]*$", primero.text):
            return None
        if any(_es_fecha(w.text) for w in line.words):
            return None
        montos = [w.text for w in line.words if _es_monto(w.text)]
        if len(montos) > 1:
            return None
        nombre = " ".join(w.text for w in line.words[1:] if not _es_monto(w.text))
        return primero.text, nombre.strip(), parse_monto(montos[0]) if montos else _CERO

    def _es_subtotal(self, datos: dict[int, str], line: Line) -> bool:
        if any(_es_fecha(w.text) for w in line.words):
            return False
        palabras = normalizar(" ".join(w.text for w in line.words)).split()
        if not palabras or palabras[0] not in _ETIQUETA_SUBTOTAL:
            return False
        return any(_es_monto(w.text) for w in line.words)

    # --- lectura ---------------------------------------------------------
    def _leer(self, paginas: Sequence[Page], layout: Layout,
              mapeo: dict[str, int]) -> tuple[list[FilaAuxiliar], int]:
        filas: list[FilaAuxiliar] = []
        seccion: _Seccion | None = None
        pendiente_saldo: tuple[str, str] | None = None
        secciones = 0

        for page in paginas:
            lineas = group(page.words)
            region = find_table_region(lineas)
            for line in lineas:
                datos = celdas(line, layout)
                dentro = region is not None and (
                    region.top <= (line.top + line.bottom) / 2 <= region.bottom)

                etiquetada = self._seccion_etiquetada(line)
                if etiquetada is not None:
                    pendiente_saldo = etiquetada
                    continue
                if pendiente_saldo is not None:
                    saldo = self._saldo_etiquetado(line)
                    if saldo is not None:
                        seccion = _Seccion(pendiente_saldo[0], pendiente_saldo[1], saldo)
                        pendiente_saldo = None
                        secciones += 1
                        continue

                if self._es_subtotal(datos, line):
                    if seccion is not None:
                        filas.append(self._fila(seccion, datos, mapeo, subtotal=True))
                    continue

                fecha = datos.get(mapeo["fecha"], "").strip()
                # Basta con que se lean los movimientos del renglon: el
                # saldo corrido puede faltar y el movimiento sigue siendo
                # un movimiento.
                montos_ok = all(_es_monto(datos.get(mapeo[c], ""))
                                for c in ("debe", "haber"))
                if _es_fecha(fecha) and montos_ok:
                    if seccion is None:
                        continue  # movimiento sin seccion: no se sabe de que cuenta
                    filas.append(self._fila(seccion, datos, mapeo))
                    continue

                en_fila = self._seccion_en_fila(line, mapeo, datos)
                if en_fila is not None:
                    seccion = _Seccion(*en_fila)
                    secciones += 1
                    continue

                # Renglon sin importes ni fecha: es la cola de lo anterior.
                # Solo dentro de la zona de tabla: fuera de ella vive el
                # membrete, el encabezado y el pie, que no continuan nada.
                if (dentro and filas and not self._parece_encabezado(line)
                        and not any(_es_monto(w.text) for w in line.words)):
                    filas[-1] = self._continuar(filas[-1], datos, mapeo)

        return filas, secciones

    def _fila(self, seccion: _Seccion, datos: dict[int, str], mapeo: dict[str, int],
              *, subtotal: bool = False) -> FilaAuxiliar:
        def celda(campo: str) -> str:
            indice = mapeo.get(campo)
            return "" if indice is None else datos.get(indice, "").strip()

        return FilaAuxiliar(
            cuenta=seccion.cuenta,
            nombre_cuenta=seccion.nombre,
            saldo_inicial_cuenta=seccion.saldo_inicial,
            folio=celda("folio"),
            fecha=celda("fecha"),
            tipo_movimiento=celda("tipo_movimiento"),
            documento=celda("documento"),
            tercero=celda("tercero"),
            debe=parse_monto(celda("debe")),
            haber=parse_monto(celda("haber")),
            saldo=parse_monto(celda("saldo")) if _es_monto(celda("saldo")) else None,
            es_subtotal=subtotal,
        )

    def _continuar(self, fila: FilaAuxiliar, datos: dict[int, str],
                   mapeo: dict[str, int]) -> FilaAuxiliar:
        """El tercero y el tipo se envuelven en varios renglones."""
        cambios: dict[str, str] = {}
        for campo in ("tipo_movimiento", "documento", "tercero"):
            indice = mapeo.get(campo)
            cola = "" if indice is None else datos.get(indice, "").strip()
            if cola:
                actual = getattr(fila, campo)
                cambios[campo] = f"{actual} {cola}".strip()
        return replace(fila, **cambios) if cambios else fila

    # --- verificacion ----------------------------------------------------
    def verifica(self, filas: Sequence[FilaAuxiliar], *, minimo: int = 5,
                 proporcion: float = 0.9) -> bool:
        """True si el saldo corrido sostiene el mapeo propuesto.

        Es el mismo principio de la balanza: el vocabulario propone y la
        aritmetica dispone. Un mapeo que confunda debe con saldo puede
        parecer razonable por el encabezado y no cuadra nunca.
        """
        movimientos = [f for f in filas if not f.es_subtotal]
        if len(movimientos) < minimo:
            return False
        buenas = comprobadas = 0
        anterior: Decimal | None = None
        cuenta_actual = ""
        for fila in movimientos:
            if fila.cuenta != cuenta_actual:
                cuenta_actual, anterior = fila.cuenta, fila.saldo_inicial_cuenta
            if fila.saldo is None:
                anterior = None  # sin saldo no se puede encadenar el siguiente
                continue
            if anterior is not None:
                comprobadas += 1
                if abs(anterior + fila.debe - fila.haber - fila.saldo) <= _TOLERANCIA:
                    buenas += 1
            anterior = fila.saldo
        if comprobadas < minimo:
            return False
        return buenas >= comprobadas * proporcion

    # --- API --------------------------------------------------------------
    def parse(self, document: Document, *, layout: Layout | None = None,
              mapeo: "dict[str, int] | Mapeo | None" = None) -> Auxiliar:
        conocido = mapeo if isinstance(mapeo, Mapeo) else None
        campos = dict(conocido.campos) if conocido else mapeo

        paginas = list(document.open_pages())
        layout = layout or self._layout(paginas[:self.paginas_muestra])
        if layout is None:
            raise LayoutDesconocido("no se encontro ninguna tabla de auxiliar")

        if campos is None:
            campos = self._resolver_mapeo(paginas, layout)

        filas, secciones = self._leer(paginas, layout, campos)
        descripcion = conocido or Mapeo(
            campos=dict(campos), forma="auxiliar",
            verificado_por="aritmetica" if self.verifica(filas) else "vocabulario",
            orientacion_verificada=self.verifica(filas),
            filas_afectadas=0,
        )
        return Auxiliar(filas=tuple(filas), secciones=secciones,
                        forma=descripcion.forma, mapeo=descripcion)

    def _resolver_mapeo(self, paginas: Sequence[Page],
                        layout: Layout) -> dict[str, int]:
        muestras = [celdas(ln, layout)
                    for page in paginas[:self.paginas_muestra]
                    for ln in group(page.words)]
        propuestas = proponer_mapeos(layout, muestras)
        for propuesta in propuestas:
            filas, _ = self._leer(paginas[:self.paginas_muestra], layout, propuesta)
            if self.verifica(filas):
                _LOG.info("mapeo de auxiliar aceptado: %s", sorted(propuesta))
                return propuesta

        faltan = _faltantes(layout, muestras)
        if faltan:
            raise LayoutDesconocido(
                "el layout no parece un auxiliar; faltan las columnas: "
                + ", ".join(faltan))
        raise LayoutDesconocido(
            f"ninguno de los {len(propuestas)} mapeos propuestos hace cuadrar "
            "el saldo corrido")
