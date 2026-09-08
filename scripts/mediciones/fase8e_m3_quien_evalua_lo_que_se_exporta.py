"""Fase 8e: las dos comprobaciones que el orquestador pidio antes del obj. 2.

1. Las 4 `dentro de tolerancia` de `saldo_mensual` en `mayor-gume`, son las
   mismas 4 cuentas donde `saldo_final` declarado difiere de la cadena?
2. Hay alguna REGLA que evalue la identidad que se va a exportar --el total
   declarado de la cuenta contra la suma de sus meses--? Si ninguna la
   evalua, la hoja ensenaria un descuadre que `Validacion` no menciona: la
   misma contradiccion entre salidas, por el otro lado.
3. Objetivo 3: de los 588 renglones de mes de `mayor-gume`, cuantos traen
   al menos un importe NO NULO NI CERO. Es el margen de la guarda.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from conftest import REAL_PDFS  # noqa: E402

from contapdf.pipeline import procesar_mayor  # noqa: E402

_CERO = Decimal(0)
resultado = procesar_mayor(REAL_PDFS["mayor-gume"])
mayor, cobertura = resultado.mayor, resultado.cobertura


def _regla(nombre):
    return next(r for r in cobertura.reglas if r.regla == nombre)


print("=" * 74)
print("1. Las 4 'dentro de tolerancia' de saldo_mensual contra las 4 de saldo_final")
print("=" * 74)
mensual = _regla("saldo_mensual")
print(f"  saldo_mensual: {mensual.evaluados} de {mensual.aplicables} evaluados, "
      f"{mensual.exactas} exactas, {len(mensual.con_tolerancia)} dentro de "
      f"tolerancia, {len(mensual.discrepancias)} con diferencia")
print(f"  las que rozan: {list(mensual.con_tolerancia)}")
cuentas_tolerancia = {c.split()[0] for c in mensual.con_tolerancia}

difieren_final = []
for cuenta in mayor.cuentas:
    suyos = [m for m in mayor.meses if m.cuenta == cuenta.cuenta]
    if not suyos or cuenta.saldo_inicial is None or cuenta.saldo_final is None:
        continue
    signo = Decimal(-1) if cuenta.naturaleza == "A" else Decimal(1)
    cadena = cuenta.saldo_inicial + signo * (
        sum((m.cargos for m in suyos), _CERO) - sum((m.abonos for m in suyos), _CERO))
    if cadena != cuenta.saldo_final:
        difieren_final.append(cuenta.cuenta)
print(f"  cuentas donde saldo_final difiere de la cadena: {sorted(difieren_final)}")
print(f"  cuentas nombradas por saldo_mensual/tolerancia:  "
      f"{sorted(cuentas_tolerancia)}")
coinciden = set(difieren_final) == cuentas_tolerancia
print(f"  >>> SON LAS MISMAS: {'SI' if coinciden else 'NO -- PARAR Y AVISAR'}")

print()
print("=" * 74)
print("2. Quien evalua el total declarado de la cuenta contra la suma de sus meses")
print("=" * 74)
print("  reglas de evaluar_mayor:")
for r in cobertura.reglas:
    print(f"    {r.regla:16} {r.estado:15} {r.evaluados} de {r.aplicables}, "
          f"{r.exactas} exactas, {len(r.con_tolerancia)} rozando, "
          f"{len(r.discrepancias)} con diferencia")

acum = _regla("acumulados")
print()
print("  `acumulados` comprueba acum[n] == acum[n-1] + movimiento[n], encadenado")
print("  desde cero. Por induccion, acum[ultimo] == suma de los meses SI todos")
print("  los pasos cuadran, y `_cerrar` toma el total de la cuenta de ese")
print("  acum[ultimo]. O sea: la identidad que se va a exportar SI la evalua,")
print("  pero paso a paso y CON TOLERANCIA.")
print(f"  las que rozan en acumulados: {list(acum.con_tolerancia)}")
cuentas_acum = {c.split()[0] for c in acum.con_tolerancia}

difieren_totales = []
for cuenta in mayor.cuentas:
    suyos = [m for m in mayor.meses if m.cuenta == cuenta.cuenta]
    if not suyos:
        continue
    for campo, declarado, leido in (
            ("cargos", cuenta.total_cargos, sum((m.cargos for m in suyos), _CERO)),
            ("abonos", cuenta.total_abonos, sum((m.abonos for m in suyos), _CERO))):
        if declarado is not None and declarado != leido:
            difieren_totales.append((cuenta.cuenta, campo, declarado, leido))
print()
print(f"  cuentas donde el TOTAL declarado difiere de la suma: "
      f"{len(difieren_totales)}")
for c, campo, dec, lei in difieren_totales:
    print(f"    {c} {campo}: declarado {dec}  leido {lei}  dif {dec - lei}")
    print(f"      esa cuenta esta nombrada por acumulados/tolerancia: "
          f"{'SI' if c in cuentas_acum else 'NO'}")
    print(f"      esa cuenta esta nombrada por saldo_mensual/tolerancia: "
          f"{'SI' if c in cuentas_tolerancia else 'NO'}")

print()
print("=" * 74)
print("3. Objetivo 3: margen de la guarda en mayor-gume")
print("=" * 74)
for nombre in ("mayor-gume", "mayor-proactivity"):
    m = procesar_mayor(REAL_PDFS[nombre]).mayor if nombre != "mayor-gume" else mayor
    # NO NULO NI CERO, que es lo que se pidio: un saldo de 0.00 no es un importe.
    con_importe = sum(1 for x in m.meses
                      if x.cargos or x.abonos or (x.saldo is not None and x.saldo))
    con_acum = sum(1 for x in m.meses
                   if (x.acum_cargos is not None and x.acum_cargos)
                   or (x.acum_abonos is not None and x.acum_abonos))
    print(f"  {nombre:20} meses {len(m.meses):4}  con importe no nulo ni cero "
          f"{con_importe:4}  con acumulado no nulo ni cero {con_acum:4}")
