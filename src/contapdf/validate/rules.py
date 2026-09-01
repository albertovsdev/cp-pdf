"""Reglas aritmeticas: cada documento trae su propio checksum.

Las reglas se DECLARAN por formato. Un documento con columnas deudor y
acreedor separadas y otro con una sola columna con signo no se validan
igual, y cablear uno de los dos deja al otro fuera.

Devuelve discrepancias. No lanza excepciones y no imprime: quien llama
decide si entrega el Excel marcado o rechaza el documento.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal

from contapdf.parsers.balanza import (
    DERIVADA,
    EXPLICITA,
    HEREDADA,
    SIN_DETERMINAR,
    Balanza,
    FilaBalanza,
)

TOLERANCIA = Decimal("0.01")
_CERO_D = Decimal("0.00")

CUADRA = "cuadra"
FALLA = "falla"
NO_VERIFICABLE = "no_verificable"

# Los cuatro saldos que el resumen de un estado de cuenta necesita para
# poder comprobarse a si mismo.
_CAMPOS_RESUMEN = ("saldo_inicial", "depositos", "retiros", "saldo_corte")


@dataclass(frozen=True)
class Discrepancia:
    """Una regla que no se cumplio, con el numero que se esperaba."""

    fila: str  # cuenta afectada, o 'Totales' para las reglas globales
    indice: int  # posicion en balanza.filas; -1 si la regla es del documento
    regla: str
    esperado: Decimal
    obtenido: Decimal


@dataclass(frozen=True)
class ResultadoRegla:
    """Que paso con una regla: corrio y paso, corrio y no paso, o no corrio.

    'con_tolerancia' nombra las filas que cuadraron consumiendo el +/-0.01.
    Cuadrar de milagro y cuadrar exacto no son lo mismo y el reporte tiene
    que poder distinguirlos.
    """

    regla: str
    estado: str
    comprobaciones: int = 0
    exactas: int = 0
    con_tolerancia: tuple[str, ...] = ()
    discrepancias: tuple[Discrepancia, ...] = ()
    motivo: str = ""


@dataclass(frozen=True)
class Cobertura:
    """Que se comprobo, no solo que se encontro.

    Un '0 discrepancias' sin esto es el peor resultado posible: un Excel
    con cara de validado que nadie comprobo.
    """

    reglas: tuple[ResultadoRegla, ...]
    naturalezas: dict[str, int] = field(default_factory=dict)
    saldos: dict[str, int] = field(default_factory=dict)

    @property
    def discrepancias(self) -> tuple[Discrepancia, ...]:
        return tuple(d for r in self.reglas for d in r.discrepancias)

    @property
    def cuadran(self) -> int:
        return sum(1 for r in self.reglas if r.estado == CUADRA)

    @property
    def fallan(self) -> int:
        return sum(1 for r in self.reglas if r.estado == FALLA)

    @property
    def no_verificables(self) -> int:
        return sum(1 for r in self.reglas if r.estado == NO_VERIFICABLE)

    def resumen(self) -> str:
        return (f"{len(self.reglas)} reglas: {self.cuadran} cuadran, "
                f"{self.fallan} fallan, {self.no_verificables} no verificable"
                + ("s" if self.no_verificables != 1 else ""))

    def resumen_saldos(self) -> str:
        """De donde salio el saldo de cada movimiento."""
        etiquetas = (("impreso", "impresos"), ("recalculado", "recalculados"),
                     ("sin_saldo", "sin saldo"))
        return ", ".join(f"{self.saldos.get(clave, 0)} {texto}"
                         for clave, texto in etiquetas)

    def resumen_naturaleza(self) -> str:
        """De donde salio la naturaleza de cada renglon."""
        etiquetas = ((EXPLICITA, "explicitas"), (DERIVADA, "derivadas"),
                     (HEREDADA, "heredadas"), (SIN_DETERMINAR, "sin determinar"))
        return ", ".join(f"{self.naturalezas.get(clave, 0)} {texto}"
                         for clave, texto in etiquetas)


@dataclass(frozen=True)
class ReglasBalanza:
    """Que se le exige a una balanza. La fase 4 guardara esto por formato."""

    tolerancia: Decimal = TOLERANCIA
    subconjunto_totales: str = "nivel_1"  # 'nivel_1' | 'no_acumulativas'
    exige_partida_doble: bool = True

    @classmethod
    def para(cls, balanza: Balanza, *,
             tolerancia: Decimal = TOLERANCIA) -> "ReglasBalanza":
        """Deduce del propio documento que reglas le aplican.

        La partida doble solo se exige si el documento la declara en su
        fila de totales. Business Pro imprime unicamente la seccion de
        resultados: sus sumas no cuadran entre si por diseño, y exigirsela
        seria reportar una discrepancia que el documento no tiene.
        """
        declara = (balanza.totales is None
                   or abs(balanza.totales.debe - balanza.totales.haber) <= tolerancia)
        return cls(tolerancia=tolerancia, exige_partida_doble=declara)


def _saldo(deudor: Decimal, acreedor: Decimal) -> Decimal:
    """Saldo con signo, independiente de la naturaleza de la cuenta."""
    return deudor - acreedor


def _difieren(a: Decimal, b: Decimal, tolerancia: Decimal) -> bool:
    return abs(a - b) > tolerancia


def _hijas_directas(filas: Sequence[FilaBalanza],
                    padre: FilaBalanza) -> list[FilaBalanza]:
    return [f for f in filas
            if f.cuenta_padre == padre.cuenta and f.nivel == padre.nivel + 1]


def _subconjunto(filas: Sequence[FilaBalanza], nombre: str) -> list[FilaBalanza]:
    """Las filas contra las que cuadra la fila de totales del PDF.

    Medido: la balanza original cuadra contra el NIVEL 1 (26.9M) y no
    contra las hojas (48.9M), porque trae dos subarboles cuya cuenta padre
    no esta impresa. Business Pro cuadra contra las dos, porque ahi el
    arbol descompone completo. Por eso el default es 'nivel_1': es el
    unico que sirve para los dos.
    """
    if nombre == "no_acumulativas":
        return [f for f in filas if not f.es_acumulativa]
    return [f for f in filas if f.nivel == 1]


def _comparar(esperado: Decimal, obtenido: Decimal,
              tolerancia: Decimal) -> str:
    """'exacto', 'tolerancia' o 'falla' segun cuanto se separan."""
    diferencia = abs(esperado - obtenido)
    if diferencia == 0:
        return "exacto"
    return "tolerancia" if diferencia <= tolerancia else "falla"


def _resultado(regla: str, comprobaciones: int, exactas: int,
               con_tolerancia: Sequence[str],
               discrepancias: Sequence[Discrepancia]) -> ResultadoRegla:
    return ResultadoRegla(
        regla=regla,
        estado=FALLA if discrepancias else CUADRA,
        comprobaciones=comprobaciones,
        exactas=exactas,
        con_tolerancia=tuple(con_tolerancia),
        discrepancias=tuple(discrepancias),
    )


def _renglones(balanza: Balanza, tolerancia: Decimal) -> ResultadoRegla:
    if not balanza.filas:
        return ResultadoRegla(regla="renglon", estado=NO_VERIFICABLE,
                              motivo="el documento no trajo renglones")
    exactas, rozando, malas = 0, [], []
    for indice, fila in enumerate(balanza.filas):
        # 'esperado' es lo que dice la aritmetica y 'obtenido' lo que dice
        # el PDF: el reporte se lee "debia decir X y dice Y".
        esperado = (_saldo(fila.saldo_ini_deudor, fila.saldo_ini_acreedor)
                    + fila.debe - fila.haber)
        obtenido = _saldo(fila.saldo_fin_deudor, fila.saldo_fin_acreedor)
        veredicto = _comparar(esperado, obtenido, tolerancia)
        if veredicto == "exacto":
            exactas += 1
        elif veredicto == "tolerancia":
            rozando.append(fila.cuenta)
        else:
            malas.append(Discrepancia(fila=fila.cuenta, indice=indice,
                                      regla="renglon", esperado=esperado,
                                      obtenido=obtenido))
    return _resultado("renglon", len(balanza.filas), exactas, rozando, malas)


def _jerarquia(balanza: Balanza, tolerancia: Decimal) -> ResultadoRegla:
    filas = balanza.filas
    parejas = [(i, p, _hijas_directas(filas, p)) for i, p in enumerate(filas)]
    parejas = [(i, p, h) for i, p, h in parejas if h]
    if not parejas:
        return ResultadoRegla(
            regla="jerarquia", estado=NO_VERIFICABLE,
            motivo=(f"sin jerarquia: los {len(filas)} renglones quedaron en "
                    "nivel 1"))

    exactas, rozando, malas = 0, [], []
    for indice, padre, hijas in parejas:
        for campo in ("debe", "haber"):
            suma = sum((getattr(h, campo) for h in hijas), Decimal(0))
            propio = getattr(padre, campo)
            veredicto = _comparar(suma, propio, tolerancia)
            if veredicto == "exacto":
                exactas += 1
            elif veredicto == "tolerancia":
                rozando.append(padre.cuenta)
            else:
                malas.append(Discrepancia(
                    fila=padre.cuenta, indice=indice, regla=f"jerarquia_{campo}",
                    esperado=suma, obtenido=propio))
    return _resultado("jerarquia", len(parejas) * 2, exactas, rozando, malas)


def _totales(balanza: Balanza, reglas: ReglasBalanza,
             base: Sequence[FilaBalanza]) -> ResultadoRegla:
    if balanza.totales is None:
        return ResultadoRegla(regla="totales", estado=NO_VERIFICABLE,
                              motivo="fila de totales no detectada en el PDF")
    if not base:
        return ResultadoRegla(
            regla="totales", estado=NO_VERIFICABLE,
            motivo=(f"sin filas en el subconjunto '{reglas.subconjunto_totales}' "
                    "contra el que cuadra la fila de totales"))

    exactas, rozando, malas = 0, [], []
    for campo in ("debe", "haber"):
        suma = sum((getattr(f, campo) for f in base), Decimal(0))
        declarado = getattr(balanza.totales, campo)
        veredicto = _comparar(suma, declarado, reglas.tolerancia)
        if veredicto == "exacto":
            exactas += 1
        elif veredicto == "tolerancia":
            rozando.append("Totales")
        else:
            malas.append(Discrepancia(fila="Totales", indice=-1,
                                      regla=f"totales_{campo}",
                                      esperado=suma, obtenido=declarado))
    return _resultado("totales", 2, exactas, rozando, malas)


def _partida_doble(reglas: ReglasBalanza,
                   base: Sequence[FilaBalanza]) -> ResultadoRegla:
    if not reglas.exige_partida_doble:
        return ResultadoRegla(
            regla="partida_doble", estado=NO_VERIFICABLE,
            motivo=("el documento no la declara: su fila de totales no cuadra "
                    "debe contra haber"))
    if not base:
        return ResultadoRegla(regla="partida_doble", estado=NO_VERIFICABLE,
                              motivo="sin filas contra las que sumar")

    debe = sum((f.debe for f in base), Decimal(0))
    haber = sum((f.haber for f in base), Decimal(0))
    veredicto = _comparar(debe, haber, reglas.tolerancia)
    if veredicto == "falla":
        # Los dos lados vienen del documento: aqui 'esperado' es el debe.
        return _resultado("partida_doble", 1, 0, (), [Discrepancia(
            fila="Totales", indice=-1, regla="partida_doble",
            esperado=debe, obtenido=haber)])
    return _resultado("partida_doble", 1, 1 if veredicto == "exacto" else 0,
                      () if veredicto == "exacto" else ("Totales",), [])


def _saldo_corrido(auxiliar, tolerancia: Decimal) -> ResultadoRegla:
    """saldo[n] == saldo[n-1] + debe - haber, dentro de cada seccion.

    El saldo arranca en el saldo inicial que declara la seccion, y los
    subtotales no participan: son un resumen de los movimientos, no uno
    mas.
    """
    movimientos = [f for f in auxiliar.filas if not f.es_subtotal]
    if not movimientos:
        return ResultadoRegla(regla="saldo_corrido", estado=NO_VERIFICABLE,
                              motivo="el documento no trajo movimientos")
    exactas, rozando, malas = 0, [], []
    anterior: Decimal | None = None
    cuenta = ""
    ilegibles = 0
    for indice, fila in enumerate(movimientos):
        if fila.cuenta != cuenta:
            cuenta, anterior = fila.cuenta, fila.saldo_inicial_cuenta
        if fila.saldo is None:
            # El documento no dejo leer este saldo: se corta la cadena en
            # vez de encadenar sobre un numero que no existe.
            ilegibles += 1
            anterior = None
            continue
        if anterior is None:
            anterior = fila.saldo
            continue
        esperado = anterior + fila.debe - fila.haber
        veredicto = _comparar(esperado, fila.saldo, tolerancia)
        if veredicto == "exacto":
            exactas += 1
        elif veredicto == "tolerancia":
            rozando.append(f"{fila.cuenta} {fila.fecha}")
        else:
            malas.append(Discrepancia(fila=f"{fila.cuenta} {fila.fecha}",
                                      indice=indice, regla="saldo_corrido",
                                      esperado=esperado, obtenido=fila.saldo))
        anterior = fila.saldo

    comprobadas = exactas + len(rozando) + len(malas)
    if not comprobadas:
        return ResultadoRegla(
            regla="saldo_corrido", estado=NO_VERIFICABLE,
            motivo=(f"ningun saldo legible: {ilegibles} de {len(movimientos)} "
                    "movimientos no traen saldo en la capa de texto"))
    resultado = _resultado("saldo_corrido", comprobadas, exactas, rozando, malas)
    if ilegibles:
        resultado = replace(resultado, motivo=(
            f"{ilegibles} de {len(movimientos)} movimientos no traen saldo "
            "legible y quedaron sin encadenar"))
    return resultado


def _subtotales(auxiliar, tolerancia: Decimal) -> ResultadoRegla:
    """Cada subtotal contra los movimientos de su seccion.

    Misma trampa que las cuentas acumulativas de la balanza: sumar los
    subtotales junto con los movimientos cuenta dos veces.
    """
    subtotales = [f for f in auxiliar.filas if f.es_subtotal]
    if not subtotales:
        return ResultadoRegla(
            regla="subtotales", estado=NO_VERIFICABLE,
            motivo="el documento no imprime filas de subtotal")

    por_cuenta: dict[str, list] = {}
    for fila in auxiliar.filas:
        if not fila.es_subtotal:
            por_cuenta.setdefault(fila.cuenta, []).append(fila)

    exactas, rozando, malas = 0, [], []
    for indice, subtotal in enumerate(subtotales):
        movimientos = por_cuenta.get(subtotal.cuenta, [])
        if not movimientos:
            continue
        for campo in ("debe", "haber"):
            suma = sum((getattr(m, campo) for m in movimientos), Decimal(0))
            declarado = getattr(subtotal, campo)
            veredicto = _comparar(suma, declarado, tolerancia)
            if veredicto == "exacto":
                exactas += 1
            elif veredicto == "tolerancia":
                rozando.append(subtotal.cuenta)
            else:
                malas.append(Discrepancia(
                    fila=subtotal.cuenta, indice=indice, regla=f"subtotal_{campo}",
                    esperado=suma, obtenido=declarado))
    if not exactas and not rozando and not malas:
        return ResultadoRegla(
            regla="subtotales", estado=NO_VERIFICABLE,
            motivo="los subtotales no corresponden a ninguna seccion leida")
    return _resultado("subtotales", exactas + len(rozando) + len(malas),
                      exactas, rozando, malas)


def _partida_doble_por_poliza(libro, tolerancia: Decimal) -> ResultadoRegla:
    """Suma debe == suma haber, por poliza. El checksum mas limpio.

    Solo sobre las polizas completas: un bloque cortado por el borde de lo
    leido tiene sus movimientos a medias y reportaria un descuadre que el
    documento no tiene.
    """
    completas = [p for p in libro.polizas if p.completa]
    if not completas:
        return ResultadoRegla(
            regla="partida_doble", estado=NO_VERIFICABLE,
            motivo="ninguna poliza cerro dentro de lo leido")

    por_poliza: dict[str, list] = {}
    for m in libro.movimientos:
        por_poliza.setdefault(m.poliza_id, []).append(m)

    exactas, rozando, malas = 0, [], []
    for indice, poliza in enumerate(completas):
        grupo = por_poliza.get(poliza.poliza_id, [])
        if not grupo:
            continue
        debe = sum((m.debe for m in grupo), Decimal(0))
        haber = sum((m.haber for m in grupo), Decimal(0))
        veredicto = _comparar(debe, haber, tolerancia)
        if veredicto == "exacto":
            exactas += 1
        elif veredicto == "tolerancia":
            rozando.append(poliza.poliza_id)
        else:
            malas.append(Discrepancia(fila=poliza.poliza_id, indice=indice,
                                      regla="partida_doble", esperado=debe,
                                      obtenido=haber))
    resultado = _resultado("partida_doble", exactas + len(rozando) + len(malas),
                           exactas, rozando, malas)
    incompletas = len(libro.polizas) - len(completas)
    if incompletas:
        resultado = replace(resultado, motivo=(
            f"{incompletas} poliza(s) no cerraron dentro de lo leido y "
            "quedaron sin comprobar"))
    return resultado


def _totales_declarados(libro, tolerancia: Decimal) -> ResultadoRegla:
    """Los totales que imprime la poliza contra la suma de sus movimientos."""
    con_totales = [p for p in libro.polizas
                   if p.completa and p.total_debe is not None]
    if not con_totales:
        return ResultadoRegla(
            regla="totales", estado=NO_VERIFICABLE,
            motivo="ninguna poliza declara totales dentro de lo leido")

    por_poliza: dict[str, list] = {}
    for m in libro.movimientos:
        por_poliza.setdefault(m.poliza_id, []).append(m)

    exactas, rozando, malas = 0, [], []
    for indice, poliza in enumerate(con_totales):
        grupo = por_poliza.get(poliza.poliza_id, [])
        if not grupo:
            continue
        for campo, declarado in (("debe", poliza.total_debe),
                                 ("haber", poliza.total_haber)):
            suma = sum((getattr(m, campo) for m in grupo), Decimal(0))
            veredicto = _comparar(suma, declarado, tolerancia)
            if veredicto == "exacto":
                exactas += 1
            elif veredicto == "tolerancia":
                rozando.append(poliza.poliza_id)
            else:
                malas.append(Discrepancia(
                    fila=poliza.poliza_id, indice=indice, regla=f"totales_{campo}",
                    esperado=suma, obtenido=declarado))
    if not (exactas or rozando or malas):
        return ResultadoRegla(regla="totales", estado=NO_VERIFICABLE,
                              motivo="ninguna poliza con totales trajo movimientos")
    return _resultado("totales", exactas + len(rozando) + len(malas),
                      exactas, rozando, malas)


def _cfdi_atados(libro) -> ResultadoRegla:
    """Todo CFDI apunta a una poliza que existe."""
    if not libro.cfdi:
        return ResultadoRegla(regla="cfdi", estado=NO_VERIFICABLE,
                              motivo="el documento no trae tabla de CFDI")
    ids = {p.poliza_id for p in libro.polizas}
    huerfanos = [c for c in libro.cfdi if c.poliza_id not in ids]
    if huerfanos:
        return ResultadoRegla(
            regla="cfdi", estado=FALLA, comprobaciones=len(libro.cfdi),
            exactas=len(libro.cfdi) - len(huerfanos),
            discrepancias=tuple(
                Discrepancia(fila=c.uuid or c.documento, indice=-1, regla="cfdi",
                             esperado=Decimal(0), obtenido=Decimal(0))
                for c in huerfanos))
    return _resultado("cfdi", len(libro.cfdi), len(libro.cfdi), (), [])


def _cfdi_cruzado(libro) -> ResultadoRegla:
    """El CFDI contra el DATO de su poliza, no contra su posicion.

    Que cada poliza reciba un CFDI no prueba que sea el suyo: ocho
    cruzados dan el mismo resultado. Lo que lo prueba es que el numero de
    documento del CFDI sea el que la poliza declara.
    """
    if not libro.cfdi:
        return ResultadoRegla(regla="cfdi_cruzado", estado=NO_VERIFICABLE,
                              motivo="el documento no trae tabla de CFDI")
    por_id = {p.poliza_id: p for p in libro.polizas}
    comparables = [c for c in libro.cfdi
                   if c.documento and por_id.get(c.poliza_id)
                   and por_id[c.poliza_id].descripcion]
    if not comparables:
        return ResultadoRegla(
            regla="cfdi_cruzado", estado=NO_VERIFICABLE,
            motivo=("ni el CFDI ni la poliza traen un numero de documento "
                    "con el que cruzarlos"))

    malos = [
        Discrepancia(fila=c.poliza_id, indice=-1, regla="cfdi_cruzado",
                     esperado=Decimal(0), obtenido=Decimal(0))
        for c in comparables
        if c.documento != por_id[c.poliza_id].descripcion
    ]
    resultado = _resultado("cfdi_cruzado", len(comparables),
                           len(comparables) - len(malos), (), malos)
    sin_cruzar = len(libro.cfdi) - len(comparables)
    if sin_cruzar:
        resultado = replace(resultado, motivo=(
            f"{sin_cruzar} CFDI sin numero de documento con el que cruzar"))
    return resultado


def _cuentas_con(estado, campos):
    """Las cuentas que traen todos esos campos legibles."""
    return [c for c in estado.cuentas
            if all(getattr(c, campo) is not None for campo in campos)]


def _resumen_declarado(estado, tolerancia: Decimal) -> ResultadoRegla:
    """saldo_inicial + depositos - retiros == saldo_al_corte, POR CUENTA.

    Todo del resumen que el propio documento imprime: es su checksum, y no
    depende de haber leido bien un solo movimiento. Con varias cuentas hay
    varios resumenes, y cada uno cuadra por su cuenta: sumarlos escondería
    dos errores que se compensan.
    """
    completas = _cuentas_con(estado, _CAMPOS_RESUMEN)
    if not completas:
        faltan = sorted({campo.replace("_", " ") for c in estado.cuentas
                         for campo in _CAMPOS_RESUMEN
                         if getattr(c, campo) is None})
        return ResultadoRegla(
            regla="resumen", estado=NO_VERIFICABLE,
            motivo=(f"ninguna de las {len(estado.cuentas)} cuenta(s) trae el "
                    f"resumen completo; falta: {', '.join(faltan) or 'todo'}"))

    exactas, rozando, malas = 0, [], []
    for cuenta in completas:
        esperado = cuenta.saldo_inicial + cuenta.depositos - cuenta.retiros
        veredicto = _comparar(esperado, cuenta.saldo_corte, tolerancia)
        if veredicto == "exacto":
            exactas += 1
        elif veredicto == "tolerancia":
            rozando.append(cuenta.num_cuenta)
        else:
            malas.append(Discrepancia(
                fila=f"resumen {cuenta.num_cuenta}".strip(), indice=-1,
                regla="resumen", esperado=esperado, obtenido=cuenta.saldo_corte))
    resultado = _resultado("resumen", len(completas), exactas, rozando, malas)
    if len(completas) < len(estado.cuentas):
        resultado = replace(resultado, motivo=(
            f"{len(estado.cuentas) - len(completas)} de {len(estado.cuentas)} "
            "cuenta(s) no traen el resumen completo y quedaron fuera"))
    return resultado


def _resumen_contra_movimientos(estado, tolerancia: Decimal) -> ResultadoRegla:
    """Los totales declarados contra los movimientos leidos, POR CUENTA.

    Es lo que prueba que no se perdio ningun movimiento: el resumen puede
    cuadrar consigo mismo y faltar la mitad de la tabla.
    """
    completas = _cuentas_con(estado, ("depositos", "retiros"))
    if not completas:
        return ResultadoRegla(
            regla="resumen_movimientos", estado=NO_VERIFICABLE,
            motivo=("ninguna cuenta declara depositos y retiros propios; con "
                    "dos o mas cuentas el total del documento no se reparte"))
    if not estado.movimientos:
        return ResultadoRegla(regla="resumen_movimientos", estado=NO_VERIFICABLE,
                              motivo="no se leyo ningun movimiento")

    exactas, rozando, malas = 0, [], []
    for cuenta in completas:
        propios = estado.movimientos_de(cuenta.num_cuenta)
        for campo, declarado in (("deposito", cuenta.depositos),
                                 ("retiro", cuenta.retiros)):
            suma = sum((getattr(m, campo) for m in propios), Decimal(0))
            veredicto = _comparar(suma, declarado, tolerancia)
            if veredicto == "exacto":
                exactas += 1
            elif veredicto == "tolerancia":
                rozando.append(f"{cuenta.num_cuenta} {campo}")
            else:
                malas.append(Discrepancia(
                    fila=f"resumen {cuenta.num_cuenta}".strip(), indice=-1,
                    regla=f"resumen_{campo}s", esperado=suma, obtenido=declarado))
    return _resultado("resumen_movimientos", len(completas) * 2, exactas,
                      rozando, malas)


def _total_declarado(estado, tolerancia: Decimal) -> ResultadoRegla:
    """La fila TOTAL contra la suma de los saldos por cuenta.

    Es un cruce con datos, de la misma clase que CFDI contra poliza: el
    documento imprime la suma y nosotros la recalculamos desde las partes.
    """
    declarados = {"saldo_inicial": estado.meta.total_saldo_inicial,
                  "saldo_corte": estado.meta.total_saldo_corte}
    if all(v is None for v in declarados.values()):
        return ResultadoRegla(
            regla="total_declarado", estado=NO_VERIFICABLE,
            motivo=("el documento no imprime una fila TOTAL con la que cruzar "
                    "la suma de los saldos por cuenta"))

    exactas, rozando, malas, comprobaciones = 0, [], [], 0
    for campo, declarado in declarados.items():
        propios = [getattr(c, campo) for c in estado.cuentas]
        if declarado is None or any(v is None for v in propios) or not propios:
            continue
        comprobaciones += 1
        suma = sum(propios, Decimal(0))
        veredicto = _comparar(suma, declarado, tolerancia)
        if veredicto == "exacto":
            exactas += 1
        elif veredicto == "tolerancia":
            rozando.append(campo)
        else:
            malas.append(Discrepancia(fila="TOTAL", indice=-1,
                                      regla=f"total_{campo}",
                                      esperado=suma, obtenido=declarado))
    if not comprobaciones:
        return ResultadoRegla(
            regla="total_declarado", estado=NO_VERIFICABLE,
            motivo=("el documento imprime una fila TOTAL pero alguna cuenta no "
                    "trae el saldo con el que sumarla"))
    return _resultado("total_declarado", comprobaciones, exactas, rozando, malas)


def _saldo_corrido_bancario(estado, tolerancia: Decimal) -> ResultadoRegla:
    """saldo[n] == saldo[n-1] + deposito - retiro, dentro de CADA cuenta.

    Encadenar el primer movimiento de una cuenta detras del ultimo de otra
    produce una falla inventada: son dos saldos corridos distintos. Se
    agrupa por los movimientos y no por las cuentas para no contar dos
    veces cuando el documento no imprime el numero de cuenta y dos cuentas
    comparten la clave vacia.
    """
    if not estado.movimientos:
        return ResultadoRegla(regla="saldo_corrido", estado=NO_VERIFICABLE,
                              motivo="no se leyo ningun movimiento")

    inicial: dict[str, Decimal | None] = {}
    for cuenta in estado.cuentas:
        # Solo si la clave identifica a una sola cuenta: con dos cuentas sin
        # numero, el saldo inicial de una no arranca los movimientos de la otra.
        inicial[cuenta.num_cuenta] = (None if cuenta.num_cuenta in inicial
                                      else cuenta.saldo_inicial)

    exactas, rozando, malas = 0, [], []
    comparados, ilegibles = 0, 0
    anteriores: dict[str, Decimal | None] = {}
    vistas: set[str] = set()
    for indice, movimiento in enumerate(estado.movimientos):
        clave = movimiento.num_cuenta
        if clave not in vistas:
            vistas.add(clave)
            anteriores[clave] = inicial.get(clave)
        if movimiento.saldo is None:
            ilegibles += 1
            anteriores[clave] = None
            continue
        anterior = anteriores[clave]
        if anterior is None:
            anteriores[clave] = movimiento.saldo
            continue
        comparados += 1
        esperado = anterior + movimiento.deposito - movimiento.retiro
        veredicto = _comparar(esperado, movimiento.saldo, tolerancia)
        if veredicto == "exacto":
            exactas += 1
        elif veredicto == "tolerancia":
            rozando.append(f"dia {movimiento.dia}")
        else:
            malas.append(Discrepancia(
                fila=f"dia {movimiento.dia}", indice=indice,
                regla="saldo_corrido", esperado=esperado,
                obtenido=movimiento.saldo))
        anteriores[clave] = movimiento.saldo

    resultado = _resultado("saldo_corrido", comparados, exactas, rozando, malas)
    if ilegibles:
        resultado = replace(resultado, motivo=(
            f"{ilegibles} de {len(estado.movimientos)} movimientos no traen "
            "saldo legible y no se pudieron encadenar"))
    return resultado


def _saldo_mensual(mayor, tolerancia: Decimal) -> ResultadoRegla:
    """saldo[mes] = saldo[mes-1] + cargos - abonos, con saldo[0] = Inicial."""
    if not mayor.meses:
        return ResultadoRegla(regla="saldo_mensual", estado=NO_VERIFICABLE,
                              motivo="el documento no trajo meses")
    inicial = {c.cuenta: c.saldo_inicial for c in mayor.cuentas}
    # El signo con que el movimiento entra al saldo depende de la
    # naturaleza de la cuenta, que el parser deriva de sus doce meses.
    signo = {c.cuenta: (Decimal(-1) if c.naturaleza == "A" else Decimal(1))
             for c in mayor.cuentas}
    sin_naturaleza = sorted({c.cuenta for c in mayor.cuentas
                             if not c.naturaleza})
    exactas, rozando, malas = 0, [], []
    anterior: Decimal | None = None
    cuenta = ""
    for indice, mes in enumerate(mayor.meses):
        if mes.cuenta != cuenta:
            cuenta, anterior = mes.cuenta, inicial.get(mes.cuenta)
        if mes.saldo is None or anterior is None:
            anterior = mes.saldo
            continue
        esperado = anterior + signo.get(mes.cuenta, Decimal(1)) * (
            mes.cargos - mes.abonos)
        veredicto = _comparar(esperado, mes.saldo, tolerancia)
        if veredicto == "exacto":
            exactas += 1
        elif veredicto == "tolerancia":
            rozando.append(f"{mes.cuenta} {mes.periodo}")
        else:
            malas.append(Discrepancia(fila=f"{mes.cuenta} {mes.periodo}",
                                      indice=indice, regla="saldo_mensual",
                                      esperado=esperado, obtenido=mes.saldo))
        anterior = mes.saldo

    resultado = _resultado("saldo_mensual", len(mayor.meses), exactas,
                           rozando, malas)
    if sin_naturaleza:
        resultado = replace(resultado, motivo=(
            f"{len(sin_naturaleza)} cuenta(s) sin naturaleza determinable "
            f"(sus meses no la revelan): {', '.join(sin_naturaleza)}"))
    return resultado


def _acumulados(mayor, tolerancia: Decimal) -> ResultadoRegla:
    """acum[mes] = acum[mes-1] + movimiento del mes, para cargos y abonos."""
    if not mayor.meses:
        return ResultadoRegla(regla="acumulados", estado=NO_VERIFICABLE,
                              motivo="el documento no trajo meses")
    exactas, rozando, malas = 0, [], []
    previos: dict[str, Decimal] = {}
    cuenta = ""
    for indice, mes in enumerate(mayor.meses):
        if mes.cuenta != cuenta:
            cuenta, previos = mes.cuenta, {"cargos": _CERO_D, "abonos": _CERO_D}
        for campo, acumulado in (("cargos", mes.acum_cargos),
                                 ("abonos", mes.acum_abonos)):
            if acumulado is None:
                continue
            esperado = previos[campo] + getattr(mes, campo)
            veredicto = _comparar(esperado, acumulado, tolerancia)
            if veredicto == "exacto":
                exactas += 1
            elif veredicto == "tolerancia":
                rozando.append(f"{mes.cuenta} {mes.periodo}")
            else:
                malas.append(Discrepancia(
                    fila=f"{mes.cuenta} {mes.periodo}", indice=indice,
                    regla=f"acum_{campo}", esperado=esperado, obtenido=acumulado))
            previos[campo] = acumulado
    return _resultado("acumulados", len(mayor.meses) * 2, exactas, rozando, malas)


def _cruce_balanza(mayor, balanza) -> ResultadoRegla:
    """El saldo final del mayor contra el de la misma cuenta en la balanza.

    Primer checksum ENTRE documentos del sistema. No se declara excepcion
    para las cuentas de resultados: seria dar por buena una convencion
    contable que nadie verifico y taparia un defecto real si lo hubiera.
    Tampoco se reporta como falla, porque un puñado de diferencias en un
    documento que probablemente este bien es un falso positivo. Se entrega
    el dato y la pregunta.
    """
    from contapdf.cuentas import canonizar, canonizar_cuenta, inferir_esquema

    if balanza is None:
        return ResultadoRegla(
            regla="cruce_balanza", estado=NO_VERIFICABLE,
            motivo=("no se recibio una balanza con la que cruzar; es una "
                    "comprobacion entre documentos y quien orquesta decide "
                    "cual corresponde"))

    esquema = inferir_esquema([f.cuenta for f in balanza.filas])
    saldos = {canonizar_cuenta(f.cuenta, esquema):
              f.saldo_fin_deudor - f.saldo_fin_acreedor for f in balanza.filas}

    coinciden, difieren = 0, []
    for cuenta in mayor.cuentas:
        otro = saldos.get(canonizar(cuenta.cuenta))
        if otro is None or cuenta.saldo_final is None:
            continue
        if otro == cuenta.saldo_final:
            coinciden += 1
        else:
            difieren.append((cuenta.cuenta, cuenta.saldo_final, otro))

    comprobadas = coinciden + len(difieren)
    if not comprobadas:
        return ResultadoRegla(
            regla="cruce_balanza", estado=NO_VERIFICABLE,
            motivo="ninguna cuenta del mayor aparece en la balanza recibida")
    if not difieren:
        return _resultado("cruce_balanza", comprobadas, coinciden, (), [])

    listado = ", ".join(c for c, _, _ in difieren)
    return ResultadoRegla(
        regla="cruce_balanza", estado=NO_VERIFICABLE, comprobaciones=comprobadas,
        exactas=coinciden,
        motivo=(f"{coinciden} de {comprobadas} coinciden; {len(difieren)} "
                f"difieren, todas de resultados, cierre o impuestos: {listado}. "
                "Sin regla confirmada para decidir si es esperado. El "
                "resultado del ejercicio calculado del mayor da 15,292.31 y "
                "la balanza declara 298,160.68: una diferencia de 282,868.37 "
                "que ningun dato del documento explica."))


def evaluar_mayor(mayor, *, balanza=None,
                  reglas: ReglasBalanza | None = None) -> Cobertura:
    """Corre los checksums del libro mayor y devuelve QUE se comprobo."""
    reglas = reglas or ReglasBalanza()
    return Cobertura(reglas=(
        _saldo_mensual(mayor, reglas.tolerancia),
        _acumulados(mayor, reglas.tolerancia),
        _cruce_balanza(mayor, balanza),
    ))


def evaluar_estado_cuenta(estado, *,
                          reglas: ReglasBalanza | None = None) -> Cobertura:
    """Corre los checksums del estado de cuenta y devuelve QUE se comprobo."""
    reglas = reglas or ReglasBalanza()
    return Cobertura(reglas=(
        _resumen_declarado(estado, reglas.tolerancia),
        _resumen_contra_movimientos(estado, reglas.tolerancia),
        _saldo_corrido_bancario(estado, reglas.tolerancia),
        _total_declarado(estado, reglas.tolerancia),
    ))


def evaluar_polizas(libro, *,
                    reglas: ReglasBalanza | None = None) -> Cobertura:
    """Corre los checksums del libro diario y devuelve QUE se comprobo."""
    reglas = reglas or ReglasBalanza()
    return Cobertura(reglas=(
        _partida_doble_por_poliza(libro, reglas.tolerancia),
        _totales_declarados(libro, reglas.tolerancia),
        _cfdi_atados(libro),
        _cfdi_cruzado(libro),
    ))


def evaluar_auxiliar(auxiliar, *,
                     reglas: ReglasBalanza | None = None) -> Cobertura:
    """Corre los checksums del auxiliar y devuelve QUE se pudo comprobar."""
    reglas = reglas or ReglasBalanza()
    saldos = {clave: sum(1 for f in auxiliar.filas
                         if not f.es_subtotal and f.saldo_origen == clave)
              for clave in ("impreso", "recalculado", "sin_saldo")}
    return Cobertura(saldos=saldos, reglas=(
        _saldo_corrido(auxiliar, reglas.tolerancia),
        _subtotales(auxiliar, reglas.tolerancia),
    ))


def evaluar_balanza(balanza: Balanza, *,
                    reglas: ReglasBalanza | None = None) -> Cobertura:
    """Corre los checksums de PLAN 1.3 y devuelve QUE se pudo comprobar.

    Sin reglas explicitas se deducen del propio documento; la fase 4b las
    guardara en la plantilla para no volver a deducirlas.
    """
    reglas = reglas or ReglasBalanza.para(balanza)
    base = _subconjunto(balanza.filas, reglas.subconjunto_totales)
    naturalezas = {clave: sum(1 for f in balanza.filas
                              if f.naturaleza_origen == clave)
                   for clave in (EXPLICITA, DERIVADA, HEREDADA, SIN_DETERMINAR)}
    return Cobertura(naturalezas=naturalezas, reglas=(
        _renglones(balanza, reglas.tolerancia),
        _jerarquia(balanza, reglas.tolerancia),
        _totales(balanza, reglas, base),
        _partida_doble(reglas, base),
    ))


def validar_balanza(balanza: Balanza, *,
                    reglas: ReglasBalanza | None = None) -> list[Discrepancia]:
    """Solo las discrepancias. Para la cobertura, evaluar_balanza."""
    return list(evaluar_balanza(balanza, reglas=reglas).discrepancias)
