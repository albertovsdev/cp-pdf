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

MEDICIONES.md e INVENTARIO.md NO se leen al arrancar. MEDICIONES.md se abre
cuando la fase toca algo que ahi se midio, y SIEMPRE antes de citar una cifra
de una fase cerrada: el indice de §2 no lleva numeros a proposito.
INVENTARIO.md dice que cubrimos hoy y lo regenera scripts/inventario.py.

Estado: fases 0 a 8f completas. El nucleo cambio en la 8c (exportador
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
antes de tocar nada: son 762 tests. Los 125 que abren documentos reales
grandes van marcados `lento` y se corren aparte, ANTES DE ENTREGAR: en la 8e
un test lento fue el UNICO que vio una consecuencia real de un cambio, a los
52 minutos de corrida y con las cinco corridas rapidas en verde. El
procedimiento de instalacion esta en INSTALACION.md.

SERVIDORSIST esta medido: la corrida de la 8c en MEDICIONES.md y la del 9 de
septiembre en PLAN §2 (fase 8f). Las corridas las hace el
orquestador por Escritorio Remoto; desde tu sesion no hay acceso y no se va
a montar SSH. Ficheros en scripts/mediciones/; la buena es la del 9 de
septiembre, con los 16 documentos que producen Excel.

OJO CON EL FACTOR: es «unas tres veces», entre 2.7x y 3.0x, y NO ADMITE
DECIMALES. La 8f midio que el denominador —esta maquina de desarrollo— tiene
±28% de ruido: dos corridas consecutivas sin tocar codigo dieron 373.5 s y
415.8 s, y poliza sola se movio un 26%. SERVIDORSIST solo varia 2.4% entre
corridas. Durante cuatro fases se cito 3.4-3.7x, luego 3.44x, luego 3.40x,
afinando decimales de una division cuyo denominador nadie habia repetido. NO
vuelvas a publicar un factor con dos decimales, y si mides tiempo en esta
maquina, REPITE la medicion antes de concluir.

Lo que si es firme son los tiempos ABSOLUTOS de SERVIDORSIST: auxiliar-gume
10m54s, poliza 1m43s, diario-general 3m40s, edocta-hsbc por OCR 48.8s, suma
18m49s. De ahi sale el corte de las 20:49 antes del apagado de las 21:00.
Ni la memoria ni el disco son restriccion (minimo 2 978 MB libres de 8 078,
327 GB de disco), pero lo medido alli es la HOLGURA, no el consumo: el pico
del proceso no se puede leer en Windows.

El OCR YA FUNCIONA en SERVIDORSIST y esta VERIFICADO alli (9 de septiembre,
edocta-hsbc completo por OCR con su xlsx). La causa era de la 8d: ocr.py
lanzaba Tesseract sin encoding, Windows en español decodifica con cp1252 y
el byte 0x9D de las comillas tipograficas no existe ahi; el AttributeError:
'NoneType' object has no attribute 'splitlines' era el SINTOMA dos capas
despues. Aun asi ningun test cubre Windows: la suite corre en WSL.

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

OJO con dos cosas abiertas de la 8b (MEDICIONES.md, «Resultados de la
fase 8b»):
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

OJO: el INVENTARIO vive en INVENTARIO.md, lo genera scripts/inventario.py y
lleva su fecha y su commit para que se vea si caduco. Dice, una linea por
fixture, que cubrimos: 16 producen Excel y 11 no. Leelo antes de proponer
nada sobre cobertura, y REGENERALO si tu fase cambia lo que un documento
produce.

OJO con lo que midio el barrido de la 8f, porque cambia como se leen los
motivos: de 61 reglas, 20 no cuadran, y de sus 11 motivos distintos SEIS
resultaron REFUTADOS al ir al documento. El dato SI estaba y el sistema decia
que no. Inbursa imprime TOTALES en la p5, Bajio imprime SALDO TOTAL en la p9
—y coincide con el saldo_corte que el parser leyo—, Banorte trae los totales
ya desglosados por cuenta. EL MOTIVO QUE IMPRIME UNA REGLA ES UNA HIPOTESIS
DEL PARSER, NO UN HALLAZGO SOBRE EL DOCUMENTO. Antes de escribir «el
documento no trae el dato», ve al documento.

Ademas: el sistema NO lee el emisor de ningun documento contable (7 columnas
del inventario vacias), el banco que si lee viene sucio, y solo 3 de los 16
formatos dejan plantilla aprendida.

Como trabajamos:
  - AL CERRAR UNA FASE, los resultados de la fase ANTERIOR se mueven a
    MEDICIONES.md y en §2 queda su linea de indice, SIN CIFRAS. §2 solo
    conserva la fase en curso. Aplica desde la 8h. Es mecanica y no lleva
    criterio A PROPOSITO: decidir que medicion merece quedarse es justo el
    juicio que queremos evitar, y una regla con juicio se olvida.
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