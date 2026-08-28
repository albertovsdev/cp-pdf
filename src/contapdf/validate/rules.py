"""Reglas aritmeticas: cada documento trae su propio checksum.

Las reglas se DECLARAN por formato. Un documento con columnas deudor y
acreedor separadas y otro con una sola columna con signo no se validan
igual, y cablear uno de los dos deja al otro fuera.

Devuelve discrepancias. No lanza excepciones y no imprime: quien llama
decide si entrega el Excel marcado o rechaza el documento.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
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

CUADRA = "cuadra"
FALLA = "falla"
NO_VERIFICABLE = "no_verificable"


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
