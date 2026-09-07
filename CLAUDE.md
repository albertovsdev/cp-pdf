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
antes de tocar nada: son ~4m26s y 710 tests. Los 111 que abren documentos
reales grandes van marcados `lento` y se corren aparte, antes de entregar
(pytest -m lento, ~33 min). El procedimiento de instalacion esta en
INSTALACION.md.

SERVIDORSIST YA SE MIDIO. La corrio el orquestador por Escritorio Remoto;
desde tu sesion no hay acceso y no se va a montar SSH. El fichero esta en
scripts/mediciones/. Factor consistente de 3.4-3.7x contra la maquina de
desarrollo: auxiliar-gume tarda 10m40s alli contra 3m08s aqui. Ni la memoria
ni el disco son restriccion (minimo 2 809 MB libres de 8 078 durante la
corrida, 328 GB de disco). Falta escribir esos numeros en PLAN §2 y llenar
las columnas vacias de M2, M3 y M4.

OJO: el OCR NUNCA ha funcionado en SERVIDORSIST. edocta-hsbc revienta con
UnicodeDecodeError: 'charmap' codec, porque ocr.py lanza Tesseract sin
encoding='utf-8' y Windows en español decodifica con cp1252. El
AttributeError: 'NoneType' object has no attribute 'splitlines' que sale en
la traza es el SINTOMA dos capas despues, no la causa; se interpreto mal dos
veces. Y la suite corre en WSL, asi que ningun test cubre Windows.

OJO: una regla que no evaluo nada NO PUEDE cuadrar. Hoy mayor-proactivity
reporta saldo_mensual 0 de 48 -> cuadra y acumulados 0 de 96 -> cuadra, con
un encabezado que dice «0 de 145 casos evaluados; 2 cuadran». La fase 7f
prohibio `aplicables is None` con CUADRA pero no `evaluados == 0`, y por ahi
se coló. Es el `0 discrepancias` en su tercera forma.

OJO: el reloj se reporta SIEMPRE partido, leer+validar por un lado y
exportar por otro. Un total unico escondio nueve fases que el exportador
era cuadratico, y la cifra de 3m57s que se cito en tres documentos
media media operacion. Si mides tiempo, parte el reloj.

OJO con dos cosas abiertas de la 8b (PLAN §2, «Resultados de la fase 8b»):
  - NO hay autenticacion. El aislamiento por despacho es organizativo, no
    una barrera de seguridad. Esta esperando decision del orquestador.
  - M3 quedo a medias. En diario-general faltan 659 304.42 en el debe y
    SOBRAN 106 873.98 en el haber: no se pierden renglones, se leen mal los
    importes (22 movimientos traen debe y haber a la vez). La mecanica
    propuesta NO explica la magnitud: quedan 552 430.44 sin aparecer en
    ningun lado, asi que hay al menos dos mecanicas. Cerrarlo exige que
    `Movimiento` guarde la pagina, que hoy no la tiene y FilaAuxiliar si.

OJO: la hoja Polizas del Excel muestra el TOTAL DECLARADO por el documento,
no la suma de los movimientos leidos. En poliza.pdf no hay diferencia; en
diario-general hay 100 polizas donde difieren y aun asi `completa` dice
VERDADERO. El Excel se ve correcto justo cuando un importe se leyo mal.

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