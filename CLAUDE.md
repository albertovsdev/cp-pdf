Sesion nueva. Contexto del proyecto:

Estas en /mnt/c/proyectos/cp-pdf, un sistema en Python que convierte PDFs
contables a Excel. LEE PLAN.md COMPLETO antes de escribir una sola linea:
es la memoria del proyecto entre sesiones y trae los contratos, las
mediciones y las decisiones de arquitectura. En particular §0
(restricciones), §1 (contratos), §2 (hallazgos medidos y principios) y §4
(tabla de fases).

Estado: fases 0 a 6 completas, 409 tests verdes mas 3 marcados lento
(pytest -m lento). Corre pytest tests/ antes de tocar nada para confirmar
que arrancas en verde.

Como trabajamos:
  - Tests primero, siempre. Muestrame el rojo antes de implementar.
  - Los numeros del PLAN son mediciones, no metas ajustables. Si tu codigo
    da otra cosa, investiga por que; no ajustes el test.
  - Si un fixture no alcanza para decidir algo, PREGUNTA en vez de asumir.
  - Mide antes de disenar. Varias fases cambiaron de rumbo porque una
    medicion refuto una hipotesis mia.
  - No toques scripts/dump_layout.py: es la herramienta de anonimizacion.
  - Los PDFs reales de fixtures/real/ tienen datos sensibles y estan en
    .gitignore. Los fixtures de fixtures/layouts/ son sus versiones
    enmascaradas.