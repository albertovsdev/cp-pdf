"""Fase 8e, objetivo 4: cuantos sitios construyen o leen una `Discrepancia`.

El cambio de contrato hay que dimensionarlo antes de elegir la forma. Se
recorre `src/` y `tests/` con el AST y se cuentan tres cosas: quien la
CONSTRUYE (esos hay que tocarlos si el campo cambia de tipo), quien lee
`esperado`/`obtenido` (esos son los que hoy deciden por su cuenta), y quien
la formatea para una salida.
"""

from __future__ import annotations

import ast
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DESTINOS = (RAIZ / "src" / "contapdf", RAIZ / "tests")


def _recorrer():
    construyen: list[tuple[str, int]] = []
    leen: list[tuple[str, int, str]] = []
    for base in DESTINOS:
        for path in sorted(base.rglob("*.py")):
            arbol = ast.parse(path.read_text(encoding="utf-8"))
            relativa = path.relative_to(RAIZ)
            for nodo in ast.walk(arbol):
                if (isinstance(nodo, ast.Call)
                        and isinstance(nodo.func, ast.Name)
                        and nodo.func.id == "Discrepancia"):
                    construyen.append((str(relativa), nodo.lineno))
                if (isinstance(nodo, ast.Attribute)
                        and nodo.attr in ("esperado", "obtenido")):
                    leen.append((str(relativa), nodo.lineno, nodo.attr))
    return construyen, leen


construyen, leen = _recorrer()

print("=" * 74)
print("QUIEN CONSTRUYE UNA Discrepancia")
print("=" * 74)
por_fichero = Counter(f for f, _ in construyen)
for fichero, veces in sorted(por_fichero.items()):
    lineas = [str(n) for f, n in construyen if f == fichero]
    print(f"  {fichero:44} {veces:3}  lineas {', '.join(lineas)}")
nucleo = sum(v for f, v in por_fichero.items() if f.startswith("src/"))
print(f"  -> en el nucleo {nucleo}, en tests {sum(por_fichero.values()) - nucleo}")

print()
print("=" * 74)
print("QUIEN LEE .esperado / .obtenido")
print("=" * 74)
por_fichero = Counter(f for f, _, _ in leen)
for fichero, veces in sorted(por_fichero.items()):
    lineas = sorted({n for f, n, _ in leen if f == fichero})
    print(f"  {fichero:44} {veces:3}  lineas "
          f"{', '.join(str(n) for n in lineas)}")
nucleo = sum(v for f, v in por_fichero.items() if f.startswith("src/"))
print(f"  -> en el nucleo {nucleo}, en tests {sum(por_fichero.values()) - nucleo}")

print()
print("=" * 74)
print("LAS TRES SALIDAS")
print("=" * 74)
for fichero in ("src/contapdf/cli.py", "src/contapdf/export/excel.py",
                "src/contapdf/web/vista.py"):
    veces = sum(1 for f, _, _ in leen if f == fichero)
    print(f"  {fichero:44} lee esperado/obtenido {veces} veces")
