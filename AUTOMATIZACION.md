# Actualización automática de los resultados

Este repositorio se actualiza solo. Un workflow de GitHub Actions ejecuta
`actualizar.py` dos veces al día, y si hay novedades hace commit de los JSON
que leen las webs de Wix. GitHub Pages los sirve y las webs se refrescan solas.

No hay que subir nada a mano.

## Cómo instalarlo

Copia estos dos ficheros a la raíz del repositorio `moscardo-web`,
respetando las carpetas:

```
actualizar.py
.github/workflows/actualizar.yml
test_offline.py          (opcional, solo para probar)
AUTOMATIZACION.md        (esto)
```

Luego, en GitHub, entra en **Settings → Actions → General**, baja a
*Workflow permissions* y marca **Read and write permissions**. Sin eso el
workflow no puede hacer commit.

Eso es todo. No hay que crear ningún token ni secreto: Actions usa el suyo.

## La primera ejecución

Hazla a mano y en seco, para verla sin que toque nada:

**Actions → Actualizar resultados → Run workflow**, marca
*Solo decir que cambiaría* y lánzalo.

Mira el registro. Si dice `sin novedades` en las tres partes, o lista
cambios que tengan sentido, vuelve a lanzarlo sin marcar la casilla y ya
queda funcionando por su cuenta.

Si algo falla, el registro completo queda guardado 30 días como artefacto
`registro` en la propia ejecución.

## Qué hace y qué no toca

| Parte | Fichero | Fuente |
|---|---|---|
| A | `datos.json` | RFFM (grupo 7 de Tercera Federación) + Flashscore para los goleadores |
| B | `spinola-resultados.json` | RFFM (los 4 equipos de fútbol sala) |
| C | `spinola-baloncesto.json` | FBM (ficha del club) |
| D | `moscardo-cantera.json` | RFFM (fichas de equipo, clasificación y calendario de los 25 equipos de cantera y filiales del Moscardó) |

`moscardo-cantera.json` **solo lo lee la web HTML del Moscardó** (`CDC Moscardo/assets/js/equipo.js`
en menta-webs): una página por equipo con cuerpo técnico, jugadores, resultados,
clasificación y próximo partido. Wix no lo usa y no hay que tocar nada en Wix.
En cada ejecución la parte D también revisa las fichas de los dos clubes en la RFFM
(1008 masculino y 15336175 femenino) y avisa si aparece un equipo nuevo o desaparece uno.

Los equipos del Spínola llevan además el campo `partidos` con el calendario
completo. Wix no lo usa; lo lee la web HTML del club (cdspinolachamartin.es,
`js/resultados.js` en el repositorio menta-webs) para pintar calendario,
clasificación y el selector de partidos de la portada.

Los equipos de fútbol sala llevan también `goleadores` (goles del Spínola y del
rival en cada jornada, sacados del acta de la RFFM: `/acta-partido/<codacta>`) y
`goleadores_temporada` (tabla de goleadores del Spínola). Las actas cerradas ya
leídas no se vuelven a pedir.

Las partes son independientes: **si una falla, las otras se publican
igual**. Un equipo cuya fuente falle conserva sus datos anteriores, así que
la web nunca se queda en blanco.

Lo que el script **nunca** pisa:

- **Los goleadores que ya estén escritos** en `datos.json`. Solo rellena los
  partidos que no tengan el campo `goles`. Las correcciones tuyas (como
  Hakim en el 86' de la J1) se quedan.
- **El texto de las notas.** Lo único que hace es retirar automáticamente
  las notas de jornadas ya jugadas (`"Jornada 6:"` desaparece cuando se
  juega la 6). Las notas nuevas las escribes tú: si cambia la fecha de un
  partido del Moscardó, el script lo avisa en el registro con un
  `AVISO: la jornada N cambia de fecha` para que decidas si merece nota.
- **Cualquier otro fichero del repositorio.** El commit solo incluye esos
  tres JSON, y antes de publicar valida que son JSON correcto.

## Avisos que conviene leer

El script escribe `AVISO:` en el registro cuando pasa algo que necesita una
decisión humana:

- **Equipo nuevo en la FBM.** Si el club inscribe un equipo de baloncesto
  más, lo incluye con un slug automático y lo avisa, para que le añadas su
  pestaña en Wix y lo metas en el diccionario `BASKET` con su slug y nombre
  definitivos.
- **Equipo que desaparece.** Conserva sus datos y lo avisa.
- **Partidos aplazados.** Si no todos los equipos del grupo 7 llevan los
  mismos partidos jugados, dice cuáles faltan.
- **Empate total en la clasificación.** Si dos equipos empatan en puntos,
  diferencia de goles y goles a favor, avisa de que su orden es arbitrario.
- **Goleador desconocido.** Si alguien no aparece en la plantilla oficial,
  usa el nombre de Flashscore (sin tildes) y lo avisa para que lo corrijas.

## Mantenimiento: los códigos de competición

Los códigos de la RFFM cambian cada temporada. Están todos juntos al
principio de las secciones de `actualizar.py`:

- `COMP_M` y `EQUIPOS_M` — competición, grupo y los 18 equipos del Moscardó.
- `FUTSAL` — los 4 equipos de fútbol sala, con su competición, grupo y código.
- `BASKET` — los grupos de la FBM y sus slugs de Wix.
- `CANTERA` — los equipos de cantera del Moscardó: código de equipo, competición,
  grupo y tipo de juego (1 fútbol 11, 2 fútbol 7). El `slug` es el nombre de su
  página en la web HTML (`equipo-<slug>.html`).

Para la temporada que viene habrá que actualizar `temporada` (hoy `22`) y
volver a buscar los códigos con
`https://www.rffm.es/api/competitions?temporada=XX&tipojuego=1` y
`https://www.rffm.es/api/groups?competicion=<código>`.

El `buildId` de la RFFM no hay que tocarlo: el script lo lee de la página
cada vez, y si caduca a mitad de ejecución lo vuelve a pedir.

## Probar sin red

`test_offline.py` comprueba, sin tocar internet, que la parte del Moscardó
reproduce exactamente el `datos.json` publicado: el cálculo y el orden de la
clasificación, el punto de vista de `gf`/`gc`, la conservación de goleadores
y notas, y el formato del fichero.

```
python test_offline.py .
```

Debe terminar en `TODO CORRECTO`. Es útil después de tocar el script.

## Uso desde la línea de órdenes

```
python actualizar.py                      actualiza si hay novedades
python actualizar.py --dry-run            dice qué cambiaría, no escribe
python actualizar.py --sin-goleadores     se salta Flashscore (no necesita Playwright)
python actualizar.py --solo basket        solo una parte (moscardo, futsal, basket)
```

Dependencias: `pip install requests beautifulsoup4 playwright` y, para los
goleadores, `python -m playwright install chromium`.

Códigos de salida: `0` todo bien, `1` error, `2` alguna parte falló pero las
demás se escribieron.
