#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prueba sin red de la parte municipal: da a objeto_municipal() lo que
JS_MUNICIPAL devolvio de verdad el 26/10/2026 (Spinola Rojo, jornada 2) y
comprueba el formato que leen Wix y el informe de los lunes.

  python test_municipal.py
"""
import importlib.util, os, json
spec = importlib.util.spec_from_file_location(
    "actualizar", os.path.join(os.path.dirname(os.path.abspath(__file__)), "actualizar.py"))
A = importlib.util.module_from_spec(spec); spec.loader.exec_module(A)

CRUDO = {"cod_grupo": "30691", "jornada": 2, "fecha": "24/10/2026", "partidos": [
  ["1", "17/10/2026", "11:00", "CDM Chamartín: PAB FS", "EL DOBLE F.S.", "SPÍNOLA CHAMARTÍN ROJO", 2, 5],
  ["2", "24/10/2026", "12:00", "IDB SANTA HORTENSIA:EXT:FS:1 - CHAMARTIN", "SPÍNOLA CHAMARTÍN ROJO", "Atocha LGNS", 1, 2],
  ["3", "07/11/2026", "12:00", "CDM Chamartín: PAB FS", "JP FC", "SPÍNOLA CHAMARTÍN ROJO", None, None],
  ["2", "24/10/2026", "10:00", "CDM Chamartín: PAB FS", "Chamberí 03", "ALBATROS", 9, 0]],
  "tabla": [[1, "Chamberí 03", 2, 2, 0, 0, 16, 0, 6],
            [4, "SPÍNOLA CHAMARTÍN ROJO", 2, 1, 0, 1, 6, 4, 3],
            [12, "ALBATROS", 2, 0, 0, 2, 0, 19, 0]]}

o = A.objeto_municipal(A.MUNICIPAL[0], CRUDO)
assert [p[0] for p in o["partidos"]] == ["1", "2", "3"], o["partidos"]
assert o["ultimos"][0][-3:] == [2, 5, 0] and o["ultimos"][1][-3:] == [1, 2, 1]
assert o["proximo"][0] == "3" and o["proximo"][6] is None
assert o["total_jugados"] == 2 and o["jornada"] == "2"
assert [f[-1] for f in o["tabla"]] == [0, 1, 0]
# el Blanco no puede colarse como Rojo
try:
    A.objeto_municipal(A.MUNICIPAL[1], CRUDO); raise SystemExit("deberia fallar")
except RuntimeError:
    pass
print(json.dumps(o, ensure_ascii=False)[:400])
print("OK")
