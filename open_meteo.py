import logging
import requests
import re
from open_meteo_definitions import *

log = logging.getLogger("OpenMeteo")

geocode_url = "https://geocoding-api.open-meteo.com/v1/search"
reverse_geocode_url = "https://nominatim.openstreetmap.org/reverse"
weather_url = "https://api.open-meteo.com/v1/forecast"
request_timeout = 10

HELP_TEXT = (
    "Weather Bot 🌤\n"
    "A bot that fetches the weather.\n\n"
    "Commands:\n"
    "  wxbot location <place>\n"
    "  wxbot location <zipcode>\n"
    "  wxbot location (uses GPS)\n"
    "  wxbot help"
)

def handle_weather_command(command, packet, interface):
    reply = ""

    if len(command) == 0 or command[0] in ("help", "?"):
        return HELP_TEXT

    if command[0] in ("location", "area"):
        location_str = " ".join(command[1:])

        if location_str:
            # User provided a location string
            coords = geocode(location_str)
            if not coords:
                return f"Sorry, location \"{location_str}\" not found."
            lat, lon, display = coords
        else:
            # No location provided — try sender's GPS
            node_id = packet.get("from")
            pos = get_node_position(interface, node_id)
            if not pos:
                return "No location provided and your node has no GPS position on record."
            lat, lon = pos 
            display = "Using last know location:\n" + reverse_geocode(lat, lon)
            log.info("Using node GPS position: %s", display)

        weather = fetch_weather(lat, lon, display)
        if not weather:
            return f"Sorry, could not fetch weather for {display} right now."
        return weather

    return HELP_TEXT

def get_node_position(interface, node_id: int) -> tuple[float, float] | None:
    # Look up the last known GPS position of a node. Returns (lat, lon) or None.

    nodes = interface.nodes
    if not nodes:
        return None

    # nodes is a dict keyed by hex node ID string e.g. "!a1b2c3d4"
    for node in nodes.values():
        if node.get("num") == node_id:
            pos = node.get("position")
            if pos and "latitude" in pos and "longitude" in pos:
                return (pos["latitude"], pos["longitude"])
    return None

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

def reverse_geocode(lat: float, lon: float) -> str:
    """Convert coordinates to a human-readable location string."""
    try:
        resp = requests.get(
            reverse_geocode_url,
            params={
                "lat": lat,
                "lon": lon,
                "format": "json",
            },
            headers={"User-Agent": "MeshWX/1.0"},  # Nominatim requires a User-Agent
            timeout=request_timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        address = data.get("address", {})
        city    = address.get("city") or address.get("town") or address.get("village") or address.get("county", "")
        state   = address.get("state", "")
        country = address.get("country_code", "").upper()

        display = ", ".join(p for p in [city, state, country] if p)
        log.info("Reverse geocoded (%f, %f) -> %s", lat, lon, display)
        return display or f"{lat:.4f}, {lon:.4f}"  # fallback to coords if nothing found

    except Exception as e:
        log.exception("Reverse geocoding error: %s", e)
        return f"{lat:.4f}, {lon:.4f}"  # fallback to raw coords on error

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
        
