"""
engine.py — Motor de predicción Elo + ataque/defensa + Dixon-Coles.
Es el mismo modelo que ya validamos en la app HTML, portado a Python
para que corra solo en el backend, sin depender de que alguien
tenga la pestaña del navegador abierta.
"""
import math

TEAMS = {
    "ARG": "Argentina", "MEX": "México", "FRA": "Francia", "ESP": "España", "NED": "Países Bajos",
    "BRA": "Brasil", "MAR": "Marruecos", "ENG": "Inglaterra", "COL": "Colombia", "SUI": "Suiza",
    "NOR": "Noruega", "GER": "Alemania", "CIV": "Costa de Marfil", "CRO": "Croacia", "USA": "Estados Unidos",
    "BEL": "Bélgica", "JPN": "Japón", "POR": "Portugal", "EGY": "Egipto", "ECU": "Ecuador",
    "RSA": "Sudáfrica", "CAN": "Canadá", "PAR": "Paraguay", "SWE": "Suecia", "COD": "RD Congo",
    "BIH": "Bosnia y Herzegovina", "AUT": "Austria", "DZA": "Argelia", "AUS": "Australia",
    "CPV": "Cabo Verde", "GHA": "Ghana", "SEN": "Senegal",
}

START_ELO = {
    "FRA": 1916, "ARG": 1907, "ESP": 1880, "ENG": 1840, "BRA": 1805, "MAR": 1789, "NED": 1776, "POR": 1765,
    "MEX": 1754, "BEL": 1735, "COL": 1729, "GER": 1726, "CRO": 1723, "USA": 1677, "SUI": 1676, "JPN": 1674,
    "SEN": 1653, "NOR": 1618, "AUT": 1599, "ECU": 1593, "EGY": 1585, "AUS": 1581, "DZA": 1577, "CAN": 1571,
    "CIV": 1565, "PAR": 1542, "SWE": 1526, "COD": 1495, "BIH": 1520, "RSA": 1450, "GHA": 1420, "CPV": 1380,
}

# W-D-L real de la fase de grupos, usado para calibrar el Elo de arranque.
GROUP_STAGE_POINTS = {
    "ARG": 9, "MEX": 9, "FRA": 9, "ESP": 7, "NED": 7, "BRA": 7, "MAR": 7, "ENG": 7, "COL": 7, "SUI": 7,
    "NOR": 6, "GER": 6, "CIV": 6, "CRO": 6, "USA": 6,
    "BEL": 5, "JPN": 5, "POR": 5, "EGY": 5,
    "ECU": 4, "RSA": 4, "CAN": 4, "PAR": 4, "SWE": 4, "COD": 4, "BIH": 4, "AUT": 4, "DZA": 4, "AUS": 4, "GHA": 4,
    "SEN": 3, "CPV": 3,
}

K = 30
HOME_ADV = 50
RHO = -0.09
ATTACK_DEFENSE_LR = 0.09
HOME_ADV_LOG = math.log(10) * (HOME_ADV / 400)


def gd_multiplier(gd: int) -> float:
    gd = abs(gd)
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11 + gd) / 8


def expected(elo_a: float, elo_b: float) -> float:
    return 1 / (1 + 10 ** (-(elo_a - elo_b) / 400))


def avg_goals_from_history(state: dict) -> float:
    finals = [m for m in state["matches"] if m["status"] in ("final", "live")]
    if not finals:
        return 1.35
    total, count = 0, 0
    for m in finals:
        total += m["hs"] + m["as"]
        count += 2
    return total / count


def expected_goals(state: dict, home: str, away: str):
    base = avg_goals_from_history(state)
    raw_home = state["attack"][home] - state["defense"][away] + HOME_ADV_LOG / 2
    raw_away = state["attack"][away] - state["defense"][home] - HOME_ADV_LOG / 2
    clamp = lambda v: max(-1.4, min(1.4, v))
    return base * math.exp(clamp(raw_home)), base * math.exp(clamp(raw_away))


def poisson_pmf(lam: float, k: int) -> float:
    fact = math.factorial(k)
    return math.exp(-lam) * (lam ** k) / fact


def dc_tau(h, a, lam, mu, rho):
    if h == 0 and a == 0:
        return 1 - lam * mu * rho
    if h == 0 and a == 1:
        return 1 + lam * rho
    if h == 1 and a == 0:
        return 1 + mu * rho
    if h == 1 and a == 1:
        return 1 - rho
    return 1


def score_matrix(exp_home: float, exp_away: float, n: int = 3):
    rows = []
    total = 0.0
    for h in range(7):
        for a in range(7):
            p = poisson_pmf(exp_home, h) * poisson_pmf(exp_away, a) * dc_tau(h, a, exp_home, exp_away, RHO)
            p = max(p, 0)
            rows.append({"h": h, "a": a, "p": p})
            total += p
    for r in rows:
        r["p"] /= total
    rows.sort(key=lambda r: -r["p"])
    outcomes = {"home": 0.0, "draw": 0.0, "away": 0.0, "over25": 0.0, "btts": 0.0}
    for r in rows:
        if r["h"] > r["a"]:
            outcomes["home"] += r["p"]
        elif r["h"] == r["a"]:
            outcomes["draw"] += r["p"]
        else:
            outcomes["away"] += r["p"]
        if r["h"] + r["a"] > 2.5:
            outcomes["over25"] += r["p"]
        if r["h"] > 0 and r["a"] > 0:
            outcomes["btts"] += r["p"]
    return rows[:n], outcomes


def confidence_for(state: dict, home: str, away: str, margin_top: float):
    sample = min(state["games_played"].get(home, 0), state["games_played"].get(away, 0))
    if sample < 2 or margin_top < 0.03:
        return "Baja"
    if sample < 4 or margin_top < 0.06:
        return "Media"
    return "Alta"


def train_on_match(state: dict, m: dict) -> dict:
    ratings = state["ratings"]
    eh, ea = ratings[m["home"]], ratings[m["away"]]
    exp_home = expected(eh + HOME_ADV, ea)
    if m["hs"] > m["as"]:
        actual_home = 1.0
    elif m["hs"] < m["as"]:
        actual_home = 0.0
    else:
        actual_home = 0.5
    mult = gd_multiplier(m["hs"] - m["as"])
    delta = K * mult * (actual_home - exp_home)
    ratings[m["home"]] = eh + delta
    ratings[m["away"]] = ea - delta

    eg_home, eg_away = expected_goals(state, m["home"], m["away"])
    err_h = m["hs"] - eg_home
    err_a = m["as"] - eg_away
    state["attack"][m["home"]] += ATTACK_DEFENSE_LR * err_h
    state["defense"][m["away"]] -= ATTACK_DEFENSE_LR * err_h
    state["attack"][m["away"]] += ATTACK_DEFENSE_LR * err_a
    state["defense"][m["home"]] -= ATTACK_DEFENSE_LR * err_a

    state["games_played"][m["home"]] = state["games_played"].get(m["home"], 0) + 1
    state["games_played"][m["away"]] = state["games_played"].get(m["away"], 0) + 1

    return {
        "match_id": m["id"], "date": m["date"], "home": m["home"], "away": m["away"],
        "hs": m["hs"], "as": m["as"], "delta_home": delta, "delta_away": -delta,
    }


def fresh_state(seed_matches: list) -> dict:
    ratings, attack, defense, games_played = {}, {}, {}, {}
    for t in TEAMS:
        base = START_ELO.get(t, 1500)
        pts = GROUP_STAGE_POINTS.get(t, 4.5)
        group_delta = ((pts / 9) - 0.5) * 140
        elo = base + group_delta
        ratings[t] = elo
        strength = (elo - 1500) / 400
        attack[t] = strength / 2
        defense[t] = strength / 2
        games_played[t] = 0

    state = {
        "ratings": ratings, "attack": attack, "defense": defense,
        "games_played": games_played, "log": [],
        "matches": [dict(m) for m in seed_matches],
    }
    for m in state["matches"]:
        if m["status"] == "final":
            state["log"].append(train_on_match(state, m))
    return state


def build_predictions(state: dict):
    """Genera el paquete de predicciones para todos los partidos no finalizados."""
    out = []
    for m in state["matches"]:
        if m["status"] == "final":
            continue
        eg_home, eg_away = expected_goals(state, m["home"], m["away"])
        top, outcomes = score_matrix(eg_home, eg_away, 3)
        margin = top[0]["p"] - top[1]["p"]
        conf = confidence_for(state, m["home"], m["away"], margin)
        out.append({
            "id": m["id"], "round": m["round"], "date": m["date"], "status": m["status"],
            "home": m["home"], "away": m["away"],
            "home_name": TEAMS.get(m["home"], m["home"]), "away_name": TEAMS.get(m["away"], m["away"]),
            "live_score": {"hs": m.get("hs"), "as": m.get("as")} if m["status"] == "live" else None,
            "top_scorelines": [{"h": r["h"], "a": r["a"], "p": round(r["p"], 4)} for r in top],
            "outcomes": {k: round(v, 4) for k, v in outcomes.items()},
            "expected_goals": {"home": round(eg_home, 2), "away": round(eg_away, 2)},
            "confidence": conf,
        })
    return out
