"""M1 (fase 8d): por que `mayor-proactivity` produce basura.

Procesa sin reventar -- 276 paginas, 220 s en SERVIDORSIST -- y el Excel
sale con `nombre_cuenta` lleno de numeros de banco, `naturaleza` vacia,
todos los importes en cero y un `(ENERO` con parentesis suelto. La
pregunta es cual de las tres capas lo produce: la estrategia de
extraccion, el layout, o el parser.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from conftest import REAL_PDFS  # noqa: E402

from contapdf.extract import strategy  # noqa: E402
from contapdf.layout.lines import group  # noqa: E402
from contapdf.parsers.base import detectar_layout  # noqa: E402
from contapdf.parsers.mayor import _MESES, _orden_de  # noqa: E402
from contapdf.pipeline import procesar_mayor  # noqa: E402

nombre = sys.argv[1] if len(sys.argv) > 1 else "mayor-proactivity"
ruta = REAL_PDFS[nombre]

# --- 1. La estrategia --------------------------------------------------
decision = strategy.decidir(ruta)
print("=" * 72)
print("1. ESTRATEGIA")
print("=" * 72)
print(f"  elegida   {decision.estrategia}")
print(f"  motivo    {decision.motivo}")
print(f"  senales   {decision.senales}")

documento, _ = strategy.extraer(ruta, page_numbers=list(range(1, 9)))
paginas = list(documento.open_pages())
print(f"  paginas leidas para el diagnostico: {len(paginas)}")
print(f"  palabras en las 8 primeras: {sum(len(p.words) for p in paginas)}")
texto = " ".join(w.text for p in paginas for w in p.words)
print(f"  el texto sale legible: "
      f"{'si' if sum(c.isalpha() for c in texto) > len(texto) * 0.2 else 'NO'}")
print(f"  muestra: {texto[:160]!r}")

# --- 2. El layout ------------------------------------------------------
print()
print("=" * 72)
print("2. LAYOUT")
print("=" * 72)
layout = detectar_layout(paginas[:4])
if layout is None:
    print("  detectar_layout devolvio None: no se reconocio tabla")
else:
    print(f"  columnas detectadas {len(layout.columns)}")
    for c in layout.columns:
        print(f"    idx={c.index} {c.align:5} x[{c.x_min:7.1f}..{c.x_max:7.1f}]"
              f" n={c.support:4} header={c.header!r}")
    print(f"  columnas de monto   {len(layout.montos)}")

# --- 3. El parser ------------------------------------------------------
print()
print("=" * 72)
print("3. QUE VE EL PARSER: renglones que toma por un MES")
print("=" * 72)
print(f"  los meses que el parser conoce: {list(_MESES)}")
tokens = Counter()
for p in paginas:
    for line in group(p.words):
        if line.words and _orden_de(line.words[0].text):
            tokens[line.words[0].text] += 1
print(f"  renglones cuyo PRIMER token normaliza a un mes, en 8 paginas: "
      f"{sum(tokens.values())}")
print(f"  los tokens, tal cual vienen impresos: {dict(tokens)}")
print()
print("  `_orden_de` compara con `normalizar()`, que quita la puntuacion:")
for muestra in ("(ENERO", "ENERO", "(ENERO)", "ENERO."):
    print(f"    _orden_de({muestra!r}) = {_orden_de(muestra)}")

# --- 4. La salida ------------------------------------------------------
print()
print("=" * 72)
print("4. LA SALIDA (documento completo)")
print("=" * 72)
resultado = procesar_mayor(ruta)
mayor = resultado.mayor
print(f"  cuentas {len(mayor.cuentas)}   meses {len(mayor.meses)}")
print()
print("  primeras cuentas:")
for cuenta in mayor.cuentas[:5]:
    print(f"    cuenta={cuenta.cuenta!r} naturaleza={cuenta.naturaleza!r}")
    print(f"      nombre={cuenta.nombre_cuenta[:110]!r}")
    print(f"      saldo_inicial={cuenta.saldo_inicial} "
          f"saldo_final={cuenta.saldo_final} "
          f"cargos={cuenta.total_cargos} abonos={cuenta.total_abonos}")
print()
print("  primeros 'meses':")
for mes in mayor.meses[:6]:
    print(f"    cuenta={mes.cuenta!r} orden={mes.orden} periodo={mes.periodo!r}"
          f" cargos={mes.cargos} abonos={mes.abonos} saldo={mes.saldo}"
          f" acum=({mes.acum_cargos}, {mes.acum_abonos}) pag={mes.pagina}")
en_cero = sum(1 for m in mayor.meses
              if m.cargos == 0 and m.abonos == 0 and not m.saldo)
print(f"  'meses' con cargos, abonos y saldo todos en cero/None: "
      f"{en_cero} de {len(mayor.meses)}")
sin_naturaleza = sum(1 for c in mayor.cuentas if not c.naturaleza)
print(f"  cuentas sin naturaleza: {sin_naturaleza} de {len(mayor.cuentas)}")
print(f"  cobertura: {resultado.cobertura.resumen()}")
