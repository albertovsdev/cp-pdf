"""Fase 8e, objetivo 2: declarado contra leido en `mayor` y `estado-cuenta`.

La 8d midio que la hoja `Cuentas` de los dos ensena lo que el documento
DECLARA sin lo que el sistema LEYO, y que en `mayor-gume` ya difiere 1
cuenta de 49. Antes de partir las columnas hay que saber, campo por campo,
cual es el declarado, cual el leido y en cuantas cuentas difieren: la 8d
solo comparo los totales de cargos y abonos, no el saldo final.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from conftest import REAL_PDFS  # noqa: E402

from contapdf.pipeline import procesar_estado_cuenta, procesar_mayor  # noqa: E402

_CERO = Decimal(0)


def _mayor(nombre: str) -> None:
    resultado = procesar_mayor(REAL_PDFS[nombre])
    mayor = resultado.mayor
    print(f"=== mayor: {nombre} ===")
    print(f"  cuentas {len(mayor.cuentas)}   meses {len(mayor.meses)}")
    difieren = {"total_cargos": [], "total_abonos": [], "saldo_final": []}
    sin_meses = 0
    for cuenta in mayor.cuentas:
        suyos = sorted((m for m in mayor.meses if m.cuenta == cuenta.cuenta),
                       key=lambda m: m.orden)
        if not suyos:
            sin_meses += 1
            continue
        # LEIDO = la suma de los meses. DECLARADO = lo que `_cerrar` toma
        # del acumulado del ultimo mes, que es lo que el documento imprime.
        suma_cargos = sum((m.cargos for m in suyos), _CERO)
        suma_abonos = sum((m.abonos for m in suyos), _CERO)
        # El saldo final leido es el de la cadena: inicial +/- movimiento.
        signo = Decimal(-1) if cuenta.naturaleza == "A" else Decimal(1)
        cadena = (cuenta.saldo_inicial
                  + signo * (suma_cargos - suma_abonos)
                  if cuenta.saldo_inicial is not None else None)
        for campo, declarado, leido in (
                ("total_cargos", cuenta.total_cargos, suma_cargos),
                ("total_abonos", cuenta.total_abonos, suma_abonos),
                ("saldo_final", cuenta.saldo_final, cadena)):
            if declarado is not None and leido is not None and declarado != leido:
                difieren[campo].append((cuenta.cuenta, declarado, leido))
    print(f"  cuentas sin meses (no comparables) {sin_meses}")
    for campo, casos in difieren.items():
        print(f"  {campo:14} difieren {len(casos)} de {len(mayor.cuentas)}")
        for nombre_c, dec, lei in casos[:5]:
            print(f"      {nombre_c}: declarado {dec}  leido {lei}"
                  f"  diferencia {dec - lei}")
    union = {c[0] for casos in difieren.values() for c in casos}
    print(f"  cuentas distintas afectadas: {len(union)} -> {sorted(union)}")
    print(f"  cobertura: {resultado.cobertura.resumen()}")
    print()


def _edocta(nombre: str) -> None:
    resultado = procesar_estado_cuenta(REAL_PDFS[nombre])
    estado = resultado.estado
    difieren = 0
    sin_declarar = 0
    print(f"=== estado-cuenta: {nombre} ===")
    for cuenta in estado.cuentas:
        suyos = estado.movimientos_de(cuenta.num_cuenta)
        dep = sum((m.deposito or _CERO for m in suyos), _CERO)
        ret = sum((m.retiro or _CERO for m in suyos), _CERO)
        saldos = [m.saldo for m in suyos if m.saldo is not None]
        corte = saldos[-1] if saldos else None
        for campo, declarado, leido in (("depositos", cuenta.depositos, dep),
                                        ("retiros", cuenta.retiros, ret),
                                        ("saldo_corte", cuenta.saldo_corte, corte)):
            if declarado is None or leido is None:
                sin_declarar += 1
                continue
            if declarado != leido:
                difieren += 1
                print(f"    {cuenta.num_cuenta} {campo}: declarado {declarado}"
                      f"  leido {leido}")
    print(f"  cuentas {len(estado.cuentas)}  movimientos {len(estado.movimientos)}")
    print(f"  campos que difieren {difieren}; sin cifra con que comparar "
          f"{sin_declarar}")
    print(f"  cobertura: {resultado.cobertura.resumen()}")
    print()


for nombre in ("mayor-gume",):
    _mayor(nombre)
for nombre in ("edocta", "edocta-bbva", "edocta-julio-banorte", "edocta-bajio"):
    _edocta(nombre)
