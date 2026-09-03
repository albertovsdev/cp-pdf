Sesion nueva. Contexto del proyecto:

Estas en /mnt/c/proyectos/cp-pdf, un sistema en Python que convierte PDFs
contables a Excel.

Dos documentos, sin solapamiento. LEE LOS DOS antes de escribir una linea:
  - PLAN.md         el PORQUE: contratos, mediciones, principios, fases.
                    En particular §0 (restricciones), §1 (contratos),
                    §2 (hallazgos y principios) y §4 (tabla de fases).
  - ARQUITECTURA.md el QUE: modulos, firmas publicas, flujo, invariantes,
                    puntos de extension, y que es imposible hoy sin
                    cambiar contratos.
Si se contradicen, PLAN.md manda en el porque y ARQUITECTURA.md en el que.

Estado: fases 0 a 7h completas. El nucleo esta cerrado: 5 parsers, los 5
salen a Excel, los 5 tienen comando de CLI, y strategy.extraer() enruta
sola entre pdf_text, pdf_chars y OCR. El parser de estado de cuenta cubre
6 formatos de 6 bancos sin ramas por banco. Cada regla de validacion
reporta 'aplicables' (el universo del documento) ademas de 'evaluados':
ningun conteo se imprime sin su denominador, y el signo de una identidad
de saldo se deriva de los datos, nunca se cablea, y una comprobacion
sobre un dato que el sistema derivo se cuenta aparte de una sobre dato
impreso. 711 tests verdes mas 15 marcados lento (pytest -m lento). Corre pytest tests/ antes de tocar nada.
Siguiente: fase 8 (capa web).

Como trabajamos:
  - Tests primero, siempre. Muestrame el rojo antes de implementar.
  - Los numeros del PLAN son mediciones, no metas ajustables. Si tu codigo
    da otra cosa, investiga por que; no ajustes el test.
  - Si un fixture no alcanza para decidir algo, PREGUNTA en vez de asumir.
  - Mide antes de disenar. Varias fases cambiaron de rumbo porque una
    medicion refuto una hipotesis mia.
  - Cuando la aritmetica no alcanza para decidir, el sistema entrega el
    dato y la pregunta: no_verificable con motivo. Nunca finge saber.
  - Actualiza ARQUITECTURA.md al cerrar cada fase, y la seccion 2 de
    PLAN.md con lo que hayas MEDIDO. Las demas secciones de PLAN.md las
    escribe el orquestador; al cerrar, dile que secciones tocaste.
  - No toques scripts/dump_layout.py: es la herramienta de anonimizacion.
  - Los PDFs reales de fixtures/real/ tienen datos sensibles y estan en
    .gitignore. Los de fixtures/layouts/ son sus versiones enmascaradas.

Reporta SIEMPRE en español. Codigo, nombres de simbolo, rutas y mensajes
de commit en ingles; todo lo demas —reportes, tablas, explicaciones,
preguntas— en español.