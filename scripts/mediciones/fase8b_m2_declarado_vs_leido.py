"""M2 y M3 (fase 8b) sobre poliza.pdf.

M2: de donde sale la cifra de la hoja `Polizas` -- del TOTAL declarado por
    el documento o de la suma de los movimientos que se leyeron.
M3: donde se pierden los importes: cuantos renglones abren cuenta, cuantos
    movimientos salieron, y cuanto dinero falta en total.
"""
import sys
from collections import Counter
from decimal import Decimal

sys.path.insert(0, "tests")
from conftest import REAL_PDFS

from contapdf.pipeline import procesar_polizas

ruta = REAL_PDFS[sys.argv[1] if len(sys.argv) > 1 else "poliza"]
res = procesar_polizas(ruta)
diario = res.libro

por_poliza = {}
for m in diario.movimientos:
    d, h = por_poliza.get(m.poliza_id, (Decimal(0), Decimal(0)))
    por_poliza[m.poliza_id] = (d + (m.debe or 0), h + (m.haber or 0))

print(f"polizas      {len(diario.polizas)}")
print(f"movimientos  {len(diario.movimientos)}")

difieren = corto = exceso = 0
falta_debe = Decimal(0)
testigos = []
for p in diario.polizas:
    leido_d, leido_h = por_poliza.get(p.poliza_id, (Decimal(0), Decimal(0)))
    dec_d = p.total_debe if p.total_debe is not None else leido_d
    dec_h = p.total_haber if p.total_haber is not None else leido_h
    if dec_d != leido_d or dec_h != leido_h:
        difieren += 1
        falta_debe += dec_d - leido_d
        if dec_d > leido_d:
            corto += 1
        else:
            exceso += 1
        if len(testigos) < 3:
            testigos.append((p.folio or p.descripcion, dec_d, leido_d,
                             dec_h, leido_h))

print()
print("--- M2: declarado contra suma de movimientos ---")
print(f"polizas donde difieren: {difieren} de {len(diario.polizas)}")
print(f"  el declarado supera lo leido: {corto}")
print(f"  lo leido supera al declarado: {exceso}")
print(f"diferencia acumulada en debe: {falta_debe}")
for folio, dd, ld, dh, lh in testigos:
    print(f"  testigo {folio!r}: debe {dd} vs {ld} | haber {dh} vs {lh}")

print()
print("--- M3: suma global ---")
dec_d = sum(p.total_debe or 0 for p in diario.polizas)
dec_h = sum(p.total_haber or 0 for p in diario.polizas)
leido_d = sum(m.debe or 0 for m in diario.movimientos)
leido_h = sum(m.haber or 0 for m in diario.movimientos)
print(f"declarado debe {dec_d}  haber {dec_h}")
print(f"leido     debe {leido_d}  haber {leido_h}")
print(f"faltan    debe {dec_d - leido_d}  haber {dec_h - leido_h}")
