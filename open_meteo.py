import logging
import requests
import re
from state_abbreviations import STATE_ABBREV
from country_abbreviations import COUNTRY_ABBREV
from weather_codes import *

log = logging.getLogger("OpenMeteo")

geocode_url = "https://geocoding-api.open-meteo.com/v1/search"
weather_url = "https://api.open-meteo.com/v1/forecast"
request_timeout = 10


def degrees_to_compass(deg: float) -> str:
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[round(deg / 45) % 8]

def format_precip(weather_code: int, precipitation: float, snowfall: float, precip_probability: int) -> str:
    if weather_code in RAIN_CODES:
        return f"Rain: {precipitation} in"
    elif weather_code in SNOW_CODES:
        return f"Snow: {snowfall} cm ({precipitation} in liquid)"
    elif weather_code in STORM_CODES:
        return f"Storm: {precipitation} in"
    else:
        return f"Rain chance: {precip_probability}%"

def geocode(location: str) -> tuple[float, float, str] | None:
    # Returns a lat, long, and display name if valid location
    #   Returns None if not found

    parts = [p.strip() for p in location.split(",")]
    parts = [STATE_ABBREV.get(p.upper(), p) for p in parts]
    parts = [COUNTRY_ABBREV.get(p.upper(), p) for p in parts]
    parts = [p.lower() for p in parts]

    try:
        response = requests.get(
            geocode_url,
            params={
                "name": parts[0],
                "count": 5,
                "language": "en",
                "format": "json"
            },
            timeout=request_timeout,
        )
        response.raise_for_status()
        data = response.json().get("results")
        if not data:
            log.error("Location not Found.")
            return None

        def score(result: dict) -> int:
            haystack = " ".join([
                result.get("name", ""),
                result.get("admin1", ""),
                result.get("admin2", ""),
                result.get("country", ""),
                result.get("country_code", ""),
            ]).lower()

            haystack_words = set(haystack.split())
            return sum(1 for part in parts if part in haystack_words)

        best = max(data, key=score)

        name = best.get("name", location)
        admin = best.get("admin1", "")
        country = best.get("country_code", "")
        display = ", ".join(p for p in [name, admin, country] if p)

        log.info("Found Location: %s", display)
        log.info("    Lat : %s", best["latitude"])
        log.info("    Long: %s", best["longitude"])

        return (best["latitude"], best["longitude"], display)

    except Exception as e:
        log.exception("Geocoding Error: %s", e)
        return None

def fetch_weather(lat: float, lon: float, display_location: str) -> str | None:
    # Return a Weather String for sending over mesh
    try:
        response = requests.get(
            weather_url,
            params = {
                "latitude": lat,
                "longitude": lon,
                "current": [
                    "temperature_2m",
                    "apparent_temperature",
                    "relative_humidity_2m",
                    "weather_code",
                    "wind_speed_10m",
                    "wind_direction_10m",
                    "precipitation",
                    "precipitation_probability",
                    "snowfall"
                ],
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
                "timezone": "auto",
                "forecast_days": 1,
            },
            timeout=request_timeout,
        )
        response.raise_for_status()
        data = response.json().get("current")
        if not data:
            log.error("Location not Found.")
            return None

        condition = WMO_CODES.get(data["weather_code"], "Unknown")
        emoji = WMO_EMOJI.get(data["weather_code"], "🌡️")
        wind_direction = degrees_to_compass(data["wind_direction_10m"])
        precip_str = format_precip(
            data["weather_code"],
            data["precipitation"],
            data["snowfall"],
            data["precipitation_probability"]
        )

        return_string = (
            f"{display_location}: {condition} {emoji}\n\n"
            f"Temp: {data['temperature_2m']}°F (feels like {data['apparent_temperature']}°F)\n"
            f"Humidity: {data['relative_humidity_2m']}%\n"
            f"Wind: {data['wind_speed_10m']} mph {wind_direction}\n"
            f"{precip_str}"
        )
        log.info("Found Weather for location %s", display_location)
        return return_string

    except Exception as e:
        log.exception("Error fetching weather: %s", e)
        return None

if __name__ == "__main__":
    result = geocode("Hoover, AL, USA")
    fetch_weather(result[0],result[1],result[2])
        