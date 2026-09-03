"""M3 (fase 8b), segunda parte: QUE forma tiene la perdida en diario-general.

«Se pierden renglones» y «los importes se leen mal» predicen cosas
distintas. Si se perdieran renglones, en el haber tambien faltaria; se lee
de MAS. Aqui se separan las dos.
"""
import sys
from collections import Counter
from decimal import Decimal

sys.path.insert(0, "tests")
from conftest import REAL_PDFS

from contapdf.pipeline import procesar_polizas

res = procesar_polizas(REAL_PDFS["diario-general"])
libro = res.libro

leido = {}
cuantos = Counter()
for m in libro.movimientos:
    d, h = leido.get(m.poliza_id, (Decimal(0), Decimal(0)))
    leido[m.poliza_id] = (d + (m.debe or 0), h + (m.haber or 0))
    cuantos[m.poliza_id] += 1

clases = Counter()
fallidas = []
for p in libro.polizas:
    ld, lh = leido.get(p.poliza_id, (Decimal(0), Decimal(0)))
    dd = p.total_debe if p.total_debe is not None else ld
    dh = p.total_haber if p.total_haber is not None else lh
    if dd == ld and dh == lh:
        continue
    fallidas.append(p.poliza_id)
    lado = ("debe " + ("corto" if dd > ld else "sobra" if dd < ld else "ok"),
            "haber " + ("corto" if dh > lh else "sobra" if dh < lh else "ok"))
    clases[lado] += 1

print(f"polizas fallidas: {len(fallidas)}")
for lado, n in clases.most_common():
    print(f"  {lado[0]:<12} {lado[1]:<12} {n}")

print()
print("--- renglones que absorbieron dos importes ---")
ambos = [m for m in libro.movimientos if (m.debe or 0) and (m.haber or 0)]
print(f"movimientos con debe Y haber distintos de cero: {len(ambos)} "
      f"de {len(libro.movimientos)}")
en_fallidas = sum(1 for m in ambos if m.poliza_id in set(fallidas))
print(f"  de ellos, en polizas fallidas: {en_fallidas}")

print()
print("--- tamano de las polizas ---")
todas = [cuantos[p.poliza_id] for p in libro.polizas]
malas = [cuantos[i] for i in fallidas]
todas.sort(); malas.sort()
print(f"movimientos por poliza, mediana: todas {todas[len(todas)//2]}, "
      f"fallidas {malas[len(malas)//2] if malas else '-'}")
print(f"  maximo: todas {todas[-1]}, fallidas {malas[-1] if malas else '-'}")
print(f"  polizas sin ningun movimiento: {sum(1 for n in todas if n == 0)}")
