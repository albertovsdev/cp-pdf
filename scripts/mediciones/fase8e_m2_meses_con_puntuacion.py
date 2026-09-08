"""Fase 8e, objetivo 3: los meses legitimos, traen puntuacion pegada?

`_orden_de` compara tras `normalizar()`, y `normalizar()` quita la
puntuacion, asi que `_orden_de('(ENERO') == 1`. Endurecerlo arregla
`mayor-proactivity` -- pero si algun renglon de mes LEGITIMO de
`mayor-gume` trae puntuacion pegada, endurecerlo rompe el fixture bueno.
Esto lo mide antes de tocar nada.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from conftest import REAL_PDFS  # noqa: E402

from contapdf.extract import strategy  # noqa: E402
from contapdf.layout.lines import group  # noqa: E402
from contapdf.parsers.base import normalizar  # noqa: E402
from contapdf.parsers.mayor import _MESES, _orden_de  # noqa: E402
from contapdf.pipeline import procesar_mayor  # noqa: E402

_LIMPIOS = {m.upper() for m in _MESES}


def _clasificar(nombre: str) -> None:
    documento, _ = strategy.extraer(REAL_PDFS[nombre])
    tokens: Counter[str] = Counter()
    for page in documento.open_pages():
        for line in group(page.words):
            if line.words and _orden_de(line.words[0].text):
                tokens[line.words[0].text] += 1
    limpios = {t: n for t, n in tokens.items() if t.upper() in _LIMPIOS}
    sucios = {t: n for t, n in tokens.items() if t.upper() not in _LIMPIOS}
    print(f"=== {nombre} ===")
    print(f"  renglones cuyo primer token normaliza a un mes: {sum(tokens.values())}")
    print(f"  con el nombre del mes LIMPIO   {sum(limpios.values()):5}"
          f"  tokens distintos: {sorted(limpios)}")
    print(f"  con puntuacion o basura pegada {sum(sucios.values()):5}"
          f"  tokens distintos: {sorted(sucios)}")
    for token in sorted(sucios):
        print(f"      {token!r} -> normalizar() -> {normalizar(token)!r}"
              f" -> _orden_de = {_orden_de(token)}   x{sucios[token]}")
    resultado = procesar_mayor(REAL_PDFS[nombre])
    print(f"  el parser produce: {len(resultado.mayor.cuentas)} cuentas, "
          f"{len(resultado.mayor.meses)} meses")
    for regla in resultado.cobertura.reglas:
        print(f"    {regla.regla:16} {regla.estado:15} "
              f"{regla.evaluados} de {regla.aplicables}")
    print()


for nombre in (sys.argv[1:] or ["mayor-gume", "mayor-proactivity"]):
    _clasificar(nombre)


# --- Segunda parte: si endurecer `_orden_de` no basta, que si discrimina --
# Medido arriba: de los 50 falsos positivos de `mayor-proactivity` solo 2
# traen puntuacion. Los otros 48 traen el nombre del mes LIMPIO dentro de
# una descripcion. Hacen falta criterios ESTRUCTURALES, y hay que
# comprobar que ninguno toca `mayor-gume`.
print("=" * 74)
print("HIPOTESIS QUE PODRIAN DISCRIMINAR, medidas en los dos documentos")
print("=" * 74)
for nombre in ("mayor-gume", "mayor-proactivity"):
    r = procesar_mayor(REAL_PDFS[nombre])
    mayor = r.mayor
    por_cuenta: Counter[str] = Counter(m.cuenta for m in mayor.meses)
    repetidos = 0
    for cuenta in por_cuenta:
        ordenes = [m.orden for m in mayor.meses if m.cuenta == cuenta]
        repetidos += len(ordenes) - len(set(ordenes))
    con_importe = sum(1 for m in mayor.meses
                      if m.cargos or m.abonos or m.saldo is not None)
    con_acumulado = sum(1 for m in mayor.meses
                        if m.acum_cargos is not None or m.acum_abonos is not None)
    print(f"--- {nombre} ---")
    print(f"  cuentas {len(mayor.cuentas)}  meses {len(mayor.meses)}")
    print(f"  H1 meses por cuenta: max {max(por_cuenta.values(), default=0)}"
          f"  (un mayor da 12 como mucho)")
    print(f"  H2 meses con `orden` repetido dentro de su cuenta: {repetidos}")
    print(f"  H3 meses con algun importe:      {con_importe} de {len(mayor.meses)}")
    print(f"  H4 meses con algun acumulado:    {con_acumulado} de {len(mayor.meses)}")
    print(f"  H5 cuentas con saldo_final leido: "
          f"{sum(1 for c in mayor.cuentas if c.saldo_final is not None)}"
          f" de {len(mayor.cuentas)}")
    print(f"  H6 cuentas con naturaleza determinada: "
          f"{sum(1 for c in mayor.cuentas if c.naturaleza)} de {len(mayor.cuentas)}")
