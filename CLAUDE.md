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

Estado: fases 0 a 8e completas. El nucleo cambio en la 8c (exportador
cuadratico y el -o), en la 8d (cuatro correcciones de correctitud) y en la
8e (que las tres salidas digan lo mismo); por lo
demas esta cerrado: 5 parsers, los 5 salen a Excel, los 5 tienen comando de
CLI, y strategy.extraer() enruta sola entre pdf_text, pdf_chars y OCR. El
parser de estado de cuenta cubre 6 formatos de 6 bancos sin ramas por banco.
Cada regla de validacion reporta 'aplicables' (el universo del documento)
ademas de 'evaluados': ningun conteo se imprime sin su denominador, el
signo de una identidad de saldo se deriva de los datos y nunca se cablea,
una comprobacion sobre un dato que el sistema derivo se cuenta aparte de
una sobre dato impreso, y desde la 8d una regla con evaluados == 0 no puede
cuadrar. La capa web (Flask) en src/contapdf/web/ habla con
el nucleo solo por cli.procesar_documento(); tiene cola persistente en
SQLite (web/cola.py), un worker secuencial —un trabajo a la vez, PLAN §6— y
separacion por despacho en la ruta (/t/<despacho>/...). Corre pytest tests/
antes de tocar nada: son 747 tests. Los 124 que abren documentos reales
grandes van marcados `lento` y se corren aparte, ANTES DE ENTREGAR: en la 8e
un test lento fue el UNICO que vio una consecuencia real de un cambio, a los
52 minutos de corrida y con las cinco corridas rapidas en verde. El
procedimiento de instalacion esta en INSTALACION.md.

SERVIDORSIST YA SE MIDIO y esta escrito en PLAN §2. La corrio el
orquestador por Escritorio Remoto; desde tu sesion no hay acceso y no se va
a montar SSH. El fichero es
scripts/mediciones/mediciones-ServidorSist-20260904-1757.txt.
Factor 3.44x sobre los 16 documentos comunes (alli se saltó edocta-hsbc por
falta de Tesseract): auxiliar-gume tarda 10m40s alli contra 3m08s aqui. Por
documento va de 2.29x a 4.03x, pero los cinco que pasan de 15 s caen entre
3.35x y 3.64x. NO cites «3.4-3.7x consistente»: ese rango no lo sostiene
ninguna fila medida. Ni la memoria ni el disco son restriccion (minimo
2 809 MB libres de 8 078 durante la corrida, 328 GB de disco), pero OJO: lo
medido alli es la HOLGURA, no el consumo — el pico del proceso no se pudo
leer en Windows.

OJO: el OCR NUNCA ha funcionado en SERVIDORSIST. La causa se encontro y se
corrigio en la 8d: ocr.py lanzaba Tesseract sin encoding, Windows en español
decodifica con cp1252 y el byte 0x9D de las comillas tipograficas no existe
ahi; el AttributeError: 'NoneType' object has no attribute 'splitlines' que
sale en la traza es el SINTOMA dos capas despues, no la causa, y se
interpreto mal dos veces. PERO el arreglo NO esta verificado en la maquina
objetivo: la suite corre en WSL y ningun test cubre Windows. Lo verifica el
orquestador volviendo a correr el guion alli con Tesseract en el PATH.

OJO: los que producen Excel son 16, no 17. mayor-proactivity sale con
codigo 2 desde la 8e: no es un libro mayor sino un reporte de movimientos
por cuenta, y no imprime meses. La guarda es de DOCUMENTO —si ningun renglon
de mes trae cargos, abonos ni saldo, se rechaza—; en mayor-gume 303 de 588
meses traen importe, asi que hay margen de sobra.

OJO con la magnitud de ese diagnostico, porque la 8d la escribio mal y el
orquestador la copio a tres documentos: los «meses» falsos NO vienen todos
del parentesis. Son 2 de 50 los que traen puntuacion —'(ENERO' y
'(SEPTIEMBRE'—; los otros 48 son nombres de mes limpios dentro de
descripciones. Endurecer _orden_de habria quitado 2 y dejado 48. _es_mes
sigue aceptando un nombre de mes al principio de cualquier renglon de
descripcion: medido y NO arreglado.

OJO: el reloj se reporta SIEMPRE partido, leer+validar por un lado y
exportar por otro. Un total unico escondio nueve fases que el exportador
era cuadratico, y la cifra de 3m57s que se cito en tres documentos
media media operacion. Si mides tiempo, parte el reloj.

OJO con dos cosas abiertas de la 8b (PLAN §2, «Resultados de la fase 8b»):
  - NO hay autenticacion. El aislamiento por despacho es organizativo, no
    una barrera de seguridad. Esta esperando decision del orquestador.
  - En diario-general faltan 659 304.42 en el debe y SOBRAN 106 873.98 en el
    haber: no se pierden renglones, se leen mal los importes (22 movimientos
    traen debe y haber a la vez). La mecanica propuesta NO explica la
    magnitud: quedan 552 430.44 sin aparecer en ningun lado, asi que hay al
    menos dos mecanicas. La 8d desbloqueo la medicion dandole `pagina` a
    `Movimiento`; se cierra en la 8f.

Las tres salidas dicen lo mismo desde la 8e: la hoja Polizas lleva
declarado y leido (8d), las hojas Cuentas de mayor y estado-cuenta tambien
(8e), la hoja Auxiliar declara saldo_origen (8e) y la Discrepancia declara
si compara importes con Decimal | None, asi que ninguna salida lo deduce.
QUEDA UN HUECO: balanza no exporta naturaleza_origen.

OJO con dos cosas de los estados de cuenta, vistas en la demostracion y SIN
MEDIR (fase 8f, mide antes de tocar):
  - la referencia sale pegada al principio de la descripcion
    (`9462491DEPOSITO SPEI:...`) cuando el PDF la imprime en su propia
    columna y MovimientoBancario tiene campo `referencia`.
  - hay espacios dentro de palabras (`C O MISION CUOTA MENSUAL`). Es un
    fenomeno DISTINTO del separador de continuacion y no esta descrito en
    ningun sitio.
  El separador de continuacion (`MEXICOORDENANTE`) SI esta medido y NO es un
  defecto: la geometria no distingue quien parte palabras de quien no (7e),
  asi que es parametro del formato y lo decide el cliente con `confirmar`.
  No lo toques ni propongas heuristicas.

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