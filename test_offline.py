#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prueba sin red: comprueba que la parte del Moscardo reproduce exactamente
el datos.json publicado cuando se le dan los datos de la RFFM.

No sustituye a una ejecucion real (no toca rffm.es ni fbm.es), pero valida
lo que mas puede romperse en silencio: el calculo y el orden de la
clasificacion, el punto de vista de gf/gc, la conservacion de goleadores y
notas, y el formato del fichero.

  python test_offline.py /ruta/al/repo/moscardo-web
"""
import json
import os
import sys
import importlib.util

REPO = sys.argv[1] if len(sys.argv) > 1 else "."

spec = importlib.util.spec_from_file_location(
    "actualizar", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "actualizar.py"))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
A.RAIZ = os.path.abspath(REPO)


class Args:
    dry_run = True
    sin_goleadores = True
    solo = "moscardo"


A.ARGS = Args()

COD = {v: k for k, v in A.EQUIPOS_M.items()}
S = {"CALA": "AD Cala Pozuelo", "ROZAS": "CD Las Rozas", "MEXICO": "México FC",
     "FUENLA": "CF Fuenlabrada",
     "SANSE": "UD San Sebastián de los Reyes «B»", "ADARVE": "AD Unión Adarve",
     "TRIVAL": "CF Trival Valderas Alcorcón",
     "SIELLO": "Club Siello Nuevo Boadilla FC",
     "ALCOBENDAS": "Rayo Ciudad Alcobendas CF", "PARLA": "CP Parla Escuela",
     "MOSTOLES": "CD Móstoles URJC",
     "RAYOB": "Rayo Vallecano de Madrid «B»", "GALAPAGAR": "CD Galapagar",
     "POZUELO": "CF Pozuelo de Alarcón", "LEGANES": "CD Leganés «B»",
     "ARANJUEZ": "Real Aranjuez CF", "TORREJON": "AD Torrejón",
     "MOSCARDO": "CD Colonia Moscardó"}

# los 44 resultados de las jornadas 1 a 5 del grupo 7, tal y como los publica
# la RFFM (verificados contra su calendario el 7-10-2026)
RES = """1|CALA|1|3|ROZAS
1|MEXICO|0|0|FUENLA
1|SANSE|0|2|ADARVE
1|TRIVAL|3|1|SIELLO
1|ALCOBENDAS|5|2|PARLA
1|MOSTOLES|0|0|RAYOB
1|GALAPAGAR|1|1|POZUELO
1|LEGANES|2|0|ARANJUEZ
1|MOSCARDO|1|0|TORREJON
2|POZUELO|1|1|ALCOBENDAS
2|ARANJUEZ|2|5|GALAPAGAR
2|FUENLA|1|3|MOSTOLES
2|TORREJON|1|0|MEXICO
2|SIELLO|0|2|SANSE
2|PARLA|0|0|TRIVAL
2|ADARVE|1|1|MOSCARDO
2|ROZAS|3|2|LEGANES
2|RAYOB|2|3|CALA
3|LEGANES|4|1|RAYOB
3|FUENLA|3|1|TORREJON
3|MEXICO|1|1|ADARVE
3|SANSE|0|3|PARLA
3|TRIVAL|1|1|POZUELO
3|MOSTOLES|1|0|CALA
3|MOSCARDO|5|1|SIELLO
3|ALCOBENDAS|1|1|ARANJUEZ
3|GALAPAGAR|1|1|ROZAS
4|ARANJUEZ|1|2|TRIVAL
4|CALA|1|0|LEGANES
4|RAYOB|1|2|GALAPAGAR
4|TORREJON|0|1|MOSTOLES
4|SIELLO|3|2|MEXICO
4|PARLA|2|2|MOSCARDO
4|ADARVE|2|2|FUENLA
4|POZUELO|3|2|SANSE
4|ROZAS||ALCOBENDAS
5|MEXICO|1|0|PARLA
5|TORREJON|4|0|ADARVE
5|TRIVAL|2|1|ROZAS
5|ALCOBENDAS|4|2|RAYOB
5|MOSTOLES|1|1|LEGANES
5|FUENLA|1|0|SIELLO
5|MOSCARDO|5|1|POZUELO
5|GALAPAGAR|1|3|CALA
5|SANSE|3|5|ARANJUEZ"""


def construye_rounds(publicado):
    """Arma la estructura pageProps.calendar.rounds que devuelve la RFFM."""
    por_jornada = {}
    for linea in RES.strip().split("\n"):
        campos = linea.split("|")
        j, a, ga, gv, b = (campos + [""] * 5)[:5]
        if len(campos) == 4:          # partido sin jugar: 'J|A||B'
            j, a, ga, b = campos
            gv = ""
        por_jornada.setdefault(int(j), []).append(dict(
            codjornada=int(j),
            fecha="", hora="", campo="",
            equipo_local=S[a].upper(), equipo_visitante=S[b].upper(),
            codigo_equipo_local=COD[S[a]], codigo_equipo_visitante=COD[S[b]],
            goles_casa=ga, goles_visitante=gv))

    # los partidos del Moscardo, con su fecha y hora oficiales
    for p in publicado["partidos"]:
        j = p["j"]
        d, mo, y = p["fecha"][8:10], p["fecha"][5:7], p["fecha"][0:4]
        rival_cod = COD[p["rival"]] if p["rival"] in COD else COD[
            "Rayo Vallecano de Madrid «B»"]
        loc = p["local"]
        m = dict(codjornada=j, fecha="%s-%s-%s" % (d, mo, y),
                 hora=p.get("hora", ""), campo="",
                 equipo_local=("MOSCARDO" if loc else "RIVAL"),
                 equipo_visitante=("RIVAL" if loc else "MOSCARDO"),
                 codigo_equipo_local=(COD["CD Colonia Moscardó"] if loc else rival_cod),
                 codigo_equipo_visitante=(rival_cod if loc else COD["CD Colonia Moscardó"]),
                 goles_casa="", goles_visitante="")
        if "gf" in p:
            gl, gv = (p["gf"], p["gc"]) if loc else (p["gc"], p["gf"])
            m["goles_casa"], m["goles_visitante"] = str(gl), str(gv)
        # sustituye el partido del Moscardo que venia de RES, si lo hubiera
        lista = por_jornada.setdefault(j, [])
        for i, otro in enumerate(lista):
            if COD["CD Colonia Moscardó"] in (otro["codigo_equipo_local"],
                                              otro["codigo_equipo_visitante"]):
                lista[i] = m
                break
        else:
            lista.append(m)

    return [dict(codjornada=j, equipos=por_jornada[j])
            for j in sorted(por_jornada)]


def main():
    publicado = A.leer_json("datos.json")
    if publicado is None:
        print("ERROR: no encuentro datos.json en %s" % A.RAIZ)
        return 1
    rounds = construye_rounds(publicado)

    class FakeRFFM(object):
        def data(self, pagina, params, clave, intentos=3):
            assert pagina == "calendario" and clave == "calendar", (pagina, clave)
            return dict(rounds=rounds, temporada="2026-2027")

    generado = {}
    real_escribe = A.escribe
    A.escribe = lambda nombre, texto, dry: generado.__setitem__(nombre, texto)
    try:
        A.parte_moscardo(FakeRFFM(), True)
    finally:
        A.escribe = real_escribe

    errores = []

    if "datos.json" not in generado:
        print("OK  la parte A no detecta novedades con los datos publicados")
        print("    (es lo correcto: significa que reproduce el fichero actual)")
        salida = A.formato_moscardo(publicado)
    else:
        salida = generado["datos.json"]
        print("NOTA la parte A ve novedades; comparo campo a campo")

    obtenido = json.loads(salida)

    # 1. JSON valido y clasificacion identica
    if obtenido["clasificacion"] != publicado["clasificacion"]:
        errores.append("la clasificacion no coincide con la publicada")
        for i, (a, b) in enumerate(zip(obtenido["clasificacion"],
                                       publicado["clasificacion"]), 1):
            if a != b:
                errores.append("  pos %d: %s  vs  %s" % (i, a, b))
    else:
        print("OK  clasificacion: 18 equipos, identica a la publicada")

    # 2. partidos identicos salvo el orden de claves
    if len(obtenido["partidos"]) != 34:
        errores.append("hay %d partidos, esperaba 34" % len(obtenido["partidos"]))
    for a, b in zip(obtenido["partidos"], publicado["partidos"]):
        if a != b:
            errores.append("la jornada %s no coincide:\n    obtenido %s\n    "
                           "publicado %s" % (a.get("j"), a, b))
    if not any("jornada" in e for e in errores):
        print("OK  los 34 partidos coinciden (fechas, horas, gf/gc, goleadores)")

    # 3. goleadores conservados
    con_goles = [p for p in obtenido["partidos"] if p.get("goles")]
    esperados = [p for p in publicado["partidos"] if p.get("goles")]
    if len(con_goles) != len(esperados):
        errores.append("se han perdido goleadores: %d vs %d"
                       % (len(con_goles), len(esperados)))
    else:
        print("OK  goleadores conservados en %d partidos" % len(con_goles))

    # 4. notas conservadas (ninguna jornada con nota esta jugada aun)
    if obtenido["notas"] != publicado["notas"]:
        print("NOTA las notas cambian:")
        print("     antes:   %s" % json.dumps(publicado["notas"], ensure_ascii=False))
        print("     despues: %s" % json.dumps(obtenido["notas"], ensure_ascii=False))
    else:
        print("OK  notas intactas (%d)" % len(obtenido["notas"]))

    # 5. 'tras' coherente
    jugadas = [p["j"] for p in obtenido["partidos"] if "gf" in p]
    if obtenido["tras"] != "tras la jornada %d" % max(jugadas):
        errores.append("'tras' dice '%s' y la ultima jugada es la %d"
                       % (obtenido["tras"], max(jugadas)))
    else:
        print("OK  'tras' = %s" % obtenido["tras"])

    print()
    if errores:
        print("FALLOS (%d):" % len(errores))
        for e in errores:
            print("  " + e)
        return 1
    print("TODO CORRECTO")
    return 0


if __name__ == "__main__":
    sys.exit(main())
