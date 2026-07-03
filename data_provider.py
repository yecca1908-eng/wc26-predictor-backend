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
    fixtures = []
    for item in data.get("response", []):
        home_name = item["teams"]["home"]["name"]
        away_name = item["teams"]["away"]["name"]
        home_code = TEAM_NAME_TO_CODE.get(home_name)
        away_code = TEAM_NAME_TO_CODE.get(away_name)
        if not home_code or not away_code:
            # Equipo sin mapear -- se omite, revisa TEAM_NAME_TO_CODE
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
    return fixtures
