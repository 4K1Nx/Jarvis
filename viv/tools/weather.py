"""Previsão do tempo pela Open-Meteo (gratuita, sem chave), com painel na HUD."""
from datetime import date

import httpx

from viv.bus import BUS
from viv.tools.registry import tool

WMO = {0: "Céu limpo", 1: "Poucas nuvens", 2: "Parcialmente nublado", 3: "Nublado", 45: "Neblina", 48: "Neblina",
       51: "Garoa fraca", 53: "Garoa", 55: "Garoa forte", 56: "Garoa gelada", 57: "Garoa gelada",
       61: "Chuva fraca", 63: "Chuva", 65: "Chuva forte", 66: "Chuva gelada", 67: "Chuva gelada",
       71: "Neve fraca", 73: "Neve", 75: "Neve forte", 77: "Neve", 80: "Pancadas fracas", 81: "Pancadas de chuva",
       82: "Pancadas fortes", 85: "Neve", 86: "Neve", 95: "Trovoadas", 96: "Trovoadas com granizo", 99: "Trovoadas com granizo"}
WEEKDAYS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def fetch(cidade: str, estado: str | None = None) -> tuple[dict, dict]:
    with httpx.Client(timeout=10) as http:
        found = http.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": cidade, "count": 10, "language": "pt"}).json().get("results") or []
        if not found:
            raise LookupError(f"cidade não encontrada: {cidade}")
        place = found[0]
        if estado:
            wanted = estado.casefold()
            place = next((p for p in found if wanted in (p.get("admin1") or "").casefold()
                          or wanted == (p.get("country_code") or "").casefold()), place)
        forecast = http.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto", "forecast_days": 5,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"}).json()
    return place, forecast


def parse_weather(place: dict, forecast: dict) -> dict:
    now, daily = forecast["current"], forecast["daily"]
    days = []
    for i in range(1, len(daily["time"])):
        days.append({"label": WEEKDAYS[date.fromisoformat(daily["time"][i]).weekday()],
                     "max": round(daily["temperature_2m_max"][i]), "min": round(daily["temperature_2m_min"][i]),
                     "rain": round(daily["precipitation_probability_max"][i] or 0),
                     "desc": WMO.get(daily["weather_code"][i], "")})
    return {
        "city": ", ".join(p for p in (place.get("name"), place.get("admin1")) if p),
        "temp": round(now["temperature_2m"]), "feels": round(now["apparent_temperature"]),
        "desc": WMO.get(now["weather_code"], "Tempo instável"),
        "max": round(daily["temperature_2m_max"][0]), "min": round(daily["temperature_2m_min"][0]),
        "rain": round(daily["precipitation_probability_max"][0] or 0),
        "humidity": round(now["relative_humidity_2m"]), "wind": round(now["wind_speed_10m"]), "days": days,
    }


@tool("web_clima", "Previsão do tempo de uma cidade: agora, hoje e próximos dias. Mostra um painel completo na tela. "
      "Use sempre que perguntarem sobre clima, tempo, temperatura ou chuva.",
      {"cidade": {"type": "string"}, "estado": {"type": "string", "description": "estado ou país, se informado", "required": False}},
      card=False)
def clima(cidade, estado=None, ctx=None):
    w = parse_weather(*fetch(cidade, estado))
    BUS.emit("card", f"Clima em {w['city']}", kind="weather", weather=w, ok=True)
    nxt = "; ".join(f"{d['label']}: {d['min']} a {d['max']} graus, {d['desc'].lower()}" for d in w["days"][:2])
    return (f"{w['city']}: agora {w['temp']} graus (sensação {w['feels']}), {w['desc']}. Hoje mínima {w['min']} e máxima "
            f"{w['max']}, {w['rain']}% de chance de chuva, umidade {w['humidity']}%, vento {w['wind']} km/h. {nxt}. "
            "O painel completo está na tela.")
