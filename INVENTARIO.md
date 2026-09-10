# Inventario de cobertura

Qué documentos cubre el sistema hoy, uno por línea. **Es un fichero
generado**: no se edita a mano, se regenera.

    generado : 2026-09-10 15:16
    commit   : 17efa10
    fixtures : 27

```
.venv/bin/python scripts/inventario.py
```

**Caduca en cuanto una fase cambia lo que un documento produce.** Si la
fecha de arriba es vieja, esto no dice lo que el sistema hace hoy: hay
que volver a correr el guion.

`COBERTURA` son los casos **evaluados** de los **aplicables** que el
documento entero contiene, y van siempre las dos cifras: un porcentaje
sin denominador es la misma mentira que un «0 discrepancias».
`REGLAS` es cuadran/fallan/no_verificables. `COD` es el código de salida
del CLI: 0 cuadra, 1 hay discrepancias que revisar, 2 no se pudo
procesar. `EMISOR` sale **del documento**, nunca del nombre del fichero;
va vacío cuando el sistema no lo lee.

---

## Producen Excel (16)

| FIXTURE | TIPO | EMISOR | PAG | EXTRACCION | COBERTURA | REGLAS | PLANTILLA | COD |
|---|---|---|---|---|---|---|---|---|
| auxiliar | auxiliar | — | 398 | pdf_text | 6783 de 6783 | 1/0/2 | pendiente | 0 |
| auxiliar-gume | auxiliar | — | 886 | pdf_text | 48355 de 58518 | 2/1/0 | no | 1 |
| balanza | balanza | — | 9 | pdf_text | 530 de 534 | 4/0/0 | aprendida | 0 |
| balanza-businesspro | balanza | — | 4 | pdf_chars | 273 de 276 | 3/0/1 | aprendida | 0 |
| balanza-gume | balanza | — | 12 | pdf_text | 863 de 863 | 4/0/0 | pendiente | 0 |
| edocta | estado-cuenta | BANCA AFIRME, S. A., INSTITUCIÓN DE B… | 6 | pdf_chars | 48 de 50 | 3/0/1 | pendiente | 0 |
| edocta-abril-santander | estado-cuenta | BANCO SANTANDER MEXICO, S.A., INSTITU… | 13 | pdf_chars | 115 de 115 | 4/0/0 | pendiente | 0 |
| edocta-bajio | estado-cuenta | KARLDOR SA DE CV BANCO DEL BAJIO S.A.… | 11 | pdf_text | 68 de 72 | 3/0/1 | pendiente | 0 |
| edocta-bbva | estado-cuenta | BBVA MEXICO, S.A., INSTITUCION DE BAN… | 11 | pdf_text | 8 de 121 | 3/0/1 | pendiente | 0 |
| edocta-hsbc | estado-cuenta | Emitido por: HSBC México S.A. Institu… | 4 | ocr | 6 de 8 | 3/0/1 | pendiente | 0 |
| edocta-inbursa | estado-cuenta | BANCO INBURSA, S.A. INSTITUCION DE BA… | 8 | pdf_text | 47 de 49 | 3/0/1 | pendiente | 0 |
| edocta-julio-banorte | estado-cuenta | Banco Mercantil del Norte S.A. Instit… | 16 | pdf_text | 285 de 291 | 2/0/2 | pendiente | 0 |
| edocta-santander | estado-cuenta | BANCO SANTANDER (MEXICO) S.A., INSTIT… | 10 | pdf_text | 16 de 25 | 1/1/2 | no | 1 |
| mayor-gume | mayor | — | 17 | pdf_text | 1764 de 1813 | 2/0/1 | aprendida | 0 |
| diario-general | polizas | — | 431 | pdf_chars | 15906 de 15906 | 0/2/2 | no | 1 |
| poliza | polizas | — | 968 | pdf_text | 9595 de 9716 | 3/1/0 | no | 1 |

## No producen Excel (11)

El motivo es el que imprime el sistema. **Es una hipótesis del parser,
no un hallazgo sobre el documento**: dice que no encontró el dato, no
que el documento no lo tenga.

| FIXTURE | TIPO ESPERADO | MOTIVO DEL RECHAZO |
|---|---|---|
| auxiliar-manufacturas | auxiliar | no se pudo leer como auxiliar: ninguno de los 60 mapeos propuestos hace cuadrar el saldo corrido |
| balanza-fd | balanza | no se pudo leer como balanza: el layout no parece una balanza; faltan las columnas: cuenta, nombre, saldo_inicial, saldo_final |
| balanza-manufacturas | balanza | no se pudo leer como balanza: el layout no parece una balanza; faltan las columnas: cuenta, nombre, saldo_inicial, saldo_final |
| balanza-proactivity | balanza | no se pudo leer como balanza: el layout no parece una balanza; faltan las columnas: cuenta, nombre, saldo_inicial, debe, haber, saldo_final |
| edocta-monex | estado-cuenta | el documento no trae tabla de movimientos porque la cuenta no tuvo ninguno: su resumen declara depositos y retiros en cero |
| edocta-multiva | estado-cuenta | el documento no trae tabla de movimientos porque la cuenta no tuvo ninguno: su resumen declara depositos y retiros en cero |
| edocta-scotiabank | estado-cuenta | el documento no trae tabla de movimientos porque la cuenta no tuvo ninguno: su resumen declara depositos y retiros en cero |
| mayor-fd | mayor | no se pudo leer como mayor: no se encontro ninguna cuenta |
| mayor-manufacturas | mayor | no se pudo leer como mayor: no se encontro ninguna cuenta |
| mayor-proactivity | mayor | no se pudo leer como mayor: se detectaron 48 renglones de mes y ninguno trae cargos, abonos ni saldo; el documento no parece un libro mayor |
| polizas-manufacturas | polizas | no se pudo leer como polizas: no se encontro ninguna poliza |
