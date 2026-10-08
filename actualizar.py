#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Actualiza los tres JSON que leen las webs de Wix del CDC Moscardo y del
CD Spinola Chamartin:

  datos.json               calendario y clasificacion del CDC Moscardo (RFFM, grupo 7)
  spinola-resultados.json  los 4 equipos de futbol sala del Spinola (RFFM)
  spinola-baloncesto.json  los equipos de baloncesto del Spinola (FBM)

Uso:
  python actualizar.py                 actualiza los ficheros si hay novedades
  python actualizar.py --dry-run       solo dice que cambiaria, no escribe nada
  python actualizar.py --sin-goleadores  se salta Flashscore (no necesita Playwright)
  python actualizar.py --solo moscardo,futsal,basket   ejecuta solo esas partes
  python actualizar.py --marcar-interrumpido   solo anota en el registro que la
                                               ejecucion anterior se corto a medias

Cada ejecucion deja constancia en el repositorio, haya novedades o no:
  log/ejecuciones.jsonl  una linea JSON por ejecucion, la mas reciente al final
  log/ultima.json        la ultima ejecucion, completa
  ESTADO.md              el mismo resumen en texto legible
Asi se puede saber desde fuera si la tarea programada corrio, sin entrar en
GitHub Actions. En --dry-run no se escribe nada de esto.

Codigo de salida:
  0  todo bien (con o sin cambios)
  1  error general
  2  alguna parte fallo, pero las demas se escribieron

Las tres partes son independientes: si una falla, las otras siguen.
Lo que el script NUNCA toca:
  - los goleadores ya escritos en datos.json (Jesus los revisa a mano)
  - el texto de las notas (solo retira las de jornadas ya jugadas)
  - los datos de un equipo cuya fuente ha fallado (se conservan tal cual)
"""

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from collections import OrderedDict
from datetime import datetime, date

try:
    from zoneinfo import ZoneInfo
    MADRID = ZoneInfo("Europe/Madrid")
except Exception:  # pragma: no cover
    MADRID = None

import requests

RAIZ = os.path.dirname(os.path.abspath(__file__))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

avisos = []
fallos = []


def log(msg):
    print(msg, flush=True)


def aviso(msg):
    avisos.append(msg)
    log("  AVISO: " + msg)


def fallo(msg):
    fallos.append(msg)
    log("  FALLO: " + msg)


# ----------------------------------------------------------------------------
# utilidades
# ----------------------------------------------------------------------------

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def hoy():
    return datetime.now(MADRID).date() if MADRID else date.today()


def fecha_larga(d):
    return "%d de %s de %d" % (d.day, MESES[d.month - 1], d.year)


def leer_json(nombre):
    ruta = os.path.join(RAIZ, nombre)
    if not os.path.exists(ruta):
        return None
    with open(ruta, encoding="utf-8") as f:
        return json.load(f, object_pairs_hook=OrderedDict)


def iguales(a, b, ignorar=()):
    """Compara dos estructuras ignorando las claves de primer nivel indicadas."""
    def limpia(x):
        if isinstance(x, dict):
            return {k: v for k, v in x.items() if k not in ignorar}
        return x
    return json.dumps(limpia(a), sort_keys=True, ensure_ascii=False) == \
           json.dumps(limpia(b), sort_keys=True, ensure_ascii=False)


def escribe(nombre, texto, dry):
    if dry:
        log("  [dry-run] NO se escribe %s (%d bytes)" % (nombre, len(texto)))
        return
    ruta = os.path.join(RAIZ, nombre)
    json.loads(texto)  # valida antes de tocar el disco
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(texto)
    log("  escrito %s (%d bytes)" % (nombre, len(texto)))


# ----------------------------------------------------------------------------
# registro de ejecuciones
# ----------------------------------------------------------------------------

DIR_LOG = os.path.join(RAIZ, "log")
JSONL = os.path.join(DIR_LOG, "ejecuciones.jsonl")
ULTIMA = os.path.join(DIR_LOG, "ultima.json")
ESTADO_MD = os.path.join(RAIZ, "ESTADO.md")

# Dos ejecuciones al dia: 400 lineas son mas de medio ano de historia.
MAX_LINEAS = 400


def url_ejecucion():
    """Enlace a esta ejecucion de GitHub Actions ("" si corre fuera de Actions)."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    run = os.environ.get("GITHUB_RUN_ID")
    if not repo or not run:
        return ""
    servidor = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    return "%s/%s/actions/runs/%s" % (servidor, repo, run)


def _estado(cambios, fallos_, partes):
    if fallos_:
        # Si alguna parte salio bien pese a los fallos, es parcial, no fallo total.
        buenas = [p for p, v in partes.items() if v in ("ok", "sin-cambios")]
        return "parcial" if buenas else "fallo"
    return "ok" if cambios else "sin-cambios"


def entrada(cambios, partes, estado=None):
    """Construye el objeto que se guarda en el registro."""
    ahora = datetime.now(MADRID) if MADRID else datetime.now()
    return OrderedDict([
        ("ts", ahora.strftime("%Y-%m-%dT%H:%M:%S%z") or ahora.isoformat()),
        ("estado", estado or _estado(cambios, fallos, partes)),
        ("cambios", list(cambios)),
        ("partes", OrderedDict(partes)),
        ("avisos", list(avisos)),
        ("fallos", list(fallos)),
        ("url", url_ejecucion()),
        ("run", os.environ.get("GITHUB_RUN_ID", "")),
        # "schedule" = la corrio el cron; "workflow_dispatch" = a mano.
        ("disparo", os.environ.get("GITHUB_EVENT_NAME", "local")),
    ])


def texto_estado(e):
    """ESTADO.md: lo mismo que la entrada, pero para leerlo de un vistazo."""
    lineas = [
        "# Estado de la actualizacion automatica",
        "",
        "Fichero generado por `actualizar.py`. No editar a mano.",
        "",
        "- **Ultima ejecucion:** %s" % e["ts"],
        "- **Estado:** %s" % e["estado"],
        "- **Ficheros con novedades:** %s" % (", ".join(e["cambios"]) or "ninguno"),
        "- **Partes:** %s" % (", ".join("%s (%s)" % (k, v)
                                        for k, v in e["partes"].items()) or "sin datos"),
    ]
    if e["url"]:
        lineas.append("- **Ejecucion en GitHub Actions:** %s" % e["url"])
    for titulo, clave in (("Avisos", "avisos"), ("Fallos", "fallos")):
        if e[clave]:
            lineas += ["", "## %s (%d)" % (titulo, len(e[clave]))]
            lineas += ["- %s" % x for x in e[clave]]
    return "\n".join(lineas) + "\n"


def guarda_registro(e, dry=False):
    """Anade la entrada al JSONL y regenera ultima.json y ESTADO.md.

    Nunca puede tumbar la ejecucion: si falla el registro, se avisa y ya.
    """
    if dry:
        log("  [dry-run] NO se escribe el registro (estado: %s)" % e["estado"])
        return
    try:
        if not os.path.isdir(DIR_LOG):
            os.makedirs(DIR_LOG)

        linea = json.dumps(e, ensure_ascii=False) + "\n"
        with open(JSONL, "a", encoding="utf-8") as f:
            f.write(linea)

        # Recorta el historico para que el fichero no crezca sin fin.
        with open(JSONL, encoding="utf-8") as f:
            lineas = [l for l in f if l.strip()]
        if len(lineas) > MAX_LINEAS:
            with open(JSONL, "w", encoding="utf-8") as f:
                f.writelines(lineas[-MAX_LINEAS:])

        with open(ULTIMA, "w", encoding="utf-8") as f:
            json.dump(e, f, ensure_ascii=False, indent=1)
            f.write("\n")

        with open(ESTADO_MD, "w", encoding="utf-8") as f:
            f.write(texto_estado(e))

        log("  registro guardado (estado: %s)" % e["estado"])
    except Exception as exc:
        log("  no pude guardar el registro: %s" % exc)


def ya_registrada(run):
    """True si esta ejecucion de Actions ya dejo su linea en el registro."""
    if not run or not os.path.exists(JSONL):
        return False
    try:
        with open(JSONL, encoding="utf-8") as f:
            lineas = [l for l in f if l.strip()]
        for l in reversed(lineas[-10:]):
            if json.loads(l).get("run") == run:
                return True
    except Exception:
        pass
    return False


# ----------------------------------------------------------------------------
# RFFM: buildId y peticiones al endpoint _next/data
# ----------------------------------------------------------------------------

class RFFM(object):
    BASE = "https://www.rffm.es"

    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA,
                               "Accept-Language": "es-ES,es;q=0.9"})
        self._build = None

    def build_id(self):
        if self._build:
            return self._build
        r = self.s.get(self.BASE + "/competicion/calendario", timeout=60)
        r.raise_for_status()
        m = re.search(r'"buildId"\s*:\s*"([^"]+)"', r.text)
        if not m:
            raise RuntimeError("no encuentro el buildId en la pagina de la RFFM")
        self._build = m.group(1)
        log("  buildId RFFM: %s" % self._build)
        return self._build

    def data(self, pagina, params, clave, intentos=3):
        """Pide /_next/data/<build>/competicion/<pagina>.json y devuelve
        pageProps[clave]. La RFFM devuelve null de vez en cuando: reintenta."""
        for i in range(1, intentos + 1):
            url = "%s/_next/data/%s/competicion/%s.json" % (
                self.BASE, self.build_id(), pagina)
            try:
                r = self.s.get(url, params=params, timeout=120)
                if r.status_code == 404:
                    # buildId caducado: lo recalcula y reintenta
                    log("    buildId caducado, lo recalculo")
                    self._build = None
                    continue
                r.raise_for_status()
                val = r.json().get("pageProps", {}).get(clave)
                if val:
                    return val
                log("    %s=%s vacio (intento %d/%d), reintento"
                    % (clave, pagina, i, intentos))
            except ValueError:
                log("    la RFFM devolvio algo que no es JSON (intento %d/%d)"
                    % (i, intentos))
            except requests.RequestException as e:
                log("    error de red (intento %d/%d): %s" % (i, intentos, e))
            time.sleep(4 * i)
        raise RuntimeError("la RFFM no devolvio %s para %s" % (clave, params))


# ----------------------------------------------------------------------------
# PARTE A - CDC Moscardo (datos.json)
# ----------------------------------------------------------------------------

MOSCARDO = "85"
COMP_M = {"temporada": "22", "competicion": "26738226",
          "grupo": "26738227", "tipojuego": "1"}

# codigo RFFM -> nombre tal y como lo escribe el fichero
EQUIPOS_M = {
    "85": "CD Colonia Moscardó",
    "171": "AD Cala Pozuelo",
    "293": "CD Las Rozas",
    "2002": "México FC",
    "2172": "CF Fuenlabrada",
    "408": "UD San Sebastián de los Reyes «B»",
    "1592": "AD Unión Adarve",
    "1563": "CF Trival Valderas Alcorcón",
    "1532": "Club Siello Nuevo Boadilla FC",
    "1032104": "Rayo Ciudad Alcobendas CF",
    "1791": "CP Parla Escuela",
    "2127": "CD Móstoles URJC",
    "58": "Rayo Vallecano de Madrid «B»",
    "438": "CD Galapagar",
    "1873": "CF Pozuelo de Alarcón",
    "94": "CD Leganés «B»",
    "117": "Real Aranjuez CF",
    "2363": "AD Torrejón",
}


def iso(fecha_ddmmaaaa):
    """'06-09-2026' -> '2026-09-06'. Devuelve None si no encaja."""
    m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", (fecha_ddmmaaaa or "").strip())
    return "%s-%s-%s" % (m.group(3), m.group(2), m.group(1)) if m else None


def nombre_m(codigo, crudo):
    if codigo in EQUIPOS_M:
        return EQUIPOS_M[codigo]
    aviso("equipo desconocido en el grupo 7: codigo %s (%s). Lo dejo tal cual "
          "y habria que anadirlo a EQUIPOS_M." % (codigo, crudo))
    return crudo


def parte_moscardo(rffm, dry):
    log("PARTE A - CDC Moscardo")
    actual = leer_json("datos.json")
    if actual is None:
        fallo("no existe datos.json; no lo genero desde cero para no perder "
              "las notas ni los goleadores")
        return False

    params = dict(COMP_M, equipo=MOSCARDO)
    cal = rffm.data("calendario", params, "calendar")
    rondas = cal.get("rounds") or []
    if not rondas:
        raise RuntimeError("el calendario del grupo 7 vino sin jornadas")

    # --- partidos del Moscardo + todos los resultados para la clasificacion
    partidos = {}
    tabla = {}
    sin_jugar_ajenos = []

    def fila(cod):
        return tabla.setdefault(cod, dict(pts=0, pj=0, g=0, e=0, p=0, gf=0, gc=0))

    for rnd in rondas:
        j = int(rnd.get("codjornada"))
        for m in (rnd.get("equipos") or []):
            cl, cv = str(m.get("codigo_equipo_local")), str(m.get("codigo_equipo_visitante"))
            gl, gv = str(m.get("goles_casa", "")).strip(), str(m.get("goles_visitante", "")).strip()
            jugado = gl != "" and gv != ""

            if jugado:
                gl, gv = int(gl), int(gv)
                for a, b, f, c in ((cl, cv, gl, gv), (cv, cl, gv, gl)):
                    r = fila(a)
                    r["pj"] += 1; r["gf"] += f; r["gc"] += c
                    if f > c:
                        r["g"] += 1; r["pts"] += 3
                    elif f == c:
                        r["e"] += 1; r["pts"] += 1
                    else:
                        r["p"] += 1
            else:
                fila(cl); fila(cv)
                sin_jugar_ajenos.append((j, cl, cv))

            if MOSCARDO in (cl, cv):
                local = cl == MOSCARDO
                rival_cod = cv if local else cl
                rival_crudo = (m.get("equipo_visitante") if local
                               else m.get("equipo_local")) or ""
                p = OrderedDict()
                p["j"] = j
                p["fecha"] = iso(m.get("fecha")) or ""
                p["local"] = local
                p["rival"] = nombre_m(rival_cod, rival_crudo)
                hora = (m.get("hora") or "").strip()
                if hora:
                    p["hora"] = hora
                if jugado:
                    p["gf"] = gl if local else gv
                    p["gc"] = gv if local else gl
                partidos[j] = p

    if len(partidos) != 34:
        aviso("esperaba 34 partidos del Moscardo y encontre %d" % len(partidos))

    # --- conserva los goleadores ya escritos y los nombres de rival previos
    previos = {p["j"]: p for p in actual.get("partidos", [])}
    for j, p in partidos.items():
        ant = previos.get(j, {})
        if ant.get("goles"):
            p["goles"] = ant["goles"]
        # respeta como estaba escrito el rival (p.ej. la J8 lleva
        # 'Rayo Vallecano «B»' en vez del nombre largo)
        if ant.get("rival") and ant["rival"] != p["rival"]:
            if mismo_equipo(ant["rival"], p["rival"]):
                p["rival"] = ant["rival"]
            else:
                aviso("la jornada %d cambia de rival: '%s' -> '%s'"
                      % (j, ant["rival"], p["rival"]))
        if ant.get("fecha") and ant["fecha"] != p["fecha"]:
            aviso("la jornada %d cambia de fecha: %s -> %s. Revisa si hace "
                  "falta una nota." % (j, ant["fecha"], p["fecha"]))

    lista_partidos = [partidos[j] for j in sorted(partidos)]

    # --- clasificacion ordenada: puntos, diferencia de goles, goles a favor
    clas = []
    for cod, r in tabla.items():
        fila_ = OrderedDict()
        fila_["equipo"] = nombre_m(cod, cod)
        for k in ("pts", "pj", "g", "e", "p", "gf", "gc"):
            fila_[k] = r[k]
        clas.append(fila_)
    clas.sort(key=lambda r: (-r["pts"], -(r["gf"] - r["gc"]), -r["gf"]))

    if len(clas) != 18:
        aviso("la clasificacion tiene %d equipos en vez de 18" % len(clas))

    pjs = set(r["pj"] for r in clas)
    if len(pjs) > 1:
        pendientes = ", ".join(
            "J%d %s-%s" % (j, EQUIPOS_M.get(a, a), EQUIPOS_M.get(b, b))
            for j, a, b in sorted(set(sin_jugar_ajenos))
            if j <= max(r["pj"] for r in clas))
        aviso("no todos los equipos tienen los mismos partidos jugados (%s). "
              "Partidos pendientes: %s" % (sorted(pjs), pendientes or "ninguno"))

    for i in range(len(clas) - 1):
        a, b = clas[i], clas[i + 1]
        if (a["pts"], a["gf"] - a["gc"], a["gf"]) == (b["pts"], b["gf"] - b["gc"], b["gf"]):
            aviso("%s y %s empatan en puntos, diferencia y goles a favor: su "
                  "orden es arbitrario." % (a["equipo"], b["equipo"]))

    # --- goleadores desde Flashscore (opcional)
    if not ARGS.sin_goleadores:
        try:
            anade_goleadores(lista_partidos)
        except Exception as e:
            aviso("no pude sacar los goleadores de Flashscore (%s). Los dejo "
                  "como estaban." % e)

    # --- notas: retira las de jornadas ya jugadas
    jugadas = set(p["j"] for p in lista_partidos if "gf" in p)
    notas = []
    for nota in actual.get("notas", []):
        m = re.match(r"^Jornada\s+(\d+):", (nota[0] if nota else "") or "")
        if m and int(m.group(1)) in jugadas:
            log("  retiro la nota de la jornada %s (ya jugada)" % m.group(1))
            continue
        notas.append(nota)

    ultima = max(jugadas) if jugadas else 0

    nuevo = OrderedDict()
    nuevo["actualizado"] = fecha_larga(hoy())
    nuevo["tras"] = "tras la jornada %d" % ultima if ultima else "antes de empezar"
    nuevo["mi_equipo"] = actual.get("mi_equipo", "CD Colonia Moscardó")
    nuevo["notas"] = notas
    nuevo["partidos"] = lista_partidos
    nuevo["clasificacion"] = clas

    if iguales(actual, nuevo, ignorar=("actualizado",)):
        log("  sin novedades, no toco datos.json")
        return False

    pos = next((i for i, r in enumerate(clas, 1)
                if r["equipo"] == "CD Colonia Moscardó"), None)
    log("  novedades: el Moscardo va %s con %d puntos tras la jornada %d"
        % (pos and "%dº" % pos, clas[pos - 1]["pts"] if pos else 0, ultima))

    escribe("datos.json", formato_moscardo(nuevo), dry)
    return True


def normaliza(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def palabras(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return set(w for w in re.split(r"[^a-z0-9]+", s.lower()) if w)


def mismo_equipo(a, b):
    """Dos formas de escribir el mismo equipo: las palabras de una estan
    contenidas en las de la otra. 'Rayo Vallecano «B»' encaja con
    'Rayo Vallecano de Madrid «B»'; 'AD Torrejon' no encaja con 'CD Las Rozas'."""
    pa, pb = palabras(a), palabras(b)
    return bool(pa) and bool(pb) and (pa <= pb or pb <= pa)


def formato_moscardo(d):
    """Un partido y una fila de clasificacion por linea, como el fichero actual."""
    o = ["{"]
    o.append(' "actualizado": %s,' % json.dumps(d["actualizado"], ensure_ascii=False))
    o.append(' "tras": %s,' % json.dumps(d["tras"], ensure_ascii=False))
    o.append(' "mi_equipo": %s,' % json.dumps(d["mi_equipo"], ensure_ascii=False))
    o.append(' "notas": %s,' % json.dumps(d["notas"], ensure_ascii=False))
    o.append(' "partidos": [')
    o.append(",\n".join("  " + json.dumps(p, ensure_ascii=False)
                        for p in d["partidos"]))
    o.append(' ],')
    o.append(' "clasificacion": [')
    o.append(",\n".join("  " + json.dumps(r, ensure_ascii=False)
                        for r in d["clasificacion"]))
    o.append(' ]')
    o.append("}")
    return "\n".join(o) + "\n"


# ----------------------------------------------------------------------------
# Goleadores del Moscardo: Flashscore + plantilla oficial (Playwright)
# ----------------------------------------------------------------------------

FLASHSCORE = "https://www.flashscore.es/equipo/colonia-moscardo/zXK1rsMs/resultados/"
PLANTILLA = "https://www.cdcmoscardo.es/plantilla"


def apellidos_plantilla():
    """{clave normalizada -> nombre bueno}. De 'Marcos PEÑARANDO' saca
    'Peñarando'; de 'Joaquin PARRILLA(PARRI)' saca 'Parri'."""
    out = {}
    try:
        r = requests.get(PLANTILLA, headers={"User-Agent": UA}, timeout=60)
        r.raise_for_status()
        texto = re.sub(r"<[^>]+>", "\n", r.text)
    except Exception as e:
        aviso("no pude leer la plantilla oficial (%s); usare los nombres de "
              "Flashscore tal cual." % e)
        return out

    for linea in texto.split("\n"):
        linea = " ".join(linea.split())
        if not linea or len(linea) > 60:
            continue
        apodo = re.search(r"\(([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ\s\-]{1,20})\)", linea)
        base = re.sub(r"\([^)]*\)", " ", linea)
        mays = re.findall(r"\b([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ\-]{2,})\b", base)
        elegido = apodo.group(1) if apodo else (" ".join(mays) if mays else None)
        if not elegido:
            continue
        bueno = " ".join(w.capitalize() for w in elegido.split())
        out[normaliza(bueno)] = bueno
        for w in elegido.split():
            out.setdefault(normaliza(w), w.capitalize())
    log("  plantilla oficial: %d nombres" % len(out))
    return out


def bonito(nombre, mapa):
    """Flashscore escribe sin tildes ni enes: busca el nombre bueno."""
    crudo = " ".join((nombre or "").replace(".", " ").split())
    if not crudo:
        return None
    cand = [crudo] + crudo.split()
    for c in sorted(cand, key=len, reverse=True):
        if normaliza(c) in mapa:
            return mapa[normaliza(c)]
    aviso("el goleador '%s' no aparece en la plantilla oficial; uso el nombre "
          "de Flashscore." % crudo)
    return " ".join(w.capitalize() for w in crudo.split())


def anade_goleadores(partidos):
    pendientes = [p for p in partidos if "gf" in p and p.get("gf", 0) > 0
                  and not p.get("goles")]
    if not pendientes:
        log("  goleadores: nada pendiente")
        return

    from playwright.sync_api import sync_playwright

    mapa = apellidos_plantilla()
    log("  goleadores: %d partido(s) pendiente(s)"
        % len(pendientes))

    with sync_playwright() as pw:
        nav = pw.chromium.launch(args=["--no-sandbox"])
        pag = nav.new_page(user_agent=UA, locale="es-ES")
        try:
            pag.goto(FLASHSCORE, timeout=60000)
            pag.wait_for_selector(".event__match", timeout=30000)
            bruto = pag.eval_on_selector_all(
                ".event__match",
                "els => els.map(e => ({id: e.id, txt: e.innerText}))")

            indice = {}
            for it in bruto:
                mid = re.search(r"g_1_(\w+)", it["id"] or "")
                fec = re.search(r"(\d{2})\.(\d{2})\.", it["txt"] or "")
                if mid and fec:
                    indice.setdefault((int(fec.group(1)), int(fec.group(2))),
                                      mid.group(1))

            for p in pendientes:
                try:
                    y, mo, d = (int(x) for x in p["fecha"].split("-"))
                except Exception:
                    continue
                mid = indice.get((d, mo))
                if not mid:
                    aviso("Flashscore no tiene la jornada %d (%s); dejo el "
                          "campo de goleadores fuera." % (p["j"], p["fecha"]))
                    continue
                goles = goles_partido(pag, mid, p["local"], mapa)
                if goles:
                    p["goles"] = goles
                    log("    J%d: %s" % (p["j"], goles))
                else:
                    aviso("no pude leer los goleadores de la jornada %d; dejo "
                          "el campo fuera." % p["j"])
        finally:
            nav.close()


def goles_partido(pag, mid, moscardo_local, mapa):
    url = ("https://www.flashscore.es/partido/%s/#/resumen-del-partido/"
           "resumen-del-partido" % mid)
    pag.goto(url, timeout=60000)
    try:
        pag.wait_for_selector(".smv__participantRow", timeout=20000)
    except Exception:
        return None
    filas = pag.eval_on_selector_all(
        ".smv__participantRow",
        "els => els.map(e => ({cls: e.className, txt: e.innerText}))")

    lado = "home" if moscardo_local else "away"
    orden, minutos = [], {}
    for f in filas:
        if lado not in (f["cls"] or ""):
            continue
        txt = " ".join((f["txt"] or "").split())
        if not re.search(r"\d+\s*-\s*\d+", txt):   # solo las filas de gol
            continue
        minuto = re.search(r"(\d{1,3}(?:\+\d{1,2})?)\s*'", txt)
        if not minuto:
            continue
        crudo = re.sub(r"\d+\s*-\s*\d+", " ", txt)
        crudo = re.sub(r"\d{1,3}(?:\+\d{1,2})?\s*'", " ", crudo)
        crudo = re.sub(r"\((?:[^)]*)\)", " ", crudo)
        nombre = bonito(crudo, mapa)
        if not nombre:
            continue
        if nombre not in minutos:
            orden.append(nombre)
            minutos[nombre] = []
        minutos[nombre].append(minuto.group(1) + "'")

    if not orden:
        return None
    return "; ".join("%s, %s" % (n, ", ".join(minutos[n])) for n in orden)


# ----------------------------------------------------------------------------
# PARTE B - Spinola futbol sala (spinola-resultados.json)
# ----------------------------------------------------------------------------

FUTSAL = [
    dict(slug="fs-tercera-division",
         nombre="Tercera División — Spínola 'A'",
         competicion="26738221", grupo="26771029", codequipo="17148745"),
    dict(slug="fs-primera-autonomica",
         nombre="1ª Autonómica Aficionado — Spínola 'B'",
         competicion="26738243", grupo="26738245", codequipo="17210256"),
    dict(slug="fs-preferente-aficionado",
         nombre="Preferente Aficionado — Spínola 'C'",
         competicion="26738246", grupo="26738248", codequipo="19068165"),
    dict(slug="fs-primera-juvenil",
         nombre="Primera Juvenil",
         competicion="26738228", grupo="28011290", codequipo="17268151"),
]
PREFIJO_ESCUDO = "https://appweb.rffm.es/pnfg/pimg/Clubes/"


def escudo(u):
    return (u or "").replace(PREFIJO_ESCUDO, "").split("?")[0]


def equipo_futsal(rffm, cfg, n=6):
    q = OrderedDict([("temporada", "22"), ("competicion", cfg["competicion"]),
                     ("grupo", cfg["grupo"]), ("tipojuego", "3")])
    st = rffm.data("clasificaciones", q, "standings")
    cal = rffm.data("calendario", dict(q, equipo=cfg["codequipo"]), "calendar")

    tabla = []
    for t in (st.get("clasificacion") or []):
        tabla.append([
            int(t["posicion"]), t["nombre"], escudo(t.get("url_img")),
            int(t["jugados"]), int(t["ganados"]), int(t["empatados"]),
            int(t["perdidos"]), int(t["goles_a_favor"]), int(t["goles_en_contra"]),
            int(t["puntos"]),
            1 if str(t.get("codequipo")) == cfg["codequipo"] else 0,
            "".join(r.get("tipo", "") for r in (t.get("racha_partidos") or [])),
        ])

    ps = []
    for j in (cal.get("rounds") or []):
        for m in (j.get("equipos") or []):
            L = str(m.get("codigo_equipo_local")) == cfg["codequipo"]
            V = str(m.get("codigo_equipo_visitante")) == cfg["codequipo"]
            if not L and not V:
                continue
            gl = str(m.get("goles_casa", "")).strip()
            gv = str(m.get("goles_visitante", "")).strip()
            ps.append([j.get("codjornada"), m.get("fecha"), m.get("hora"),
                       m.get("campo"), m.get("equipo_local"),
                       m.get("equipo_visitante"),
                       escudo(m.get("escudo_equipo_local")),
                       escudo(m.get("escudo_equipo_visitante")),
                       None if gl == "" else int(gl),
                       None if gv == "" else int(gv),
                       1 if L else 0])

    jug = [p for p in ps if p[8] is not None]
    pen = [p for p in ps if p[8] is None]
    return OrderedDict([
        ("slug", cfg["slug"]), ("nombre", cfg["nombre"]),
        ("deporte", "Fútbol sala"), ("comp", st.get("competicion")),
        ("grupo", st.get("grupo")), ("jornada", st.get("jornada")),
        ("fecha", st.get("fecha_jornada")), ("temp", cal.get("temporada")),
        ("fuente", "https://www.rffm.es/competicion/clasificaciones?" +
                   "&".join("%s=%s" % kv for kv in q.items())),
        ("tabla", tabla), ("ultimos", jug[-n:]),
        ("proximo", pen[0] if pen else None), ("total_jugados", len(jug)),
        # calendario completo: lo usa la web HTML (cdspinolachamartin.es); Wix lo ignora
        ("partidos", ps),
    ])


def parte_futsal(rffm, dry):
    log("PARTE B - Spinola futbol sala")
    actual = leer_json("spinola-resultados.json") or OrderedDict(
        [("generado", ""), ("base_escudos", "https://appweb.rffm.es"),
         ("equipos", [])])
    antes = {e["slug"]: e for e in actual.get("equipos", [])}

    equipos = []
    for cfg in FUTSAL:                      # de uno en uno: en paralelo da null
        log("  %s" % cfg["slug"])
        try:
            equipos.append(equipo_futsal(rffm, cfg))
        except Exception as e:
            if cfg["slug"] in antes:
                fallo("%s: %s. Conservo los datos publicados."
                      % (cfg["slug"], e))
                equipos.append(antes[cfg["slug"]])
            else:
                fallo("%s: %s. No hay datos previos que conservar."
                      % (cfg["slug"], e))
        time.sleep(2)

    nuevo = OrderedDict([("generado", hoy().isoformat()),
                         ("base_escudos", "https://appweb.rffm.es"),
                         ("equipos", equipos)])

    if iguales(actual, nuevo, ignorar=("generado",)):
        log("  sin novedades, no toco spinola-resultados.json")
        return False

    for e in equipos:
        pos = next((f[0] for f in e["tabla"] if f[10] == 1), None)
        log("  %s: %s, jornada %s" % (e["slug"], pos and "%sº" % pos,
                                      e.get("jornada")))
    escribe("spinola-resultados.json", formato_lista(nuevo, "equipos",
            ["generado", "base_escudos"]), dry)
    return True


def formato_lista(d, clave, antes):
    o = ["{"]
    for k in antes:
        o.append(' "%s": %s,' % (k, json.dumps(d[k], ensure_ascii=False)))
    o.append(' "%s": [' % clave)
    o.append(",\n".join("  " + json.dumps(e, ensure_ascii=False)
                        for e in d[clave]))
    o.append(' ]')
    o.append("}")
    return "\n".join(o) + "\n"


# ----------------------------------------------------------------------------
# PARTE C - Spinola baloncesto (spinola-baloncesto.json)
# ----------------------------------------------------------------------------

FBM_CLUB = 15985
FBM_SLUG = "colegio-cardenal-spinola-chamartin"
FBM_URL = "https://www.fbm.es/resultados-club-%d/%s" % (FBM_CLUB, FBM_SLUG)
PATRON_SPINOLA = re.compile("SPINOLA", re.I)

# grupo FBM -> (slug, nombre). El orden manda: es el de las pestanas de Wix.
BASKET = OrderedDict([
    ("17607", ("bal-2a-autonomica-masc", "2ª División Autonómica ORO — Masculino")),
    ("17641", ("bal-junior-femenino", "Junior Femenino Preferente")),
    ("17745", ("bal-infantil-masculino", "Infantil Masculino Preferente")),
    ("17804", ("bal-alevin-femenino", "Alevín Femenino 1º año — Liga Marco Aldany")),
    ("17875", ("bal-sub22-femenino", "Sub 22 Femenina — Primera 2ª División")),
])


def txt(el):
    return " ".join(el.get_text(" ", strip=True).split()) if el else ""


def partes(celda):
    """Parte una celda por <br> y limpia cada trozo."""
    import bs4
    trozos, actual = [], []
    for nodo in celda.children:
        if getattr(nodo, "name", None) == "br":
            trozos.append(" ".join("".join(actual).split()))
            actual = []
        else:
            actual.append(nodo.get_text(" ") if isinstance(nodo, bs4.element.Tag)
                          else str(nodo))
    trozos.append(" ".join("".join(actual).split()))
    return trozos


def parte_basket(dry):
    log("PARTE C - Spinola baloncesto")
    from bs4 import BeautifulSoup

    actual = leer_json("spinola-baloncesto.json") or OrderedDict(
        [("generado", ""), ("equipos", [])])
    antes = {e["slug"]: e for e in actual.get("equipos", [])}

    r = requests.get(FBM_URL, headers={"User-Agent": UA}, timeout=90)
    r.raise_for_status()
    doc = BeautifulSoup(r.text, "html.parser")

    grupos = OrderedDict()

    # --- calendarios: una pestana por grupo
    for pest in doc.select('[id^="pestana_calendario_"]'):
        g = pest.get("id").replace("pestana_calendario_", "")
        capa = doc.find(id="capa_calendario_" + g)
        if not capa:
            continue
        ps, jor = [], ""
        for nodo in capa.find_all(["header", "table"]):
            if nodo.name == "header":
                m = re.search(r"Jornada\s*(\d+)", txt(nodo), re.I)
                if m:
                    jor = m.group(1)
                continue
            for fila in nodo.select("tbody tr"):
                c = fila.find_all(["td", "th"])
                if len(c) < 6:
                    continue
                loc, pl, pv, vis = txt(c[0]), txt(c[1]), txt(c[2]), txt(c[3])
                if not PATRON_SPINOLA.search(loc) and not PATRON_SPINOLA.search(vis):
                    continue
                fh = partes(c[4])
                campo = [x for x in partes(c[5]) if x]
                ps.append([jor, fh[0] if fh else "",
                           fh[1] if len(fh) > 1 else "",
                           " — ".join(campo), loc, vis,
                           None if pl == "" else int(pl),
                           None if pv == "" else int(pv),
                           1 if PATRON_SPINOLA.search(loc) else 0])
        jug = [p for p in ps if p[6] is not None]
        pen = [p for p in ps if p[6] is None]
        grupos[g] = dict(competicion=txt(pest), tabla=[], ultimos=jug[-6:],
                         proximo=pen[0] if pen else None, total_jugados=len(jug),
                         jornada=jug[-1][0] if jug else "0",
                         fecha=jug[-1][1] if jug else "", partidos=ps)

    # --- clasificaciones
    rc = doc.find(id="resultadosClasificaciones")
    if rc:
        for capa in rc.select('[id^="capa_"]'):
            m = re.match(r"^capa_(\d+)_(\d+)$", capa.get("id") or "")
            if not m:
                continue
            clas = next((t for t in capa.find_all("table")
                         if t.select_one(".nombre_equipo")), None)
            if not clas:
                continue
            tabla = []
            for fila in clas.select("tbody tr"):
                c = [txt(x) for x in fila.find_all(["td", "th"])]
                if len(c) < 8 or not c[0].isdigit():
                    continue
                tabla.append([int(c[0]), c[1]] +
                             [int(x or 0) for x in c[2:8]] +
                             [1 if PATRON_SPINOLA.search(c[1]) else 0])
            g = m.group(1)
            if g not in grupos:
                pest = doc.find(id="pestana_%s_%s" % (m.group(1), m.group(2)))
                grupos[g] = dict(competicion=txt(pest), tabla=[], ultimos=[],
                                 proximo=None, total_jugados=0, jornada="0",
                                 fecha="")
            grupos[g]["tabla"] = tabla

    if not grupos:
        raise RuntimeError("la ficha de la FBM vino sin ningun grupo")

    # --- monta la lista en el orden conocido, y al final los nuevos
    equipos, vistos = [], set()
    for g, (slug, nombre) in BASKET.items():
        if g in grupos:
            equipos.append(objeto_basket(g, grupos[g], slug, nombre))
            vistos.add(g)
        elif slug in antes:
            aviso("el equipo %s (grupo FBM %s) ya no aparece en la ficha del "
                  "club. Conservo sus datos tal cual." % (slug, g))
            equipos.append(antes[slug])
    for g, datos in grupos.items():
        if g in vistos:
            continue
        slug = "bal-" + (re.sub(r"[^a-z0-9]+", "-",
                                normaliza_texto(datos["competicion"])).strip("-")
                         or g)
        aviso("EQUIPO NUEVO en la FBM: grupo %s, '%s' -> slug '%s'. Hay que "
              "anadirle su pestana en Wix y meterlo en BASKET."
              % (g, datos["competicion"], slug))
        equipos.append(objeto_basket(g, datos, slug, datos["competicion"]))

    nuevo = OrderedDict([("generado", hoy().isoformat()), ("equipos", equipos)])

    if iguales(actual, nuevo, ignorar=("generado",)):
        log("  sin novedades, no toco spinola-baloncesto.json")
        return False

    for e in equipos:
        pos = next((f[0] for f in e["tabla"] if f[8] == 1), None)
        log("  %s: %s, jornada %s" % (e["slug"], pos and "%sº" % pos,
                                      e.get("jornada")))
    escribe("spinola-baloncesto.json",
            formato_lista(nuevo, "equipos", ["generado"]), dry)
    return True


def normaliza_texto(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def objeto_basket(gcod, datos, slug, nombre):
    """'comp' es la primera parte del titulo y 'grupo' el resto, con ' · '."""
    trozos = [t.strip() for t in (datos["competicion"] or "").split(" - ")]
    comp = trozos[0] if trozos else ""
    grupo = " · ".join(trozos[1:])
    return OrderedDict([
        ("slug", slug), ("nombre", nombre), ("deporte", "Baloncesto"),
        ("federacion", "FBM"), ("comp", comp), ("grupo", grupo),
        ("jornada", datos["jornada"]), ("fecha", datos["fecha"]),
        ("temp", "2026-2027"), ("fuente", FBM_URL),
        ("tabla", datos["tabla"]), ("ultimos", datos["ultimos"]),
        ("proximo", datos["proximo"]), ("total_jugados", datos["total_jugados"]),
        # calendario completo: lo usa la web HTML (cdspinolachamartin.es); Wix lo ignora
        ("partidos", datos.get("partidos", [])),
    ])


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main():
    global ARGS
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="dice que cambiaria pero no escribe nada")
    ap.add_argument("--sin-goleadores", action="store_true",
                    help="se salta Flashscore (no necesita Playwright)")
    ap.add_argument("--solo", default="moscardo,futsal,basket",
                    help="partes a ejecutar, separadas por comas")
    ap.add_argument("--marcar-interrumpido", action="store_true",
                    help="no actualiza nada: solo anota que la ejecucion se corto")
    ARGS = ap.parse_args()

    # El workflow lo llama cuando el script anterior murio sin dejar rastro
    # (timeout del job, el runner se quedo sin memoria, cancelacion...).
    if ARGS.marcar_interrumpido:
        if ya_registrada(os.environ.get("GITHUB_RUN_ID", "")):
            log("la ejecucion ya dejo su linea en el registro: no toco nada")
            return 0
        fallo("la ejecucion se corto antes de terminar (mira el registro de Actions)")
        guarda_registro(entrada([], OrderedDict(), estado="interrumpido"))
        return 0

    partes_a_hacer = [p.strip() for p in ARGS.solo.split(",") if p.strip()]

    log("=== %s ===" % datetime.now(MADRID).strftime("%Y-%m-%d %H:%M %Z")
        if MADRID else "=== %s ===" % datetime.now())

    rffm = RFFM()
    cambios = []
    partes = OrderedDict([("moscardo", "omitido"), ("futsal", "omitido"),
                          ("basket", "omitido")])

    def corre(clave, fichero, etiqueta, funcion):
        """Ejecuta una parte y anota como le fue, sin cortar a las demas."""
        if clave not in partes_a_hacer:
            return
        try:
            if funcion():
                cambios.append(fichero)
                partes[clave] = "ok"
            else:
                partes[clave] = "sin-cambios"
        except Exception as e:
            partes[clave] = "fallo"
            fallo("%s: %s" % (etiqueta, e))

    corre("moscardo", "datos.json", "parte A (Moscardo)",
          lambda: parte_moscardo(rffm, ARGS.dry_run))
    corre("futsal", "spinola-resultados.json", "parte B (futbol sala)",
          lambda: parte_futsal(rffm, ARGS.dry_run))
    corre("basket", "spinola-baloncesto.json", "parte C (baloncesto)",
          lambda: parte_basket(ARGS.dry_run))

    log("")
    log("=== resumen ===")
    log("ficheros con novedades: %s" % (", ".join(cambios) or "ninguno"))
    if avisos:
        log("avisos (%d):" % len(avisos))
        for a in avisos:
            log("  - " + a)
    if fallos:
        log("fallos (%d):" % len(fallos))
        for f in fallos:
            log("  - " + f)

    # Deja constancia en el repositorio, haya novedades o no: la ausencia de
    # una linea nueva es lo que permite saber desde fuera que la tarea no corrio.
    e = entrada(cambios, partes)
    guarda_registro(e, ARGS.dry_run)

    # deja el resultado a mano del workflow de GitHub Actions
    resumen = os.environ.get("GITHUB_OUTPUT")
    if resumen:
        with open(resumen, "a", encoding="utf-8") as f:
            f.write("cambios=%s\n" % ",".join(cambios))
            f.write("hay_cambios=%s\n" % ("true" if cambios else "false"))
            f.write("avisos=%d\n" % len(avisos))
            f.write("fallos=%d\n" % len(fallos))
            f.write("estado=%s\n" % e["estado"])

    if fallos:
        return 2 if cambios else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
