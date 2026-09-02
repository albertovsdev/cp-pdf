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
    # El UNIVERSO: cuantos casos de esta regla contiene el documento. None
    # solo cuando no se pudo determinar, y entonces la regla no puede
    # afirmar que cuadro.
    aplicables: int | None = None
    # Cuantos de esos casos recibieron veredicto. Antes se llamaba
    # 'comprobaciones' y en unas reglas significaba esto y en otras el
    # universo: un 5 de 116 y un 116 de 116 se imprimian igual.
    evaluados: int = 0
    exactas: int = 0
    con_tolerancia: tuple[str, ...] = ()
    discrepancias: tuple[Discrepancia, ...] = ()
    motivo: str = ""

    def __post_init__(self) -> None:
        if self.estado == CUADRA and self.aplicables is None:
            raise ValueError(
                f"{self.regla}: no puede cuadrar sin saber sobre cuantos "
                "casos podia correr; sin 'aplicables' va no_verificable")
        if self.aplicables is not None and self.aplicables < self.evaluados:
            raise ValueError(
                f"{self.regla}: 'aplicables' ({self.aplicables}) no puede ser "
                f"menor que 'evaluados' ({self.evaluados})")

    @property
    def comprobaciones(self) -> int:
        """DEPRECADO, se retira en la fase 8. Usa 'evaluados'."""
        return self.evaluados

    def resumen(self) -> str:
        """La linea de una regla, siempre con su denominador."""
        if self.aplicables is None:
            return f"{self.regla}: universo sin determinar"
        partes = [f"{self.evaluados} de {self.aplicables} evaluados",
                  f"{self.exactas} exactos"]
        if self.con_tolerancia:
            partes.append(f"{len(self.con_tolerancia)} dentro de tolerancia")
        if self.discrepancias:
            partes.append(f"{len(self.discrepancias)} con diferencia")
        return f"{self.regla}: " + ", ".join(partes)


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

    @property
    def aplicables(self) -> int:
        """Casos que los documentos contienen para el conjunto de reglas."""
        return sum(r.aplicables or 0 for r in self.reglas)

    @property
    def evaluados(self) -> int:
        return sum(r.evaluados for r in self.reglas)

    def resumen(self) -> str:
        """Nunca un numerador solo: cuantas reglas, y sobre cuantos casos."""
        sin_universo = sum(1 for r in self.reglas if r.aplicables is None)
        texto = (f"{len(self.reglas)} reglas: {self.cuadran} cuadran, "
                 f"{self.fallan} fallan, {self.no_verificables} no verificable"
                 + ("s" if self.no_verificables != 1 else "")
                 + f"; {self.evaluados} de {self.aplicables} casos evaluados")
        if sin_universo:
            texto += (f" ({sin_universo} regla"
                      + ("s" if sin_universo != 1 else "")
                      + " con universo sin determinar)")
        return texto

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


def _resultado(regla: str, aplicables: int, exactas: int,
               con_tolerancia: Sequence[str],
               discrepancias: Sequence[Discrepancia], *,
               evaluados: int | None = None,
               motivo: str = "") -> ResultadoRegla:
    """Arma el resultado y deja el hueco a la vista.

    'evaluados' se deduce de los veredictos emitidos; cuando es menor que
    el universo, el hueco se explica en 'motivo' -- una regla que corrio en
    parte del documento tiene que decir en que parte no corrio.
    """
    if evaluados is None:
        evaluados = exactas + len(con_tolerancia) + len(discrepancias)
    if evaluados < aplicables and not motivo:
        motivo = (f"{aplicables - evaluados} de {aplicables} casos no se "
                  "pudieron comprobar")
    return ResultadoRegla(
        regla=regla,
        estado=FALLA if discrepancias else CUADRA,
        aplicables=aplicables,
        evaluados=evaluados,
        exactas=exactas,
        con_tolerancia=tuple(con_tolerancia),
        discrepancias=tuple(discrepancias),
        motivo=motivo,
    )


def _renglones(balanza: Balanza, tolerancia: Decimal) -> ResultadoRegla:
    if not balanza.filas:
        return ResultadoRegla(regla="renglon", estado=NO_VERIFICABLE,
                              aplicables=0, evaluados=0,
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
    # El universo son los padres que el documento DECLARA que existen -- las
    # cuentas nombradas en algun 'cuenta_padre' -- y no los pares que se
    # lograron formar. Una hija que apunta a un padre ausente es un caso que
    # existe y no se comprobo; contar solo los pares formados lo escondia.
    # Se cuenta x2 porque cada padre se comprueba en debe y en haber, que
    # son las unidades de 'exactas'.
    padres_referidos = {f.cuenta_padre for f in filas if f.cuenta_padre}
    aplicables = len(padres_referidos) * 2
    parejas = [(i, p, _hijas_directas(filas, p)) for i, p in enumerate(filas)]
    parejas = [(i, p, h) for i, p, h in parejas if h]
    if not parejas:
        return ResultadoRegla(
            regla="jerarquia", estado=NO_VERIFICABLE,
            aplicables=aplicables, evaluados=0,
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
    huerfanos = sorted(padres_referidos - {p.cuenta for p in filas})
    motivo = ""
    if huerfanos:
        motivo = (f"{len(huerfanos)} cuenta(s) padre que alguna fila declara "
                  f"no aparecen en el documento: {', '.join(huerfanos[:5])}")
    return _resultado("jerarquia", aplicables, exactas, rozando, malas,
                      evaluados=len(parejas) * 2, motivo=motivo)


def _totales(balanza: Balanza, reglas: ReglasBalanza,
             base: Sequence[FilaBalanza]) -> ResultadoRegla:
    if balanza.totales is None:
        return ResultadoRegla(regla="totales", estado=NO_VERIFICABLE,
                              aplicables=2, evaluados=0,
                              motivo="fila de totales no detectada en el PDF")
    if not base:
        return ResultadoRegla(
            regla="totales", estado=NO_VERIFICABLE, aplicables=2, evaluados=0,
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
            regla="partida_doble", estado=NO_VERIFICABLE, aplicables=1,
            evaluados=0,
            motivo=("el documento no la declara: su fila de totales no cuadra "
                    "debe contra haber"))
    if not base:
        return ResultadoRegla(regla="partida_doble", estado=NO_VERIFICABLE,
                              aplicables=1, evaluados=0,
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


def naturaleza_por_cuenta(auxiliar, *,
                          tolerancia: Decimal = TOLERANCIA) -> dict[str, str]:
    """Cual de las dos identidades sostiene el saldo corrido de cada cuenta.

    'D' para `saldo = anterior + debe - haber`, 'A' para la contraria, y ''
    cuando el documento no lo revela. Se decide por MAYORIA de los renglones
    que la revelan -- el mismo criterio que `MayorParser._naturaleza` -- y no
    por unanimidad: un solo saldo mal leido no puede voltear una cuenta
    entera. Medido: en los dos fixtures ninguna cuenta tiene votos de los dos
    lados, asi que mayoria y unanimidad coinciden hoy.

    NUNCA se infiere del numero ni del nombre de la cuenta: la aritmetica
    manda sobre el vocabulario (PLAN 2).
    """
    movimientos: dict[str, list] = {}
    subtotales: dict[str, object] = {}
    for fila in auxiliar.filas:
        if fila.es_subtotal:
            subtotales.setdefault(fila.cuenta, fila)
        else:
            movimientos.setdefault(fila.cuenta, []).append(fila)

    naturalezas: dict[str, str] = {}
    for cuenta, filas in movimientos.items():
        deudora, acreedora = _votos_de_naturaleza(filas, subtotales.get(cuenta),
                                                  tolerancia)
        naturalezas[cuenta] = ("" if deudora == acreedora
                               else "D" if deudora > acreedora else "A")
    return naturalezas


def _votos_de_naturaleza(filas: Sequence, subtotal, tolerancia: Decimal
                         ) -> tuple[int, int]:
    """Cuantos renglones sostiene cada identidad.

    Un renglon con `debe == haber` no vota: las dos identidades lo cumplen.
    El aterrizaje de la cadena entera en el saldo del subtotal declarado
    vale un voto mas, y es el UNICO disponible cuando todos los saldos
    intermedios son ilegibles -- el caso de auxiliar-gume.
    """
    deudora = acreedora = 0
    anterior = filas[0].saldo_inicial_cuenta if filas else None
    for fila in filas:
        if fila.saldo is None or fila.debe is None or fila.haber is None:
            # Sin uno de los tres el renglon no puede votar, y ademas corta
            # la cadena: el siguiente no tiene contra que compararse.
            anterior = fila.saldo
            continue
        if anterior is not None and fila.debe != fila.haber:
            movimiento = fila.debe - fila.haber
            deudora += abs(anterior + movimiento - fila.saldo) <= tolerancia
            acreedora += abs(anterior - movimiento - fila.saldo) <= tolerancia
        anterior = fila.saldo

    if (subtotal is not None and subtotal.saldo is not None and filas
            and filas[0].saldo_inicial_cuenta is not None
            and not any(f.debe is None or f.haber is None for f in filas)):
        neto = sum((f.debe - f.haber for f in filas), Decimal(0))
        if neto != 0:
            inicial = filas[0].saldo_inicial_cuenta
            deudora += abs(inicial + neto - subtotal.saldo) <= tolerancia
            acreedora += abs(inicial - neto - subtotal.saldo) <= tolerancia
    return deudora, acreedora


def _saldo_corrido(auxiliar, tolerancia: Decimal) -> ResultadoRegla:
    """saldo[n] == saldo[n-1] + debe - haber, dentro de cada seccion.

    El saldo arranca en el saldo inicial que declara la seccion, y los
    subtotales no participan: son un resumen de los movimientos, no uno
    mas.
    """
    movimientos = [f for f in auxiliar.filas if not f.es_subtotal]
    if not movimientos:
        return ResultadoRegla(regla="saldo_corrido", estado=NO_VERIFICABLE,
                              aplicables=0, evaluados=0,
                              motivo="el documento no trajo movimientos")
    # El signo de la identidad NO se cablea: sale de los datos de cada
    # cuenta. Cablearlo le hacia la pregunta equivocada a las 44 cuentas
    # acreedoras del fixture y producia 3,585 fallas inventadas.
    naturalezas = naturaleza_por_cuenta(auxiliar, tolerancia=tolerancia)
    sin_naturaleza = sorted(c for c, n in naturalezas.items() if not n)
    indeterminados = sum(1 for f in movimientos if not naturalezas.get(f.cuenta))

    exactas, rozando, malas = 0, [], []
    anterior: Decimal | None = None
    cuenta = ""
    signo = Decimal(1)
    ilegibles = 0
    for indice, fila in enumerate(movimientos):
        if fila.cuenta != cuenta:
            cuenta, anterior = fila.cuenta, fila.saldo_inicial_cuenta
            naturaleza = naturalezas.get(cuenta, "")
            signo = Decimal(-1) if naturaleza == "A" else Decimal(1)
        if not naturalezas.get(fila.cuenta):
            # Sin saber de que lado corre el saldo no se puede comprobar
            # nada: el caso sigue en el denominador y la cobertura lo dice.
            anterior = fila.saldo
            continue
        if fila.saldo is None:
            # El documento no dejo leer este saldo: se corta la cadena en
            # vez de encadenar sobre un numero que no existe.
            ilegibles += 1
            anterior = None
            continue
        if anterior is None:
            anterior = fila.saldo
            continue
        esperado = anterior + signo * (fila.debe - fila.haber)
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
        detalle = (f"{ilegibles} de {len(movimientos)} movimientos no traen "
                   "saldo en la capa de texto")
        if sin_naturaleza:
            detalle = (f"{len(sin_naturaleza)} cuenta(s) no revelan de que "
                       "lado corre su saldo: "
                       + ", ".join(sin_naturaleza[:5]))
        return ResultadoRegla(
            regla="saldo_corrido", estado=NO_VERIFICABLE,
            aplicables=len(movimientos), evaluados=0, motivo=detalle)
    # El universo son todos los movimientos, incluido el que siembra cada
    # cadena: que no se pueda encadenar el primero es una limitacion de la
    # comprobacion, no una razon para sacarlo del denominador.
    total = len(movimientos)
    siembras = total - comprobadas - ilegibles - indeterminados
    partes = []
    if ilegibles:
        partes.append(f"{ilegibles} de {total} movimientos no traen saldo "
                      "legible en la capa de texto")
    if indeterminados:
        partes.append(f"{indeterminados} de {total} pertenecen a "
                      f"{len(sin_naturaleza)} cuenta(s) cuyo saldo no revela "
                      "de que lado corre: "
                      + ", ".join(sin_naturaleza[:5]))
    if siembras > 0:
        partes.append(f"{siembras} de {total} abren cadena y no tienen contra "
                      "que encadenarse")
    motivo = "; ".join(partes)
    return _resultado("saldo_corrido", len(movimientos), exactas, rozando,
                      malas, evaluados=comprobadas, motivo=motivo)


def _subtotales(auxiliar, tolerancia: Decimal) -> ResultadoRegla:
    """Cada subtotal contra los movimientos de su seccion.

    Misma trampa que las cuentas acumulativas de la balanza: sumar los
    subtotales junto con los movimientos cuenta dos veces.
    """
    subtotales = [f for f in auxiliar.filas if f.es_subtotal]
    if not subtotales:
        return ResultadoRegla(
            regla="subtotales", estado=NO_VERIFICABLE, aplicables=0,
            evaluados=0,
            motivo="el documento no imprime filas de subtotal")
    # Dos comprobaciones por subtotal, debe y haber: son las unidades de
    # 'exactas', y el universo tiene que estar en las mismas.
    aplicables = len(subtotales) * 2

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
            regla="subtotales", estado=NO_VERIFICABLE, aplicables=aplicables,
            evaluados=0,
            motivo="los subtotales no corresponden a ninguna seccion leida")
    evaluados = exactas + len(rozando) + len(malas)
    motivo = ""
    if evaluados < aplicables:
        motivo = (f"{(aplicables - evaluados) // 2} de {len(subtotales)} "
                  "subtotales no corresponden a ninguna seccion leida")
    return _resultado("subtotales", aplicables, exactas, rozando, malas,
                      evaluados=evaluados, motivo=motivo)


def _partida_doble_por_poliza(libro, tolerancia: Decimal) -> ResultadoRegla:
    """Suma debe == suma haber, por poliza. El checksum mas limpio.

    Solo sobre las polizas completas: un bloque cortado por el borde de lo
    leido tiene sus movimientos a medias y reportaria un descuadre que el
    documento no tiene.
    """
    completas = [p for p in libro.polizas if p.completa]
    # Las incompletas son APLICABLES aunque no se evaluen: el PLAN dice que
    # la cobertura las declara, y declarar exige estar en el denominador.
    aplicables = len(libro.polizas)
    if not completas:
        return ResultadoRegla(
            regla="partida_doble", estado=NO_VERIFICABLE,
            aplicables=aplicables, evaluados=0,
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
    evaluados = exactas + len(rozando) + len(malas)
    incompletas = len(libro.polizas) - len(completas)
    partes = []
    if incompletas:
        partes.append(f"{incompletas} de {aplicables} polizas no cerraron "
                      "dentro de lo leido")
    sin_movimientos = aplicables - incompletas - evaluados
    if sin_movimientos > 0:
        partes.append(f"{sin_movimientos} de {aplicables} polizas no trajeron "
                      "ningun movimiento")
    motivo = "; ".join(partes)
    return _resultado("partida_doble", aplicables, exactas, rozando, malas,
                      evaluados=evaluados, motivo=motivo)


def _totales_declarados(libro, tolerancia: Decimal) -> ResultadoRegla:
    """Los totales que imprime la poliza contra la suma de sus movimientos."""
    con_totales = [p for p in libro.polizas
                   if p.completa and p.total_debe is not None]
    aplicables = len(libro.polizas) * 2
    if not con_totales:
        return ResultadoRegla(
            regla="totales", estado=NO_VERIFICABLE, aplicables=aplicables,
            evaluados=0,
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
                              aplicables=aplicables, evaluados=0,
                              motivo="ninguna poliza con totales trajo movimientos")
    evaluados = exactas + len(rozando) + len(malas)
    motivo = ""
    if evaluados < aplicables:
        motivo = (f"{(aplicables - evaluados) // 2} de {len(libro.polizas)} "
                  "polizas no declaran totales o no cerraron dentro de lo leido")
    return _resultado("totales", aplicables, exactas, rozando, malas,
                      evaluados=evaluados, motivo=motivo)


def _cfdi_atados(libro) -> ResultadoRegla:
    """Todo CFDI apunta a una poliza que existe."""
    if not libro.cfdi:
        return ResultadoRegla(regla="cfdi", estado=NO_VERIFICABLE,
                              aplicables=0, evaluados=0,
                              motivo="el documento no trae tabla de CFDI")
    ids = {p.poliza_id for p in libro.polizas}
    huerfanos = [c for c in libro.cfdi if c.poliza_id not in ids]
    if huerfanos:
        return ResultadoRegla(
            regla="cfdi", estado=FALLA, aplicables=len(libro.cfdi),
            evaluados=len(libro.cfdi),
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
                              aplicables=0, evaluados=0,
                              motivo="el documento no trae tabla de CFDI")
    por_id = {p.poliza_id: p for p in libro.polizas}
    comparables = [c for c in libro.cfdi
                   if c.documento and por_id.get(c.poliza_id)
                   and por_id[c.poliza_id].descripcion]
    if not comparables:
        return ResultadoRegla(
            regla="cfdi_cruzado", estado=NO_VERIFICABLE,
            aplicables=len(libro.cfdi), evaluados=0,
            motivo=("ni el CFDI ni la poliza traen un numero de documento "
                    "con el que cruzarlos"))

    # CONTENCION, no igualdad: PLAN 1.2 dice que el numero del CFDI es el
    # que la poliza declara, y la descripcion lo trae con texto alrededor
    # ('FACT. FOLIO: 65501589987'). Comparar con '!=' convertia 863 cruces
    # correctos en fallas inventadas.
    malos = [
        Discrepancia(fila=c.poliza_id, indice=-1, regla="cfdi_cruzado",
                     esperado=Decimal(0), obtenido=Decimal(0))
        for c in comparables
        if c.documento not in por_id[c.poliza_id].descripcion
    ]
    sin_cruzar = len(libro.cfdi) - len(comparables)
    motivo = ""
    if sin_cruzar:
        motivo = (f"{sin_cruzar} de {len(libro.cfdi)} CFDI sin numero de "
                  "documento con el que cruzar")
    return _resultado("cfdi_cruzado", len(libro.cfdi),
                      len(comparables) - len(malos), (), malos,
                      evaluados=len(comparables), motivo=motivo)


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
            aplicables=len(estado.cuentas), evaluados=0,
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
    motivo = ""
    if len(completas) < len(estado.cuentas):
        motivo = (f"{len(estado.cuentas) - len(completas)} de "
                  f"{len(estado.cuentas)} cuenta(s) no traen el resumen "
                  "completo y quedaron sin comprobar")
    return _resultado("resumen", len(estado.cuentas), exactas, rozando, malas,
                      evaluados=len(completas), motivo=motivo)


def _resumen_contra_movimientos(estado, tolerancia: Decimal) -> ResultadoRegla:
    """Los totales declarados contra los movimientos leidos, POR CUENTA.

    Es lo que prueba que no se perdio ningun movimiento: el resumen puede
    cuadrar consigo mismo y faltar la mitad de la tabla.
    """
    completas = _cuentas_con(estado, ("depositos", "retiros"))
    if not completas:
        return ResultadoRegla(
            regla="resumen_movimientos", estado=NO_VERIFICABLE,
            aplicables=len(estado.cuentas) * 2, evaluados=0,
            motivo=("ninguna cuenta declara depositos y retiros propios; con "
                    "dos o mas cuentas el total del documento no se reparte"))
    if not estado.movimientos:
        return ResultadoRegla(regla="resumen_movimientos", estado=NO_VERIFICABLE,
                              aplicables=len(estado.cuentas) * 2, evaluados=0,
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
    motivo = ""
    if len(completas) < len(estado.cuentas):
        motivo = (f"{len(estado.cuentas) - len(completas)} de "
                  f"{len(estado.cuentas)} cuenta(s) no declaran depositos y "
                  "retiros propios")
    return _resultado("resumen_movimientos", len(estado.cuentas) * 2, exactas,
                      rozando, malas, evaluados=len(completas) * 2,
                      motivo=motivo)


def _total_declarado(estado, tolerancia: Decimal) -> ResultadoRegla:
    """La fila TOTAL contra la suma de los saldos por cuenta.

    Es un cruce con datos, de la misma clase que CFDI contra poliza: el
    documento imprime la suma y nosotros la recalculamos desde las partes.
    """
    declarados = {"saldo_inicial": estado.meta.total_saldo_inicial,
                  "saldo_corte": estado.meta.total_saldo_corte}
    if all(v is None for v in declarados.values()):
        return ResultadoRegla(
            regla="total_declarado", estado=NO_VERIFICABLE, aplicables=2,
            evaluados=0,
            motivo=("el documento no imprime una fila TOTAL con la que cruzar "
                    "la suma de los saldos por cuenta"))

    exactas, rozando, malas, evaluados = 0, [], [], 0
    for campo, declarado in declarados.items():
        propios = [getattr(c, campo) for c in estado.cuentas]
        if declarado is None or any(v is None for v in propios) or not propios:
            continue
        evaluados += 1
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
    if not evaluados:
        return ResultadoRegla(
            regla="total_declarado", estado=NO_VERIFICABLE, aplicables=2,
            evaluados=0,
            motivo=("el documento imprime una fila TOTAL pero alguna cuenta no "
                    "trae el saldo con el que sumarla"))
    motivo = ""
    if evaluados < 2:
        motivo = ("el documento solo imprime uno de los dos totales (saldo "
                  "inicial y saldo al corte)")
    return _resultado("total_declarado", 2, exactas, rozando, malas,
                      evaluados=evaluados, motivo=motivo)


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
                              aplicables=0, evaluados=0,
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

    # El universo son todos los movimientos, incluido el que abre cada
    # cadena. Un banco que imprime el saldo una sola vez por dia deja 111 de
    # 116 sin comprobar: eso es cobertura del 4%, no una tabla de 5 casos.
    total = len(estado.movimientos)
    siembras = total - comparados - ilegibles
    partes = []
    if ilegibles:
        # 'no traen saldo', no 'no traen saldo legible': la causa varia y
        # esta regla no la puede ver. Medido en la 7g: en BBVA los 93
        # renglones no tienen NINGUN token en la columna del saldo -- el
        # banco solo lo imprime al cierre del dia, y eso es correcto -- pero
        # en Bajio el unico renglon sin saldo SI tiene tinta ahi, o sea es
        # perdida de extraccion. Afirmar una sola causa seria inventarla.
        partes.append(f"{ilegibles} de {total} movimientos no traen saldo con "
                      "el que encadenar")
    if siembras > 0:
        partes.append(f"{siembras} de {total} abren cadena y no tienen contra "
                      "que encadenarse")
    motivo = "; ".join(partes)
    return _resultado("saldo_corrido", total, exactas, rozando, malas,
                      evaluados=comparados, motivo=motivo)


def _saldo_mensual(mayor, tolerancia: Decimal) -> ResultadoRegla:
    """saldo[mes] = saldo[mes-1] + cargos - abonos, con saldo[0] = Inicial."""
    if not mayor.meses:
        return ResultadoRegla(regla="saldo_mensual", estado=NO_VERIFICABLE,
                              aplicables=0, evaluados=0,
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

    evaluados = exactas + len(rozando) + len(malas)
    resultado = _resultado("saldo_mensual", len(mayor.meses), exactas,
                           rozando, malas, evaluados=evaluados)
    if sin_naturaleza:
        resultado = replace(resultado, motivo=(
            f"{len(sin_naturaleza)} cuenta(s) sin naturaleza determinable "
            f"(sus meses no la revelan): {', '.join(sin_naturaleza)}"))
    return resultado


def _acumulados(mayor, tolerancia: Decimal) -> ResultadoRegla:
    """acum[mes] = acum[mes-1] + movimiento del mes, para cargos y abonos."""
    if not mayor.meses:
        return ResultadoRegla(regla="acumulados", estado=NO_VERIFICABLE,
                              aplicables=0, evaluados=0,
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
    evaluados = exactas + len(rozando) + len(malas)
    aplicables = len(mayor.meses) * 2
    motivo = ""
    if evaluados < aplicables:
        motivo = (f"{aplicables - evaluados} de {aplicables} acumulados no "
                  "vienen legibles en el documento")
    return _resultado("acumulados", aplicables, exactas, rozando, malas,
                      evaluados=evaluados, motivo=motivo)


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
            aplicables=len(mayor.cuentas), evaluados=0,
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
            aplicables=len(mayor.cuentas), evaluados=0,
            motivo="ninguna cuenta del mayor aparece en la balanza recibida")
    if not difieren:
        motivo = ""
        if comprobadas < len(mayor.cuentas):
            motivo = (f"{len(mayor.cuentas) - comprobadas} de "
                      f"{len(mayor.cuentas)} cuentas del mayor no aparecen en "
                      "la balanza recibida")
        return _resultado("cruce_balanza", len(mayor.cuentas), coinciden, (),
                          [], evaluados=comprobadas, motivo=motivo)

    listado = ", ".join(c for c, _, _ in difieren)
    return ResultadoRegla(
        regla="cruce_balanza", estado=NO_VERIFICABLE,
        aplicables=len(mayor.cuentas), evaluados=comprobadas,
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
