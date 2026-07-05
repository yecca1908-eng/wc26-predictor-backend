"""
data_provider.py — Trae resultados reales del Mundial desde API-Football.

Necesitas una API key gratuita:
1. Entra a https://www.api-football.com/ (o su versión en RapidAPI)
2. Crea una cuenta, plan gratuito (100 requests/día — de sobra para refrescar
   cada pocas horas)
3. Copia tu "API-KEY" y ponla en la variable de entorno API_FOOTBALL_KEY

El plan gratuito SÍ incluye la Copa del Mundo (league id 1 en API-Football).

Si no configuras la key, este módulo no falla — simplemente no trae nada
nuevo y el backend sigue funcionando con los datos con los que arrancó.
"""
import os
import requests

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
WORLD_CUP_LEAGUE_ID = 1
SEASON = int(os.environ.get("WORLD_CUP_SEASON", "2026"))

# API-Football entrega nombres de equipo en inglés. Este mapa los traduce
# a nuestros códigos internos de 3 letras. Si un partido no aparece
# reflejado tras un refresh, lo más probable es que falte un nombre acá
# — revisa el log del servidor, imprime los nombres "sin mapear" y agrégalos.
TEAM_NAME_TO_CODE = {
    "Argentina": "ARG", "Mexico": "MEX", "France": "FRA", "Spain": "ESP",
    "Netherlands": "NED", "Brazil": "BRA", "Morocco": "MAR", "England": "ENG",
    "Colombia": "COL", "Switzerland": "SUI", "Norway": "NOR", "Germany": "GER",
    "Ivory Coast": "CIV", "Côte d'Ivoire": "CIV", "Croatia": "CRO", "USA": "USA",
    "United States": "USA", "Belgium": "BEL", "Japan": "JPN", "Portugal": "POR",
    "Egypt": "EGY", "Ecuador": "ECU", "South Africa": "RSA", "Canada": "CAN",
    "Paraguay": "PAR", "Sweden": "SWE", "DR Congo": "COD", "Congo DR": "COD",
    "Bosnia and Herzegovina": "BIH", "Austria": "AUT", "Algeria": "DZA",
    "Australia": "AUS", "Cape Verde": "CPV", "Cape Verde Islands": "CPV",
    "Ghana": "GHA", "Senegal": "SEN", "Jordan": "JOR",
}

STATUS_MAP = {
    "FT": "final", "AET": "final", "PEN": "final",
    "1H": "live", "2H": "live", "HT": "live", "ET": "live", "P": "live", "LIVE": "live",
    "NS": "scheduled", "TBD": "scheduled",
}


def fetch_fixtures():
    """Devuelve la lista cruda de partidos del Mundial desde API-Football.
    Lanza una excepción si no hay API key o si la petición falla —
    quien llame a esto debe capturarla y seguir con el estado que ya tenía."""
    if not API_KEY:
        raise RuntimeError("Falta API_FOOTBALL_KEY en las variables de entorno")

    resp = requests.get(
        f"{BASE_URL}/fixtures",
        headers={"x-apisports-key": API_KEY},
        params={"league": WORLD_CUP_LEAGUE_ID, "season": SEASON},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()

    # API-Football a veces responde HTTP 200 pero con un error adentro
    # (ej: cuota diaria agotada) -- si no revisamos esto, parece que
    # "no hay partidos nuevos" cuando en realidad la consulta falló.
    errors = data.get("errors")
    if errors:
        raise RuntimeError(f"La API devolvió un error: {errors}")

    raw_response = data.get("response", [])
    fixtures = []
    unmapped = set()
    for item in raw_response:
        home_name = item["teams"]["home"]["name"]
        away_name = item["teams"]["away"]["name"]
        home_code = TEAM_NAME_TO_CODE.get(home_name)
        away_code = TEAM_NAME_TO_CODE.get(away_name)
        if not home_code or not away_code:
            unmapped.add(f"{home_name} vs {away_name}")
            continue
        status_short = item["fixture"]["status"]["short"]
        fixtures.append({
            "api_id": item["fixture"]["id"],
            "home": home_code,
            "away": away_code,
            "status": STATUS_MAP.get(status_short, "scheduled"),
            "hs": item["goals"]["home"],
            "as": item["goals"]["away"],
            "date": item["fixture"]["date"],
            "round_raw": item["league"]["round"],
        })
    LAST_FETCH_DIAGNOSTIC["total_raw"] = len(raw_response)
    LAST_FETCH_DIAGNOSTIC["mapped"] = len(fixtures)
    LAST_FETCH_DIAGNOSTIC["unmapped_examples"] = sorted(unmapped)[:15]
    return fixtures


LAST_FETCH_DIAGNOSTIC = {"total_raw": None, "mapped": None, "unmapped_examples": []}


def fetch_xg(api_id: int):
    """Intenta traer el xG real de un partido ya terminado.
    Devuelve (xg_home, xg_away) o (None, None) si la API no tiene ese dato
    para este partido — pasa seguido en fútbol de selecciones, incluso en
    planes pagos, así que el motor está preparado para seguir sin xG."""
    if not API_KEY:
        return None, None
    try:
        resp = requests.get(
            f"{BASE_URL}/fixtures/statistics",
            headers={"x-apisports-key": API_KEY},
            params={"fixture": api_id},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("response", [])
        if len(data) < 2:
            return None, None
        xg = {}
        for side in data:
            team_id = side["team"]["id"]
            for stat in side.get("statistics", []):
                if stat["type"].strip().lower() in ("expected goals", "xg"):
                    try:
                        xg[team_id] = float(stat["value"])
                    except (TypeError, ValueError):
                        pass
        if len(xg) != 2:
            return None, None
        values = list(xg.values())
        return values[0], values[1]
    except Exception:
        return None, None


def fetch_lineups_confirmed(api_id: int) -> bool:
    """True si ya hay alineaciones confirmadas para este partido (la API
    las publica normalmente ~1 hora antes del pitazo inicial). No ajusta
    ninguna probabilidad por sí sola -- solo informa si ya se puede
    considerar "cerrado" el once titular de cada selección."""
    if not API_KEY:
        return False
    try:
        resp = requests.get(
            f"{BASE_URL}/fixtures/lineups",
            headers={"x-apisports-key": API_KEY},
            params={"fixture": api_id},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("response", [])
        return len(data) >= 2
    except Exception:
        return False

