"""Parser del libro diario.

Una poliza no es una fila: es un BLOQUE con encabezado, movimientos,
opcionalmente sus CFDI, y un cierre que declara los totales. Las dos
variantes medidas lo arman distinto -- una con campos etiquetados ('Tipo
de poliza', 'Fecha') y otra con un renglon de nombre seguido de sus
movimientos y un 'TOTAL POLIZA:' -- pero las dos son el mismo bloque.

Salida en tres tablas relacionadas (PLAN 1.2), no una plana: un CFDI no
pertenece a un movimiento sino a la poliza, y aplanarlo desde el principio
pierde esa relacion.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from contapdf.ir import Document, Line, Page
from contapdf.layout.lines import group
from contapdf.parsers.balanza import LayoutDesconocido, Mapeo
from contapdf.parsers.base import Layout, celdas, detectar_layout, normalizar, parse_monto

_LOG = logging.getLogger(__name__)
_CERO = Decimal("0.00")

_RE_MONTO = re.compile(r"^\$?-?[\d,]*\.\d{2}$")
_RE_CUENTA = re.compile(r"^\d{3,}(-\d+)*$")
_RE_FECHA = re.compile(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$")
_RE_UUID = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-", re.I)
_RE_RFC = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$", re.I)
_RE_TROZO_UUID = re.compile(r"^[0-9A-F-]{4,}$", re.I)

_ETIQUETA_TIPO = ("tipo de poliza", "tipo poliza")
_ETIQUETA_FECHA = ("fecha",)
_ETIQUETA_DESCRIPCION = ("descripcion",)
_ETIQUETA_FOLIO = ("folio",)
_MARCA_CFDI = ("cfdi",)
_MARCA_TOTALES = ("totales", "total poliza", "total")


@dataclass(frozen=True)
class Poliza:
    """Una poliza del libro diario.

    'poliza_id' NO identifica a la poliza: identifica su POSICION en esta
    lectura. Cambia si se procesa el documento completo o solo un rango de
    paginas, y no se puede comparar entre lecturas ni entre documentos.
    Sirve para unir las tres tablas de una misma corrida y para nada mas.
    La poliza se identifica de verdad por 'tipo', 'fecha' y
    'descripcion'/'folio', que son los campos que el contador reconoce.
    """

    poliza_id: str
    tipo: str
    naturaleza: str
    fecha: str
    descripcion: str
    folio: str
    total_debe: Decimal | None
    total_haber: Decimal | None
    # False cuando el bloque no llego a cerrar dentro de lo leido: se
    # corto en el borde del rango de paginas. Sus movimientos estan
    # incompletos y validarlos reportaria un descuadre que no existe.
    completa: bool = True


@dataclass(frozen=True)
class Movimiento:
    poliza_id: str
    orden: int
    cuenta: str
    nombre_cuenta: str
    debe: Decimal
    haber: Decimal


@dataclass(frozen=True)
class CFDI:
    poliza_id: str
    fecha: str
    documento: str
    uuid: str
    rfc: str
    tipo: str


@dataclass(frozen=True)
class LibroDiario:
    polizas: tuple[Poliza, ...]
    movimientos: tuple[Movimiento, ...]
    cfdi: tuple[CFDI, ...]
    forma: str = ""
    mapeo: Mapeo | None = None

    def __iter__(self) -> Iterator[Poliza]:
        return iter(self.polizas)


def _es_monto(texto: str) -> bool:
    t = texto.strip()
    return bool(t) and bool(_RE_MONTO.match(t))


def _montos(line: Line) -> list[str]:
    return [w.text for w in line.words if _es_monto(w.text)]


def _etiqueta(line: Line) -> str:
    """La etiqueta de un campo de bloque, si el renglon abre con una."""
    return normalizar(" ".join(w.text for w in line.words[:3])).rstrip(":")


def _empieza_con(texto: str, opciones: Sequence[str]) -> bool:
    return any(texto == o or texto.startswith(o + " ") for o in opciones)


def _valor_tras_etiqueta(line: Line, corte: float = 120.0) -> list[str]:
    """Lo que va a la derecha de la etiqueta del campo."""
    return [w.text for w in line.words if w.x0 >= corte]


def _texto_de_corrida_principal(line: Line, hasta: float) -> str:
    """El texto de la corrida mas a la izquierda, hasta cierta x.

    Cuando dos columnas se imprimen encima, ordenar por x las intercala.
    La corrida las separa: la de mas a la izquierda es la que empieza el
    renglon.
    """
    candidatas = [w for w in line.words if w.x0 < hasta]
    if not candidatas:
        return ""
    principal = min(candidatas, key=lambda w: (w.x0, w.run)).run
    palabras = [w for w in line.words if w.run == principal]
    if len(palabras) < 2:  # sin informacion de corrida: se usa todo
        palabras = candidatas
    return " ".join(w.text for w in sorted(palabras, key=lambda w: w.x0)
                    if not _es_monto(w.text) and not _RE_CUENTA.match(w.text))


class PolizasParser:
    """Convierte un Document de libro diario en polizas, movimientos y CFDI."""

    def __init__(self, paginas_muestra: int = 3) -> None:
        self.paginas_muestra = paginas_muestra

    # --- clasificacion ---------------------------------------------------
    def _abre_bloque_etiquetado(self, line: Line) -> tuple[str, str] | None:
        """'Tipo de poliza  Venta ( Ingreso )' -> (tipo, naturaleza)."""
        if not _empieza_con(_etiqueta(line), _ETIQUETA_TIPO):
            return None
        valores = _valor_tras_etiqueta(line)
        if not valores:
            return "", ""
        tipo = valores[0]
        naturaleza = " ".join(v for v in valores[1:] if v not in ("(", ")"))
        return tipo, naturaleza.strip()

    def _abre_bloque_por_nombre(self, line: Line, ancho_cuenta: float) -> str | None:
        """Un renglon de texto a la izquierda, con fecha y sin importes.

        Exigir la fecha es lo que lo distingue del encabezado de columnas,
        que tambien empieza a la izquierda y tampoco trae importes.
        """
        if not line.words or line.words[0].x0 > ancho_cuenta:
            return None
        if _RE_CUENTA.match(line.words[0].text) or _montos(line):
            return None
        if len(line.words) < 3:
            return None
        if not any(_RE_FECHA.match(w.text) for w in line.words):
            return None
        return _texto_de_corrida_principal(line, hasta=ancho_cuenta + 100)

    def _es_movimiento(self, line: Line) -> bool:
        # Un importe basta: hay formatos que imprimen cargo O abono, no los
        # dos, y exigir dos perdia todos sus movimientos.
        return (bool(line.words) and bool(_RE_CUENTA.match(line.words[0].text))
                and len(_montos(line)) >= 1)

    def _anclas(self, paginas: Sequence[Page]) -> tuple[float, float] | None:
        """Los dos bordes derechos donde caen los importes de un movimiento.

        Se miden sobre los propios renglones de movimiento: el encabezado
        de esas columnas no siempre esta donde se le pueda leer.
        """
        bordes: list[float] = []
        for page in paginas:
            for line in group(page.words):
                if not self._es_movimiento(line):
                    continue
                bordes.extend(w.x1 for w in line.words if _es_monto(w.text))
        if not bordes:
            return None
        grupos: list[list[float]] = []
        for x in sorted(bordes):
            if grupos and x - grupos[-1][-1] <= 4.0:
                grupos[-1].append(x)
            else:
                grupos.append([x])
        mejores = sorted(grupos, key=len, reverse=True)[:2]
        if len(mejores) < 2:
            return None
        anclas = sorted(sum(g) / len(g) for g in mejores)
        return anclas[0], anclas[1]

    def _debe_haber(self, line: Line,
                    anclas: tuple[float, float] | None) -> tuple[Decimal, Decimal]:
        montos = [w for w in line.words if _es_monto(w.text)]
        if anclas is None or len(montos) >= 2:
            return parse_monto(montos[-2].text), parse_monto(montos[-1].text)
        izquierda, derecha = anclas
        unico = montos[-1]
        if abs(unico.x1 - izquierda) <= abs(unico.x1 - derecha):
            return parse_monto(unico.text), _CERO
        return _CERO, parse_monto(unico.text)

    def _es_totales(self, line: Line) -> bool:
        return _empieza_con(_etiqueta(line), _MARCA_TOTALES) and bool(_montos(line))

    # --- lectura ---------------------------------------------------------
    def _leer(self, paginas: Sequence[Page], layout: Layout | None
              ) -> tuple[list[Poliza], list[Movimiento], list[CFDI]]:
        anclas = self._anclas(paginas)
        polizas: list[Poliza] = []
        movimientos: list[Movimiento] = []
        cfdis: list[CFDI] = []
        actual: dict | None = None
        orden = 0
        en_cfdi = False
        # Un movimiento cuyo nombre de cuenta se envuelve deja el numero de
        # cuenta en un renglon y los importes en otro. Se recuerda el
        # primero hasta que aparecen los importes; si no aparecen, se
        # descarta -- no se inventa un movimiento en cero.
        envuelto: dict | None = None

        def cerrar() -> None:
            nonlocal actual
            if actual is not None:
                polizas.append(Poliza(**actual))
                actual = None

        def nuevo(**campos) -> None:
            nonlocal actual, orden, en_cfdi, envuelto
            cerrar()
            orden = 0
            en_cfdi = False
            envuelto = None
            base = dict(poliza_id=f"P{len(polizas) + 1:05d}", tipo="",
                        naturaleza="", fecha="", descripcion="", folio="",
                        total_debe=None, total_haber=None, completa=False)
            base.update(campos)
            actual = base

        for page in paginas:
            for line in group(page.words):
                etiqueta = _etiqueta(line)

                etiquetado = self._abre_bloque_etiquetado(line)
                if etiquetado is not None:
                    nuevo(tipo=etiquetado[0], naturaleza=etiquetado[1])
                    continue

                if actual is not None and not en_cfdi:
                    if _empieza_con(etiqueta, _ETIQUETA_FECHA) and not en_cfdi:
                        valores = _valor_tras_etiqueta(line)
                        if valores and _RE_FECHA.match(valores[0]):
                            actual["fecha"] = valores[0]
                            continue
                    if _empieza_con(etiqueta, _ETIQUETA_DESCRIPCION):
                        actual["descripcion"] = " ".join(_valor_tras_etiqueta(line))
                        continue
                    if _empieza_con(etiqueta, _ETIQUETA_FOLIO):
                        valores = [v for v in _valor_tras_etiqueta(line)
                                   if not _empieza_con(normalizar(v), ("cuenta",))]
                        continue

                if _empieza_con(etiqueta, _MARCA_CFDI):
                    en_cfdi = True
                    continue

                if self._es_totales(line):
                    envuelto = None
                    montos = _montos(line)
                    if actual is not None and len(montos) >= 2:
                        # No se cierra aqui: la tabla de CFDI de la poliza
                        # viene DESPUES de sus totales.
                        actual["total_debe"] = parse_monto(montos[0])
                        actual["total_haber"] = parse_monto(montos[1])
                        actual["completa"] = True
                    continue

                if self._es_movimiento(line):
                    envuelto = None
                    if actual is None:
                        continue
                    orden += 1
                    debe, haber = self._debe_haber(line, anclas)
                    nombre = _texto_de_corrida_principal(line, hasta=line.words[0].x1 + 5)
                    movimientos.append(Movimiento(
                        poliza_id=actual["poliza_id"], orden=orden,
                        cuenta=line.words[0].text, nombre_cuenta=nombre.strip(),
                        debe=debe, haber=haber))
                    continue

                # Renglon que abre con numero de cuenta pero sin importes:
                # el nombre de la cuenta se envolvio y los importes vienen
                # en uno de los renglones siguientes.
                if (actual is not None and not en_cfdi and line.words
                        and _RE_CUENTA.match(line.words[0].text)
                        and not _montos(line)):
                    envuelto = {
                        "cuenta": line.words[0].text,
                        "nombre": _texto_de_corrida_principal(
                            line, hasta=line.words[0].x1 + 5).strip(),
                    }
                    continue

                if envuelto is not None and not en_cfdi:
                    montos = _montos(line)
                    cola = " ".join(w.text for w in line.words
                                    if not _es_monto(w.text)).strip()
                    if not montos:
                        # Sigue siendo nombre: se acumula y se espera.
                        if cola:
                            envuelto["nombre"] = f"{envuelto['nombre']} {cola}".strip()
                        continue
                    orden += 1
                    debe, haber = self._debe_haber(line, anclas)
                    movimientos.append(Movimiento(
                        poliza_id=actual["poliza_id"], orden=orden,
                        cuenta=envuelto["cuenta"],
                        nombre_cuenta=f"{envuelto['nombre']} {cola}".strip(),
                        debe=debe, haber=haber))
                    envuelto = None
                    continue

                nombre = (None if en_cfdi
                          else self._abre_bloque_por_nombre(line, ancho_cuenta=25.0))
                if nombre is not None:
                    fecha = next((w.text for w in line.words
                                  if _RE_FECHA.match(w.text)), "")
                    nuevo(descripcion=nombre, fecha=fecha)
                    continue

                if en_cfdi and actual is not None:
                    fila = self._cfdi(line, actual["poliza_id"], cfdis)
                    if fila is not None:
                        cfdis.append(fila)

        cerrar()
        return polizas, movimientos, cfdis

    def _cfdi(self, line: Line, poliza_id: str,
              previos: list[CFDI]) -> CFDI | None:
        """Un renglon de la tabla de CFDI, o la cola del UUID anterior."""
        textos = [w.text for w in line.words]
        if not textos:
            return None

        if _RE_FECHA.match(textos[0]):
            uuid = next((t for t in textos if _RE_UUID.match(t)), "")
            rfc = next((t for t in textos if _RE_RFC.match(t)), "")
            resto = [t for t in textos[1:] if t not in (uuid, rfc)]
            # Sin folio fiscal no hay numero de documento que leer: la fila
            # es una poliza manual ('fecha | Diario | (Manual)') y tomar
            # 'resto[0]' inventaba un documento con el texto que hubiera.
            # Medido: los 101 CFDI sin UUID del fixture son exactamente los
            # que salian con documento='Diario'.
            documento = resto[0] if (resto and uuid) else ""
            return CFDI(poliza_id=poliza_id, fecha=textos[0],
                        documento=documento, uuid=uuid,
                        rfc=rfc, tipo=resto[-1] if len(resto) > 1 else "")

        # El UUID se parte en dos renglones: la cola no abre fila nueva.
        if previos and len(textos) == 1 and _RE_TROZO_UUID.match(textos[0]):
            previos[-1] = replace(previos[-1],
                                  uuid=f"{previos[-1].uuid}{textos[0]}")
        return None

    # --- verificacion ----------------------------------------------------
    def verifica(self, polizas: Sequence[Poliza],
                 movimientos: Sequence[Movimiento], *, minimo: int = 2) -> bool:
        """True si las polizas leidas cuadran debe contra haber."""
        if len(polizas) < minimo or not movimientos:
            return False
        por_poliza: dict[str, list[Movimiento]] = {}
        for m in movimientos:
            por_poliza.setdefault(m.poliza_id, []).append(m)
        buenas = 0
        for p in polizas:
            grupo = por_poliza.get(p.poliza_id, [])
            if not grupo:
                continue
            if sum(m.debe for m in grupo) == sum(m.haber for m in grupo):
                buenas += 1
        return buenas >= len(por_poliza) * 0.9

    # --- API --------------------------------------------------------------
    def parse(self, document: Document, *, layout: Layout | None = None,
              mapeo: "dict[str, int] | Mapeo | None" = None) -> LibroDiario:
        paginas = list(document.open_pages())
        if not paginas:
            raise LayoutDesconocido("el documento no trajo paginas")
        layout = layout or detectar_layout(paginas[:self.paginas_muestra])

        polizas, movimientos, cfdis = self._leer(paginas, layout)
        if not polizas:
            raise LayoutDesconocido("no se encontro ninguna poliza")

        conocido = mapeo if isinstance(mapeo, Mapeo) else None
        cuadra = self.verifica(polizas, movimientos)
        descripcion = conocido or Mapeo(
            campos={}, forma="bloques" if any(p.tipo for p in polizas) else "diario",
            verificado_por="aritmetica" if cuadra else "vocabulario",
            orientacion_verificada=cuadra, filas_afectadas=0)
        return LibroDiario(polizas=tuple(polizas), movimientos=tuple(movimientos),
                           cfdi=tuple(cfdis), forma=descripcion.forma,
                           mapeo=descripcion)
