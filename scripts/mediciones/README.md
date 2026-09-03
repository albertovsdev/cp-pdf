# Mediciones

Los números de PLAN.md §2 son mediciones, no metas. Estos guiones son los
que las produjeron, para que cualquiera pueda volver a correrlas en vez de
creerse la tabla.

Necesitan los PDFs reales de `fixtures/real/`, que están en `.gitignore`
por llevar datos de clientes. Sin ellos fallan con un `KeyError` del
fixture, no con un número inventado.

```
.venv/bin/python scripts/mediciones/fase8b_m1_subtotales.py
.venv/bin/python scripts/mediciones/fase8b_m2_declarado_vs_leido.py diario-general
.venv/bin/python scripts/mediciones/fase8b_m3_forma_de_la_perdida.py
```

`fase8b_m1_subtotales.py` tarda ~4 min: relee `auxiliar-gume` (886 págs).
