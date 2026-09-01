"""Parser de estado de cuenta bancario.

El documento mas desordenado de los siete. La primera pagina suele ser
puro metadato -- encabezado, domicilio, sello digital, resumen de
comisiones -- y la tabla real empieza mas abajo o en la pagina siguiente.
Un envio SPEI ocupa nueve renglones visuales, asi que la regla de fila
nueva es la del auxiliar: el renglon trae la FECHA en su columna, y todo
lo que sigue sin fecha continua al anterior.

Lo que generaliza a nueve bancos no es una rama por banco, son tres cosas:

1. El ENCABEZADO manda. Los campos se reconocen por el vocabulario de la
   fila de encabezado (`_CAMPOS_TABLA`) y los importes se colocan contra
   el BORDE DERECHO de esa etiqueta. Medido: los importes se alinean a la
   derecha con su encabezado en los seis formatos, con desviaciones de 0 a
   30pt, siempre menores que media separacion entre columnas. Tomar "las
   tres columnas mas a la derecha" en cambio mete el retiro en la casilla
   del deposito en cuanto el documento imprime el simbolo de moneda como
   columna propia.
2. Un encabezado AGRUPADO (una etiqueta arriba que abarca dos subcolumnas)
   se resuelve consultando el renglon de arriba solo cuando la subetiqueta
   no significa nada por si sola.
3. Las CUENTAS son secciones. Un estado puede traer varias cuentas; cada
   bloque de movimientos va precedido del nombre del producto o del numero
   de cuenta, y el movimiento pertenece a la seccion que lo contiene.

Los saldos del resumen son propiedad de la CUENTA, no del documento. Un
estado de una sola cuenta queda con `cuentas` de longitud 1, sin caso
especial.

LIMITE CONOCIDO -- la union de continuaciones. Hay documentos que envuelven
partiendo palabras a la mitad ('CON' + 'CEPTO:') y otros que envuelven por
palabra entera ('CVE' + 'RASTREO:'). La geometria NO los distingue: en los
dos casos el ultimo token llega al margen y el siguiente arranca en el
borde izquierdo de la columna. Por eso `separador_continuacion` es un
parametro del formato y no una deduccion; su valor por omision es el
medido en el primer formato de la fase 7.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal

from contapdf.ir import ColumnSpec, Document, Line, Page, Word
from contapdf.layout.lines import group
from contapdf.parsers.balanza import LayoutDesconocido, Mapeo
from contapdf.parsers.base import Layout, normalizar, parse_monto

_LOG = logging.getLogger(__name__)
_CERO = Decimal("0.00")

# El signo puede ir delante o detras: la reversa de un cargo se imprime
# como "287,000.00-" en la misma columna del cargo.
_RE_MONTO = re.compile(r"^\$?-?[\d,]*\.\d{2}-?$")
_RE_SOLO_NUMERO = re.compile(r"^[\d.,]+$")
# Simbolo de moneda y signo sueltos, que van en su propio token:
# '-$' delante de un saldo es la unica marca de que es negativo.
_RE_SIGNO = re.compile(r"^-?\$$|^-$")
_RE_CLABE = re.compile(r"^\d{18}$")
_RE_RFC = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")
_RE_FECHA_LARGA = re.compile(r"\d{1,2}\s+[A-ZÁÉÍÓÚ]{3}\s+\d{4}")
_RE_ANIO = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")
# Un numero de cuenta impreso: digitos, con o sin guiones. Excluye la CLABE,
# que son 18 digitos exactos y se reconoce aparte.
_RE_NUM_CUENTA = re.compile(r"^\d[\d-]{6,}\d$")

# Un hueco mayor que esto separa dos etiquetas de encabezado. Medido: dentro
# de una etiqueta de varias palabras los huecos van de 1 a 3pt, y entre dos
# etiquetas vecinas el mas estrecho es de 11pt.
_HUECO_ETIQUETA = 8.0
# Cuanto puede desbordar un valor la etiqueta de su columna de texto.
_MARGEN_REFERENCIA_IZQ = 30.0
_MARGEN_REFERENCIA_DER = 6.0
# Hueco vertical maximo entre un renglon de la tabla y su continuacion.
# Medido: dentro de la tabla van de 2 a 4pt en los seis formatos, y el pie
# de pagina cae a 19pt o mas del ultimo renglon.
_SALTO = 12.0

_MESES = (("ENE", "01"), ("FEB", "02"), ("MAR", "03"), ("ABR", "04"),
          ("MAY", "05"), ("JUN", "06"), ("JUL", "07"), ("AGO", "08"),
          ("SEP", "09"), ("OCT", "10"), ("NOV", "11"), ("DIC", "12"))

# --- Vocabularios -------------------------------------------------------
# Encabezado de la tabla de movimientos. El orden es la PRIORIDAD: la
# subetiqueta 'operacion' de un saldo agrupado tambien aparece dentro de
# 'descripcion de la operacion', y gana quien este antes en esta lista.
_CAMPOS_TABLA = (
    ("saldo", ("saldo",)),
    ("deposito", ("deposito", "abono")),
    ("retiro", ("retiro", "cargo")),
    ("fecha", ("fecha", "dia")),
    ("referencia", ("referencia", "folio", "docto")),
    ("descripcion", ("descripcion", "concepto", "establecimiento")),
)

# Encabezado del resumen que lista las cuentas del documento.
_CAMPOS_CUENTAS = (
    ("saldo_inicial", ("saldo anterior", "mes anterior", "saldo inicial")),
    ("saldo_corte", ("saldo al corte", "mes actual", "saldo actual",
                     "saldo final")),
    ("clabe", ("clabe",)),
    ("num_cuenta", ("no de cuenta", "numero de cuenta", "num de cuenta",
                    "cuenta")),
    ("producto", ("producto", "instrumento")),
)

# Etiquetas de saldo tal como las imprimen los nueve bancos. Se comparan
# contra la etiqueta SIN espacios ni puntuacion porque hay documentos que
# entregan 'Saldoinicial' pegado, y por el FINAL de la etiqueta porque el
# renglon puede traer otra pareja etiqueta-valor antes.
# 'depsitos' no es un error: ese PDF no trae los acentos en su codificacion.
_CAMPOS_RESUMEN = (
    ("saldo_inicial", ("saldoinicial", "saldoanterior", "balanceinicial",
                       "saldoinicialdelperiodo", "saldoinicialdel",
                       "saldodeliquidacioninicial", "saldodeoperacioninicial",
                       "saldofinaldelperiodoanterior")),
    ("saldo_corte", ("saldoalcorte", "saldofinal", "saldoactual",
                     "saldofinaldel", "saldofinaldelacuenta", "saldototal")),
    ("depositos", ("depositos", "deposito", "depsitos", "abonos", "abono",
                   "totalabonos", "totaldedepositos", "depositosabonos")),
    ("retiros", ("retiros", "retiro", "cargos", "cargo", "totalcargos",
                 "totalderetiros", "retiroscargos")),
)
_SALDOS = ("saldo_inicial", "depositos", "retiros", "saldo_corte")
# Campos que llevan importe: son los que se alinean a la derecha y los
# unicos que se colocan por borde derecho.
_MONTOS = ("deposito", "retiro", "saldo", "saldo_inicial", "saldo_corte")
# Del mas largo al mas corto: 'saldo final del periodo anterior' es un saldo
# INICIAL, y si ganara 'saldo final' quedaria del lado equivocado.
_RESUMEN_POR_LARGO = tuple(sorted(
    ((s, campo) for campo, sinonimos in _CAMPOS_RESUMEN for s in sinonimos),
    key=lambda par: -len(par[0])))

# Renglones que el documento imprime dentro de la tabla pero que no son
# movimientos: son el saldo de arranque de la seccion.
_APERTURA = ("saldoanterior", "saldoinicial", "balanceinicial",
             "saldofinaldelperiodoanterior")

# Formatos de fecha medidos, cada uno en un banco distinto. El primer grupo
# es el dia salvo donde el documento imprime el mes primero.
_FECHAS = (
    (re.compile(r"^(\d{1,2})$"), "d"),
    (re.compile(r"^(\d{1,2})[-/ ]([A-ZÁÉÍÓÚ]{3})\.?[-/ ](\d{2,4})$"), "dmy"),
    (re.compile(r"^(\d{1,2})[-/ ]([A-ZÁÉÍÓÚ]{3})\.?$"), "dm"),
    (re.compile(r"^([A-ZÁÉÍÓÚ]{3})\.?[-/ ](\d{1,2})$"), "md"),
)


@dataclass(frozen=True)
class MetaEstadoCuenta:
    """Lo que es del DOCUMENTO, no de ninguna de sus cuentas."""

    banco: str = ""
    rfc: str = ""
    periodo_ini: str = ""
    periodo_fin: str = ""
    anio: str = ""
    # La fila TOTAL del resumen de cuentas, cuando el documento la imprime.
    total_saldo_inicial: Decimal | None = None
    total_saldo_corte: Decimal | None = None


@dataclass(frozen=True)
class CuentaBancaria:
    num_cuenta: str = ""
    clabe: str = ""
    producto: str = ""
    moneda: str = ""
    saldo_inicial: Decimal | None = None
    depositos: Decimal | None = None
    retiros: Decimal | None = None
    saldo_corte: Decimal | None = None


@dataclass(frozen=True)
class MovimientoBancario:
    num_cuenta: str
    dia: str
    fecha: str
    descripcion: str
    referencia: str
    deposito: Decimal
    retiro: Decimal
    saldo: Decimal | None
    pagina: int = 0


@dataclass(frozen=True)
class TipoDeReporte:
    """QUE es el documento cuando no es una tabla de movimientos.

    'layout desconocido' hace que la capa web muestre un error cuando el
    usuario en realidad subio otro tipo de reporte. Esto dice cual, con la
    evidencia del propio documento y con lo que si se pudo leer.
    """

    clave: str
    etiqueta: str
    evidencia: tuple[str, ...] = ()
    cuentas: tuple[CuentaBancaria, ...] = ()


class ReporteNoEsperado(LayoutDesconocido):
    """No hay tabla de movimientos, y se sabe por que.

    Sigue siendo un LayoutDesconocido: quien ya lo atrapaba no se entera.
    """

    def __init__(self, tipo: TipoDeReporte) -> None:
        super().__init__(tipo.etiqueta)
        self.tipo = tipo


@dataclass(frozen=True)
class EstadoCuenta:
    meta: MetaEstadoCuenta
    cuentas: tuple[CuentaBancaria, ...]
    movimientos: tuple[MovimientoBancario, ...]
    mapeo: Mapeo | None = None

    def __iter__(self) -> Iterator[MovimientoBancario]:
        return iter(self.movimientos)

    def cuenta(self, num_cuenta: str) -> CuentaBancaria | None:
        return next((c for c in self.cuentas if c.num_cuenta == num_cuenta), None)

    def movimientos_de(self, num_cuenta: str) -> tuple[MovimientoBancario, ...]:
        return tuple(m for m in self.movimientos if m.num_cuenta == num_cuenta)


# --- Utilidades de texto -------------------------------------------------
def _es_monto(texto: str) -> bool:
    t = texto.strip()
    return bool(t) and bool(_RE_MONTO.match(t))


def _clave(texto: str) -> str:
    """La etiqueta sin espacios, acentos ni puntuacion."""
    return normalizar(texto).replace(" ", "")


def _campo_de(texto: str, vocabulario: Sequence[tuple[str, tuple[str, ...]]]
              ) -> str | None:
    """El campo cuyo vocabulario aparece en la etiqueta, por prioridad."""
    plano = normalizar(texto)
    # Tambien sin espacios: hay un encabezado que imprime 'F E C H A' letra
    # por letra, y otro que entrega 'Saldoinicial' de una pieza.
    apretado = plano.replace(" ", "")
    for campo, sinonimos in vocabulario:
        if any(s in plano or s.replace(" ", "") in apretado for s in sinonimos):
            return campo
    return None


def _campo_de_saldo(etiqueta: str) -> str | None:
    """El campo de saldo que nombra el FINAL de la etiqueta, si alguno."""
    clave = _clave(etiqueta)
    if not clave:
        return None
    return next((campo for sinonimo, campo in _RESUMEN_POR_LARGO
                 if clave.endswith(sinonimo)), None)


# --- Encabezados ---------------------------------------------------------
@dataclass(frozen=True)
class _Etiqueta:
    texto: str
    x_min: float
    x_max: float


def _etiquetas(line: Line) -> list[_Etiqueta]:
    """Parte el renglon en etiquetas: palabras separadas por huecos chicos."""
    palabras = sorted(line.words, key=lambda w: w.x0)
    etiquetas: list[_Etiqueta] = []
    actual: list[Word] = []
    for word in palabras:
        if actual and word.x0 - actual[-1].x1 > _HUECO_ETIQUETA:
            etiquetas.append(_junta(actual))
            actual = []
        actual.append(word)
    if actual:
        etiquetas.append(_junta(actual))
    return etiquetas


def _junta(palabras: Sequence[Word]) -> _Etiqueta:
    return _Etiqueta(texto=" ".join(w.text for w in palabras),
                     x_min=min(w.x0 for w in palabras),
                     x_max=max(w.x1 for w in palabras))


def _columnas_de(line: Line, arriba: Line | None,
                 vocabulario: Sequence[tuple[str, tuple[str, ...]]]
                 ) -> tuple[tuple[ColumnSpec, ...], dict[int, str]]:
    """Columnas y campos que declara una fila de encabezado.

    Cuando una subetiqueta no significa nada por si sola se consulta la de
    ARRIBA que la traslapa: es lo que resuelve un encabezado agrupado, donde
    'SALDO' abarca 'OPERACION' y 'LIQUIDACION' desde el renglon anterior.
    """
    columnas: list[ColumnSpec] = []
    campos: dict[int, str] = {}
    for etiqueta in _etiquetas(line):
        campo = _campo_de(etiqueta.texto, vocabulario)
        texto = etiqueta.texto
        if campo is None and arriba is not None:
            campo, texto = _campo_heredado(etiqueta, arriba, vocabulario)
        if campo is None:
            continue
        indice = len(columnas)
        columnas.append(ColumnSpec(
            index=indice, align="right" if campo in _MONTOS else "left",
            x_min=etiqueta.x_min, x_max=etiqueta.x_max, support=1, header=texto))
        campos[indice] = campo
    return tuple(columnas), campos


def _campo_heredado(etiqueta: _Etiqueta, arriba: Line,
                    vocabulario: Sequence[tuple[str, tuple[str, ...]]]
                    ) -> tuple[str | None, str]:
    """El campo que le presta la etiqueta de arriba que la traslapa."""
    for otra in _etiquetas(arriba):
        if not _traslapan(otra, etiqueta):
            continue
        campo = _campo_de(otra.texto, vocabulario)
        if campo is not None:
            return campo, f"{otra.texto} {etiqueta.texto}"
    return None, etiqueta.texto


def _traslapan(a: _Etiqueta, b: _Etiqueta) -> bool:
    return not (a.x_max < b.x_min or b.x_max < a.x_min)


def _sirve_de_tabla(campos: dict[int, str]) -> bool:
    """Un encabezado de movimientos trae fecha, saldo y un importe."""
    presentes = set(campos.values())
    return ("fecha" in presentes and "saldo" in presentes
            and bool(presentes & {"deposito", "retiro"}))


def _sirve_de_cuentas(campos: dict[int, str]) -> bool:
    """Un resumen de cuentas identifica la cuenta y trae al menos un saldo."""
    presentes = set(campos.values())
    return (len(presentes) >= 3 and bool(presentes & {"producto", "num_cuenta"})
            and bool(presentes & {"saldo_inicial", "saldo_corte"}))


def detectar_cabecera(paginas: Sequence[Page]) -> Layout | None:
    """El layout de la tabla de movimientos, leido de su fila de encabezado.

    Devuelve None cuando ninguna pagina trae una: eso no es un error, es un
    documento de otro tipo.
    """
    for page in paginas:
        lineas = group(page.words)
        for indice, line in enumerate(lineas):
            if any(_es_monto(w.text) for w in line.words):
                continue
            arriba = lineas[indice - 1] if indice else None
            columnas, campos = _columnas_de(line, arriba, _CAMPOS_TABLA)
            if _sirve_de_tabla(campos):
                return Layout(columns=columnas, texto_en_montos=False)
    return None


def _campos_de(layout: Layout) -> dict[int, str]:
    """Reconstruye campo por columna a partir de los encabezados guardados.

    Permite aplicar un layout que venga de una plantilla, que solo guarda
    las columnas y sus etiquetas.
    """
    campos: dict[int, str] = {}
    for columna in layout.columns:
        campo = _campo_de(columna.header, _CAMPOS_TABLA)
        if campo is not None:
            campos[columna.index] = campo
    return campos


# --- Fechas --------------------------------------------------------------
def _mes_de(abreviatura: str) -> str:
    plano = normalizar(abreviatura).upper()[:3]
    return next((n for a, n in _MESES if a == plano), "")


def _anio_de(periodo: str) -> str:
    partes = periodo.split()
    return partes[2] if len(partes) == 3 else ""


def _completa_anio(crudo: str, declarado: str) -> str:
    """Un anio de dos digitos se resuelve contra el siglo que declara el periodo."""
    if len(crudo) == 4:
        return crudo
    siglo = declarado[:2] if len(declarado) == 4 else "20"
    return f"{siglo}{crudo.zfill(2)}"


def _fecha_de(texto: str, meta: "MetaEstadoCuenta"
              ) -> tuple[str, str] | None:
    """(dia, dd/mm/aaaa) a partir de lo que el renglon imprime en su columna.

    Cuando el documento solo imprime el dia, el mes y el anio salen del
    periodo que el propio documento declara -- y solo si no cruza de mes:
    si lo cruzara, el dia solo no dice a cual pertenece y se deja vacio en
    vez de adivinar.
    """
    limpio = " ".join(texto.split()).upper()
    periodo_ini, periodo_fin = meta.periodo_ini, meta.periodo_fin
    declarado = meta.anio or _anio_de(periodo_ini)
    for patron, forma in _FECHAS:
        encontrado = patron.match(limpio)
        if encontrado is None:
            continue
        if forma == "d":
            dia = encontrado.group(1)
            return dia, _del_periodo(dia, periodo_ini, periodo_fin)
        if forma == "md":
            mes, dia = _mes_de(encontrado.group(1)), encontrado.group(2)
        else:
            dia, mes = encontrado.group(1), _mes_de(encontrado.group(2))
        if not mes:
            return None
        anio = (_completa_anio(encontrado.group(3), declarado)
                if forma == "dmy" else declarado)
        return dia, (f"{int(dia):02d}/{mes}/{anio}" if anio else "")
    return None


def _del_periodo(dia: str, periodo_ini: str, periodo_fin: str) -> str:
    partes_ini, partes_fin = periodo_ini.split(), periodo_fin.split()
    if len(partes_ini) != 3 or len(partes_fin) != 3:
        return ""
    if partes_ini[1:] != partes_fin[1:]:
        return ""
    mes = _mes_de(partes_ini[1])
    return f"{int(dia):02d}/{mes}/{partes_ini[2]}" if mes else ""


# --- Parser --------------------------------------------------------------
@dataclass
class _Lectura:
    """Lo que se va juntando en la unica pasada por el documento."""

    saldos: dict = field(default_factory=dict)
    filas: list = field(default_factory=list)
    total: dict = field(default_factory=dict)
    identificadores: dict = field(default_factory=dict)
    evidencia: list = field(default_factory=list)


class EstadoCuentaParser:
    """Convierte un Document de estado de cuenta en cuentas + movimientos."""

    def __init__(self, paginas_muestra: int = 2, *,
                 separador_continuacion: str = "") -> None:
        self.paginas_muestra = paginas_muestra
        self.separador_continuacion = separador_continuacion

    # --- identificacion del documento ---------------------------------
    def _identificacion(self, lineas_por_pagina: Sequence[list[Line]]) -> _Lectura:
        lectura = _Lectura()
        for lineas in lineas_por_pagina:
            cabecera: tuple[tuple[ColumnSpec, ...], dict[int, str]] | None = None
            for indice, line in enumerate(lineas):
                if not line.words:
                    continue
                self._banco(line, lectura.identificadores)
                self._identificadores(line, lectura.identificadores)
                self._periodo(line, lectura.identificadores)
                self._moneda(line, lectura.identificadores)
                arriba = lineas[indice - 1] if indice else None
                cabecera = self._resumen(line, arriba, lineas, indice,
                                         cabecera, lectura)
        return lectura

    def _resumen(self, line, arriba, lineas, indice, cabecera, lectura):
        """Las tres formas en que un banco imprime sus saldos.

        Tabla de cuentas (una fila por cuenta y a veces una fila TOTAL),
        tabla horizontal (etiquetas en un renglon, importes en el
        siguiente) y etiqueta-valor dentro del renglon.
        """
        hay_montos = any(_es_monto(w.text) for w in line.words)
        if not hay_montos:
            columnas, campos = _columnas_de(line, arriba, _CAMPOS_CUENTAS)
            if _sirve_de_cuentas(campos):
                return (columnas, campos)
            self._horizontal(line, lineas, indice, lectura)
            return cabecera
        if cabecera is not None:
            estado = self._fila_de_cuenta(line, cabecera, lectura)
            if estado == "fila":
                return cabecera
            # Un TOTAL cierra la tabla, y un renglon con importes que no cae
            # en ninguna columna de saldo dice que la tabla ya termino: sin
            # esto el resumen del periodo que viene despues se leeria como
            # una cuenta mas.
            if estado == "total":
                return None
            cabecera = None
        self._etiqueta_valor(line, lectura)
        return cabecera

    def _fila_de_cuenta(self, line: Line, cabecera, lectura: _Lectura) -> str:
        """Una fila del resumen de cuentas, o la fila TOTAL que las suma."""
        columnas, campos = cabecera
        celdas = _celdas_de_cuenta(line, Layout(columns=columnas), campos)
        saldos = {c: parse_monto(celdas[c][0].text)
                  for c in ("saldo_inicial", "saldo_corte") if celdas.get(c)}
        if not saldos:
            return "no"
        etiqueta = " ".join(w.text for w in line.words if not _es_monto(w.text))
        if _clave(etiqueta).startswith("total"):
            lectura.total.update(saldos)
            return "total"
        # El nombre del producto desborda su columna hasta invadir la vecina,
        # asi que lo que separa nombre de numero no es donde cayo el token
        # sino su forma: el nombre es la corrida de palabras con letras que
        # abre la fila, y el numero el primer token que ya no las tiene.
        palabras = [w.text for w in celdas.get("producto", ())]
        palabras += [w.text for w in celdas.get("num_cuenta", ())]
        nombre: list[str] = []
        for texto in palabras:
            if not any(c.isalpha() for c in texto):
                break
            nombre.append(texto)
        producto = " ".join(nombre)
        numeros = [t for t in palabras if _RE_NUM_CUENTA.match(t)
                   and not _RE_CLABE.match(t)]
        clabe = "".join(w.text for w in celdas.get("clabe", ()))
        lectura.filas.append(CuentaBancaria(
            num_cuenta=numeros[-1] if numeros else "",
            clabe=clabe if _RE_CLABE.match(clabe) else "",
            producto=producto.strip(), **saldos))
        return "fila"

    def _horizontal(self, line: Line, lineas: Sequence[Line], indice: int,
                    lectura: _Lectura) -> None:
        """Etiquetas de saldo en un renglon y sus importes en el siguiente."""
        etiquetas = _etiquetas(line)
        campos = [(_campo_de_saldo(e.texto), e) for e in etiquetas]
        nombrados = [(c, e) for c, e in campos if c is not None]
        if len(nombrados) < 3 or indice + 1 >= len(lineas):
            return
        montos = [w for w in lineas[indice + 1].words if _es_monto(w.text)]
        if len(montos) < 3:
            return
        for campo, etiqueta in nombrados:
            cercano = min(montos, key=lambda w: abs(w.x1 - etiqueta.x_max))
            if abs(cercano.x1 - etiqueta.x_max) < 60.0:
                lectura.saldos.setdefault(campo, parse_monto(cercano.text))
                lectura.evidencia.append(f"{etiqueta.texto} {cercano.text}")

    def _etiqueta_valor(self, line: Line, lectura: _Lectura) -> None:
        """Cada importe del renglon se queda con la etiqueta que lo precede.

        Por segmentos y no por el inicio del renglon: hay resumenes a dos
        columnas donde el mismo renglon trae 'Saldo promedio 351,153.25' y
        'Saldo inicial 181,609.21'.
        """
        etiqueta: list[str] = []
        for word in sorted(line.words, key=lambda w: w.x0):
            if _es_monto(word.text):
                campo = _campo_de_saldo(" ".join(etiqueta))
                if campo is not None and campo not in lectura.saldos:
                    lectura.saldos[campo] = parse_monto(word.text)
                    lectura.evidencia.append(
                        f"{' '.join(etiqueta)} {word.text}".strip())
                etiqueta = []
            elif not _RE_SOLO_NUMERO.match(word.text.strip()):
                # Un numero suelto es un contador ('Abonos (+) 53'), no
                # parte de la etiqueta.
                etiqueta.append(word.text)

    def _banco(self, line: Line, campos: dict) -> None:
        """El nombre de la institucion se imprime ENCIMA del domicilio.

        Sin separar por corrida salen entrelazados; con ella, la corrida
        que la nombra es una sola.
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
        if "cuenta" in plano.split() and "num_cuenta" not in campos:
            # El ULTIMO candidato del renglon, no el que sigue a la etiqueta:
            # hay documentos que imprimen 'CUENTA CUENTA CONECTA <banco> N'.
            candidatos = [t.strip() for t in textos
                          if _RE_NUM_CUENTA.match(t.strip())
                          and not _RE_CLABE.match(t.strip())]
            if candidatos:
                campos["num_cuenta"] = candidatos[-1]

    def _periodo(self, line: Line, campos: dict) -> None:
        """El periodo declarado, y por separado el anio.

        Cada banco escribe el periodo distinto ('01 ABR 2025', '01/12/2022',
        '1 DE SEPTIEMBRE AL 30 DE SEPTIEMBRE DE 2022'). Solo hace falta
        entenderlo entero cuando el documento imprime unicamente el dia del
        movimiento; para los demas alcanza con el anio, y ese si esta
        siempre.
        """
        texto = " ".join(w.text for w in line.words)
        if "periodo" not in normalizar(texto):
            return
        if "anio" not in campos:
            anio = _RE_ANIO.search(texto)
            if anio is not None:
                campos["anio"] = anio.group(0)
        if "periodo_ini" in campos:
            return
        fechas = _RE_FECHA_LARGA.findall(texto)
        if len(fechas) >= 2:
            campos["periodo_ini"], campos["periodo_fin"] = fechas[0], fechas[1]

    def _moneda(self, line: Line, campos: dict) -> None:
        if "moneda" in campos:
            return
        palabras = [w.text for w in sorted(line.words, key=lambda w: w.x0)]
        for i, texto in enumerate(palabras):
            if normalizar(texto) != "moneda":
                continue
            resto = [t for t in palabras[i + 1:i + 3]
                     if t.isalpha() and len(t) > 2]
            if resto:
                campos["moneda"] = " ".join(resto)
            return

    # --- cuentas -------------------------------------------------------
    def _cuentas(self, lectura: _Lectura) -> tuple[CuentaBancaria, ...]:
        """Las cuentas del documento, con sus saldos donde los haya.

        Con dos o mas cuentas los totales de deposito y retiro se quedan en
        None salvo que el documento los desglose por cuenta: repartir el
        total del documento entre las cuentas seria inventarlo.
        """
        ident = lectura.identificadores
        if len(lectura.filas) > 1:
            return tuple(lectura.filas)
        base = lectura.filas[0] if lectura.filas else CuentaBancaria()
        # Con 'or' un saldo de 0.00 se leeria como ausente: es un valor, no
        # un vacio, y es justo el de las cuentas sin movimientos.
        saldos = {c: (getattr(base, c) if getattr(base, c) is not None
                      else lectura.saldos.get(c))
                  for c in _SALDOS}
        return (replace(base,
                        num_cuenta=base.num_cuenta or ident.get("num_cuenta", ""),
                        clabe=base.clabe or ident.get("clabe", ""),
                        moneda=ident.get("moneda", ""), **saldos),)

    # --- movimientos ---------------------------------------------------
    def _movimientos(self, paginas: Sequence[Page],
                     lineas_por_pagina: Sequence[list[Line]], layout: Layout,
                     campos: dict[int, str], meta: MetaEstadoCuenta,
                     cuentas: Sequence[CuentaBancaria]
                     ) -> list[MovimientoBancario]:
        """Recorre el documento una vez y arma los movimientos.

        La tabla NO se acota con find_table_region: en estos documentos deja
        paginas enteras fuera. Se acota con lo que el propio documento
        garantiza -- los seis formatos medidos REIMPRIMEN el encabezado en
        cada pagina de tabla -- asi que solo hay movimientos debajo de un
        encabezado, y una continuacion tiene que venir pegada al renglon
        anterior. Eso es lo que deja fuera el pie de pagina, que en todos
        ellos cae a mas de 19pt del ultimo renglon.
        """
        movimientos: list[MovimientoBancario] = []
        actual = cuentas[0].num_cuenta if cuentas else ""
        secciones = _secciones(cuentas)

        for page, lineas in zip(paginas, lineas_por_pagina):
            anterior: Line | None = None
            for indice, line in enumerate(lineas):
                if not line.words:
                    continue
                seccion = _seccion_de(line, secciones)
                if seccion is not None:
                    actual, anterior = seccion, line
                    continue
                arriba = lineas[indice - 1] if indice else None
                propio = self._cabecera_de_seccion(line, arriba)
                if propio is not None:
                    layout, campos = propio
                    anterior = line
                    continue
                if anterior is None:
                    continue
                fila = self._fila(line, layout, campos, meta, actual, page.number)
                if fila is not None:
                    movimientos.append(fila)
                    anterior = line
                elif movimientos and line.top - anterior.bottom <= _SALTO:
                    cola = " ".join(w.text for w in _junta_signos(line.words)
                                    if not _es_monto(w.text))
                    if cola:
                        movimientos[-1] = replace(
                            movimientos[-1],
                            descripcion=(movimientos[-1].descripcion
                                         + self.separador_continuacion + cola))
                    anterior = line
        return [m for m in movimientos if not _es_apertura(m)]

    def _cabecera_de_seccion(self, line: Line, arriba: Line | None):
        """Una seccion puede reimprimir el encabezado con otras columnas."""
        if any(_es_monto(w.text) for w in line.words):
            return None
        columnas, campos = _columnas_de(line, arriba, _CAMPOS_TABLA)
        if not _sirve_de_tabla(campos):
            return None
        return Layout(columns=columnas, texto_en_montos=False), campos

    def _fila(self, line: Line, layout: Layout, campos: dict[int, str],
              meta: MetaEstadoCuenta, num_cuenta: str, pagina: int
              ) -> MovimientoBancario | None:
        celdas = _celdas_de_movimiento(line, layout, campos)
        crudo = " ".join(w.text for w in celdas.get("fecha", ()))
        fecha = _fecha_de(crudo, meta)
        if fecha is None:
            return None
        dia, normalizada = fecha
        return MovimientoBancario(
            num_cuenta=num_cuenta,
            dia=dia,
            fecha=normalizada,
            descripcion=" ".join(w.text for w in celdas.get("descripcion", ())),
            referencia=" ".join(w.text for w in celdas.get("referencia", ())),
            deposito=_importe(celdas.get("deposito")),
            retiro=_importe(celdas.get("retiro")),
            saldo=_importe(celdas.get("saldo"), vacio=None),
            pagina=pagina,
        )

    # --- API ------------------------------------------------------------
    def parse(self, document: Document, *, layout: Layout | None = None,
              mapeo: "dict[str, int] | Mapeo | None" = None) -> EstadoCuenta:
        paginas = list(document.open_pages())
        if not paginas:
            raise LayoutDesconocido("el documento no trajo paginas")
        lineas_por_pagina = [group(p.words) for p in paginas]

        lectura = self._identificacion(lineas_por_pagina)
        ident = lectura.identificadores
        meta = MetaEstadoCuenta(
            banco=ident.get("banco", ""), rfc=ident.get("rfc", ""),
            periodo_ini=ident.get("periodo_ini", ""),
            periodo_fin=ident.get("periodo_fin", ""),
            anio=ident.get("anio", ""),
            total_saldo_inicial=lectura.total.get("saldo_inicial"),
            total_saldo_corte=lectura.total.get("saldo_corte"))
        cuentas = self._cuentas(lectura)

        layout = layout or detectar_cabecera(paginas)
        if layout is None:
            raise ReporteNoEsperado(_tipo_sin_tabla(cuentas, lectura.evidencia))

        movimientos = self._movimientos(paginas, lineas_por_pagina, layout,
                                        _campos_de(layout), meta, cuentas)
        if not movimientos:
            raise ReporteNoEsperado(_tipo_sin_tabla(cuentas, lectura.evidencia))

        conocido = mapeo if isinstance(mapeo, Mapeo) else None
        descripcion = conocido or Mapeo(
            campos={}, forma="edocta", verificado_por="aritmetica",
            orientacion_verificada=True, filas_afectadas=0)
        return EstadoCuenta(meta=meta, cuentas=cuentas,
                            movimientos=tuple(movimientos), mapeo=descripcion)


# --- Auxiliares del modulo ----------------------------------------------
def _importe(palabras, *, vacio: Decimal | None = _CERO) -> Decimal | None:
    return parse_monto(palabras[0].text) if palabras else vacio


def _num_cuenta_en(texto: str) -> str:
    """El numero de cuenta que el propio nombre del producto trae pegado."""
    candidatos = [t for t in texto.split() if _RE_NUM_CUENTA.match(t)
                  and not _RE_CLABE.match(t)]
    return candidatos[-1] if candidatos else ""


def _secciones(cuentas: Sequence[CuentaBancaria]) -> dict[str, str]:
    """Como se anuncia cada cuenta cuando empieza su bloque de movimientos."""
    secciones: dict[str, str] = {}
    for cuenta in cuentas:
        if cuenta.producto:
            secciones.setdefault(_clave(cuenta.producto), cuenta.num_cuenta)
    return secciones


def _seccion_de(line: Line, secciones: dict[str, str]) -> str | None:
    """La cuenta que anuncia este renglon, si anuncia alguna.

    Por como ABRE el renglon y no por igualdad: el documento repite el
    nombre del producto y a veces le agrega detras el numero de cuenta o la
    CLABE. Gana el nombre mas largo que encaje, para que 'inversion enlace
    negocios' no se lleve los movimientos de 'enlace negocios'.
    """
    clave = _clave(" ".join(w.text for w in line.words))
    if not clave:
        return None
    candidatos = [nombre for nombre in secciones if clave.startswith(nombre)]
    return secciones[max(candidatos, key=len)] if candidatos else None


def _es_apertura(movimiento: MovimientoBancario) -> bool:
    """El renglon de saldo de arranque no es un movimiento."""
    if movimiento.deposito or movimiento.retiro:
        return False
    return _clave(movimiento.descripcion).startswith(_APERTURA)


def _junta_signos(palabras: Sequence[Word]) -> list[Word]:
    """Pega al importe el simbolo y el signo que vienen en su propio token.

    Hay formatos que imprimen '$' como columna aparte y uno que marca el
    saldo negativo con un '-$' suelto delante. Sin juntarlos el signo se
    pierde y el saldo corrido falla justo en el renglon que lo lleva.
    """
    palabras = sorted(palabras, key=lambda w: w.x0)
    salida: list[Word] = []
    pendiente = ""
    for word in palabras:
        if _RE_SIGNO.match(word.text.strip()):
            pendiente += word.text.strip()
            continue
        if pendiente and _es_monto(word.text):
            salida.append(replace(word, text=f"{pendiente}{word.text}"))
        elif pendiente:
            salida.append(word)
        else:
            salida.append(word)
        pendiente = ""
    return salida


def _campo_de_monto(word: Word, montos: Sequence[ColumnSpec],
                    campos: dict[int, str]) -> str | None:
    """El importe se queda con la columna cuyo BORDE DERECHO tiene mas cerca.

    La tolerancia es media separacion entre columnas: alcanza para los 30pt
    que un importe desborda su encabezado en el formato mas desalineado, y
    nunca llega a la columna vecina.
    """
    if not montos:
        return None
    bordes = sorted(c.x_max for c in montos)
    huecos = [b - a for a, b in zip(bordes, bordes[1:])]
    limite = min(huecos) / 2 if huecos else 40.0
    elegida = min(montos, key=lambda c: abs(word.x1 - c.x_max))
    if abs(word.x1 - elegida.x_max) >= limite:
        return None
    return campos.get(elegida.index)


def _celdas_de_movimiento(line: Line, layout: Layout, campos: dict[int, str]
                          ) -> dict[str, list[Word]]:
    """Reparte las palabras de un renglon de la tabla de movimientos.

    Los importes van por su borde derecho; las fechas por la columna en que
    ABREN (van alineadas a la izquierda y pueden ser dos, operacion y
    liquidacion); el resto es descripcion, salvo lo que cae entero dentro de
    la columna de referencia. La descripcion NO se reparte por cercania:
    desborda su encabezado hasta la mitad de la pagina y acabaria en la
    casilla del importe.
    """
    celdas: dict[str, list[Word]] = {}
    palabras = _junta_signos(line.words)
    montos = tuple(c for c in layout.columns
                   if campos.get(c.index) in ("deposito", "retiro", "saldo"))
    columnas_fecha = [c for c in layout.columns if campos.get(c.index) == "fecha"]
    referencia = next((c for c in layout.columns
                       if campos.get(c.index) == "referencia"), None)

    consumidas = 0
    for orden, columna in enumerate(columnas_fecha):
        while (consumidas < len(palabras)
               and palabras[consumidas].x0 <= columna.x_max
               and not _es_monto(palabras[consumidas].text)):
            if orden == 0:
                celdas.setdefault("fecha", []).append(palabras[consumidas])
            consumidas += 1

    for word in palabras[consumidas:]:
        if _es_monto(word.text):
            campo = _campo_de_monto(word, montos, campos)
            if campo is not None:
                celdas.setdefault(campo, []).append(word)
            continue
        if (referencia is not None
                and any(c.isdigit() for c in word.text)
                and word.x0 >= referencia.x_min - _MARGEN_REFERENCIA_IZQ
                and word.x1 <= referencia.x_max + _MARGEN_REFERENCIA_DER):
            celdas.setdefault("referencia", []).append(word)
        else:
            celdas.setdefault("descripcion", []).append(word)
    return celdas


def _celdas_de_cuenta(line: Line, layout: Layout, campos: dict[int, str]
                      ) -> dict[str, list[Word]]:
    """Reparte las palabras de una fila del resumen de cuentas.

    Aqui si vale la cercania para el texto: las columnas son angostas y sus
    valores no desbordan. Un numero de cuenta con guiones tiene la forma
    exacta de un importe, asi que lo unico que decide es el punto decimal.
    """
    celdas: dict[str, list[Word]] = {}
    montos = tuple(c for c in layout.columns if c.align == "right")
    textos = _ensanchadas(layout.columns)
    for word in _junta_signos(line.words):
        if _es_monto(word.text):
            campo = _campo_de_monto(word, montos, campos)
        else:
            campo = _campo_de_texto(word, textos, campos)
        if campo is not None:
            celdas.setdefault(campo, []).append(word)
    return celdas


def _ensanchadas(columnas: Sequence[ColumnSpec]) -> tuple[ColumnSpec, ...]:
    """Las columnas de texto, extendidas hasta la mitad del hueco vecino.

    El valor de una celda es mas ancho que su etiqueta por los dos lados:
    'INVERSION ENLACE NEGOCIOS PFAE' desborda 80pt a la derecha de la
    palabra 'Producto', y una CLABE impresa por grupos empieza 24pt a la
    izquierda de su etiqueta. Lo que separa dos celdas no es ninguna de las
    dos etiquetas: es el punto medio entre ellas.
    """
    orden = sorted(columnas, key=lambda c: c.x_min)
    textos = [c for c in orden if c.align != "right"]
    if len(textos) == 1:
        # Nada compite con ella: el valor puede llegar hasta donde alcance.
        return (replace(textos[0], x_min=float("-inf"), x_max=float("inf")),)
    anchas = []
    for posicion, columna in enumerate(orden):
        if columna.align == "right":
            continue
        izquierda = (orden[posicion - 1].x_max + columna.x_min) / 2 \
            if posicion else float("-inf")
        derecha = (columna.x_max + orden[posicion + 1].x_min) / 2 \
            if posicion + 1 < len(orden) else float("inf")
        anchas.append(replace(columna, x_min=izquierda, x_max=derecha))
    return tuple(anchas)


def _campo_de_texto(word: Word, textos: Sequence[ColumnSpec],
                    campos: dict[int, str]) -> str | None:
    centro = (word.x0 + word.x1) / 2
    for columna in textos:
        if columna.x_min <= centro <= columna.x_max:
            return campos.get(columna.index)
    return None


def _tipo_sin_tabla(cuentas: Sequence[CuentaBancaria],
                    evidencia: Sequence[str]) -> TipoDeReporte:
    """QUE es un documento que no trae tabla de movimientos.

    Cuando el resumen del propio banco declara cero depositos y cero
    retiros, la respuesta no es 'no encontre la tabla': es que la cuenta no
    tuvo movimientos en el periodo, y la capa web puede decirlo asi.
    """
    con_saldos = [c for c in cuentas
                  if c.depositos is not None and c.retiros is not None]
    if con_saldos and all(c.depositos == _CERO and c.retiros == _CERO
                          for c in con_saldos):
        return TipoDeReporte(
            clave="sin_movimientos",
            etiqueta=("el documento no trae tabla de movimientos porque la "
                      "cuenta no tuvo ninguno: su resumen declara depositos "
                      "y retiros en cero"),
            evidencia=tuple(evidencia), cuentas=tuple(cuentas))
    return TipoDeReporte(
        clave="no_identificado",
        etiqueta=("no se encontro la tabla de movimientos y el resumen no "
                  "alcanza para decir de que tipo de reporte se trata"),
        evidencia=tuple(evidencia), cuentas=tuple(cuentas))
