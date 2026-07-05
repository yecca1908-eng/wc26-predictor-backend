"""
main.py — Backend del predictor del Mundial 2026.

Corre un servidor que:
1. Sirve las predicciones actuales en /api/state
2. Cada 6 horas (configurable) se conecta a la API de datos deportivos,
   trae resultados nuevos, reentrena el modelo con los partidos que ya
   terminaron, y guarda el estado en disco.
3. También puedes forzar una actualización manual con POST /api/refresh

Ejecutar local:
    pip install -r requirements.txt
    export API_FOOTBALL_KEY=tu_key_aqui
    uvicorn main:app --reload

Luego abre http://localhost:8000/api/state en el navegador para ver el JSON,
o apunta el frontend (predictor-mundial-2026.html) a esta URL.
"""
import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler

import engine
import data_provider

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("wc26")

STATE_FILE = Path(os.environ.get("STATE_FILE", "state.json"))
REFRESH_HOURS = float(os.environ.get("REFRESH_HOURS", "6"))

ROUND_RAW_MAP = {
    "round of 32": "r32", "round of 16": "r16",
    "quarter-finals": "qf", "quarterfinals": "qf",
    "semi-finals": "sf", "semifinals": "sf",
    "final": "f", "3rd place final": "third",
}

app = FastAPI(title="WC26 Predictor Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Semilla inicial: lo mismo que ya tenía la app, para que el backend
# arranque funcional incluso antes de tu primer refresh con datos reales. ---
SEED_MATCHES = [
    {"id": "mex-ecu", "round": "r32", "date": "30 jun", "home": "MEX", "away": "ECU", "status": "final", "hs": 2, "as": 0},
    {"id": "rsa-can", "round": "r32", "date": "28 jun", "home": "RSA", "away": "CAN", "status": "final", "hs": 0, "as": 1},
    {"id": "bra-jpn", "round": "r32", "date": "29 jun", "home": "BRA", "away": "JPN", "status": "final", "hs": 2, "as": 1},
    {"id": "ger-par", "round": "r32", "date": "29 jun", "home": "GER", "away": "PAR", "status": "final", "hs": 1, "as": 1},
    {"id": "ned-mar", "round": "r32", "date": "29 jun", "home": "NED", "away": "MAR", "status": "final", "hs": 1, "as": 1},
    {"id": "civ-nor", "round": "r32", "date": "30 jun", "home": "CIV", "away": "NOR", "status": "final", "hs": 1, "as": 2},
    {"id": "fra-swe", "round": "r32", "date": "30 jun", "home": "FRA", "away": "SWE", "status": "final", "hs": 3, "as": 0},
    {"id": "eng-cod", "round": "r32", "date": "1 jul", "home": "ENG", "away": "COD", "status": "final", "hs": 2, "as": 1},
    {"id": "bel-sen", "round": "r32", "date": "1 jul", "home": "BEL", "away": "SEN", "status": "final", "hs": 3, "as": 2},
    {"id": "usa-bih", "round": "r32", "date": "1 jul", "home": "USA", "away": "BIH", "status": "final", "hs": 2, "as": 0},
    {"id": "esp-aut", "round": "r32", "date": "2 jul", "home": "ESP", "away": "AUT", "status": "final", "hs": 3, "as": 0},
    {"id": "por-cro", "round": "r32", "date": "2 jul", "home": "POR", "away": "CRO", "status": "final", "hs": 2, "as": 1},
    {"id": "sui-dza", "round": "r32", "date": "2 jul", "home": "SUI", "away": "DZA", "status": "final", "hs": 2, "as": 0},
    {"id": "aus-egy", "round": "r32", "date": "3 jul", "home": "AUS", "away": "EGY", "status": "live", "hs": 0, "as": 1},
    {"id": "arg-cpv", "round": "r32", "date": "3 jul", "home": "ARG", "away": "CPV", "status": "scheduled"},
    {"id": "col-gha", "round": "r32", "date": "3 jul", "home": "COL", "away": "GHA", "status": "scheduled"},
    {"id": "can-mar", "round": "r16", "date": "4 jul", "home": "CAN", "away": "MAR", "status": "scheduled"},
    {"id": "par-fra", "round": "r16", "date": "4 jul", "home": "PAR", "away": "FRA", "status": "scheduled"},
    {"id": "bra-nor", "round": "r16", "date": "5 jul", "home": "BRA", "away": "NOR", "status": "scheduled"},
    {"id": "mex-eng", "round": "r16", "date": "5 jul", "home": "MEX", "away": "ENG", "status": "scheduled"},
    {"id": "por-esp", "round": "r16", "date": "6 jul", "home": "POR", "away": "ESP", "status": "scheduled"},
    {"id": "usa-bel", "round": "r16", "date": "6 jul", "home": "USA", "away": "BEL", "status": "scheduled"},
]


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    state = engine.fresh_state(SEED_MATCHES)
    save_state(state)
    return state


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


state = load_state()


def merge_and_train(state, fixtures):
    """Actualiza el estado con datos reales: si un partido ya sembrado
    cambió de estado (por ejemplo scheduled -> final), lo reentrenamos.
    Si aparece un cruce nuevo que no teníamos (por ejemplo un cruce de
    octavos que dependía de resultados de hoy), lo agregamos."""
    by_id = {m["id"]: m for m in state["matches"]}
    new_finals = 0
    for fx in fixtures:
        mid = f"{fx['home'].lower()}-{fx['away'].lower()}"
        round_code = ROUND_RAW_MAP.get(fx["round_raw"].strip().lower(), None)

        if mid in by_id:
            m = by_id[mid]
            was_final = m["status"] == "final"
            m["status"] = fx["status"]
            if fx["hs"] is not None:
                m["hs"] = fx["hs"]
            if fx["as"] is not None:
                m["as"] = fx["as"]
            if m["status"] == "final" and not was_final:
                # Recién terminó -- intentamos traer su xG real, una sola vez.
                xg_h, xg_a = data_provider.fetch_xg(fx["api_id"])
                if xg_h is not None:
                    m["xg_home"], m["xg_away"] = xg_h, xg_a
                    m["xg_home_used"] = True
                    log.info("xG real usado en %s: %.2f - %.2f", mid, xg_h, xg_a)
                state["log"].append(engine.train_on_match(state, m))
                state["last_trained"] = m["date"]
                new_finals += 1
            elif m["status"] == "scheduled":
                # Todavía no empieza -- revisamos si ya hay alineaciones
                # confirmadas (informativo, no ajusta números por sí solo).
                m["lineups_confirmed"] = data_provider.fetch_lineups_confirmed(fx["api_id"])
        elif round_code and round_code not in ("group",):
            # Cruce nuevo que no teníamos sembrado (ej: llave que se acaba
            # de definir). Solo lo agregamos si ambos códigos de equipo
            # son selecciones que ya conocemos.
            if fx["home"] in engine.TEAMS and fx["away"] in engine.TEAMS:
                new_m = {
                    "id": mid, "round": round_code, "date": fx["date"][:10],
                    "home": fx["home"], "away": fx["away"], "status": fx["status"],
                    "hs": fx["hs"] or 0, "as": fx["as"] or 0,
                }
                state["matches"].append(new_m)
                by_id[mid] = new_m
                if new_m["status"] == "final":
                    xg_h, xg_a = data_provider.fetch_xg(fx["api_id"])
                    if xg_h is not None:
                        new_m["xg_home"], new_m["xg_away"] = xg_h, xg_a
                        new_m["xg_home_used"] = True
                    state["log"].append(engine.train_on_match(state, new_m))
                    new_finals += 1
    return new_finals


def refresh():
    global state
    try:
        fixtures = data_provider.fetch_fixtures()
    except Exception as e:
        log.warning("No se pudo refrescar datos reales: %s", e)
        return {"ok": False, "reason": str(e)}
    new_finals = merge_and_train(state, fixtures)
    save_state(state)
    log.info("Refresh OK — %s partidos nuevos entrenados", new_finals)
    return {
        "ok": True,
        "new_finals": new_finals,
        "diagnostic": data_provider.LAST_FETCH_DIAGNOSTIC,
    }


scheduler = BackgroundScheduler()
scheduler.add_job(refresh, "interval", hours=REFRESH_HOURS, id="refresh_job")
scheduler.start()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/state")
def get_state():
    ranked = sorted(state["ratings"].items(), key=lambda x: -x[1])
    ranking = [{"code": t, "name": engine.TEAMS.get(t, t), "elo": round(e, 1)} for t, e in ranked]
    predictions = engine.build_predictions(state)
    return {
        "ranking": ranking,
        "predictions": predictions,
        "log": state["log"][-30:],
        "matches_trained": len(state["log"]),
        "last_trained": state.get("last_trained", "—"),
    }


@app.post("/api/refresh")
def manual_refresh():
    return refresh()


@app.get("/api/refresh")
def manual_refresh_get():
    """Igual que el POST de arriba, pero se puede visitar directo desde el
    navegador (sin curl/Postman) para forzar una actualización a mano."""
    return refresh()


@app.post("/api/reset")
def reset():
    global state
    state = engine.fresh_state(SEED_MATCHES)
    save_state(state)
    return {"ok": True}

