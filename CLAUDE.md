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

Estado: fases 0 a 8c completas. El nucleo solo cambio en la 8c para
arreglar el exportador y el -o; por lo demas esta cerrado: 5 parsers, los
5 salen a Excel, los 5 tienen comando de CLI, y strategy.extraer() enruta
sola entre pdf_text, pdf_chars y OCR. El parser
de estado de cuenta cubre 6 formatos de 6 bancos sin ramas por banco. Cada
regla de validacion reporta 'aplicables' (el universo del documento)
ademas de 'evaluados': ningun conteo se imprime sin su denominador, el
signo de una identidad de saldo se deriva de los datos y nunca se cablea, y
una comprobacion sobre un dato que el sistema derivo se cuenta aparte de
una sobre dato impreso. La capa web (Flask) en src/contapdf/web/ habla con
el nucleo solo por cli.procesar_documento(); tiene cola persistente en
SQLite (web/cola.py), un worker secuencial —un trabajo a la vez, PLAN §6— y
separacion por despacho en la ruta (/t/<despacho>/...). Corre pytest tests/
antes de tocar nada: son ~4m20s y 701 tests. Los 111 que abren documentos
reales grandes van marcados `lento` y se corren aparte, antes de entregar
(pytest -m lento, ~33 min). El procedimiento de instalacion esta en
INSTALACION.md.

OJO: la 8c NO llego a medir SERVIDORSIST. No hay acceso desde la sesion --
se entra por Escritorio Remoto, sin SSH -- asi que quedo preparado
scripts/medir_servidorsist.py para que lo corra el orquestador alli. Las
tablas de M2, M3 y M4 en PLAN §2 tienen la columna de esa maquina VACIA.
Todo el dimensionamiento sigue saliendo de la maquina de desarrollo.

OJO: el reloj se reporta SIEMPRE partido, leer+validar por un lado y
exportar por otro. Un total unico escondio nueve fases que el exportador
era cuadratico, y la cifra de 3m57s que se cito en tres documentos
media media operacion. Si mides tiempo, parte el reloj.

OJO con dos cosas abiertas de la 8b (PLAN §2, «Resultados de la fase 8b»):
  - NO hay autenticacion. El aislamiento por despacho es organizativo, no
    una barrera de seguridad. Esta esperando decision del orquestador.
  - M3 quedo a medias. En diario-general faltan 659 304.42 en el debe y
    SOBRAN 106 873.98 en el haber: no se pierden renglones, se leen mal los
    importes (22 movimientos traen debe y haber a la vez). Cerrarlo exige
    que el IR del diario guarde la pagina, que hoy no la tiene: es cambio
    de contrato y esta esperando decision.

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