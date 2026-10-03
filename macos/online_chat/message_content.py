"""Versioned message content shared with iOS, carried by the existing API body."""
import json
import math
import re
from urllib.parse import parse_qs, urlparse

PREFIX = "OCM1:"
URL_PATTERN = re.compile(r"(?:https?://|www\.)[^\s<>]+", re.IGNORECASE)


def valid_location(value):
    if not isinstance(value, dict): return None
    try:
        lat, lon = float(value["latitude"]), float(value["longitude"])
        if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
            return {"latitude": lat, "longitude": lon}
    except (KeyError, ValueError, TypeError): pass


def decode(body):
    content = {"text": str(body or "")}
    if content["text"].startswith(PREFIX):
        try:
            value = json.loads(content["text"][len(PREFIX):])
            if isinstance(value, dict) and isinstance(value.get("text"), str):
                content = {"text": value["text"]}
                for key in ("reply", "forward"):
                    quote = value.get(key)
                    if isinstance(quote, dict) and all(isinstance(quote.get(k), str) for k in ("id", "sender", "text")):
                        content[key] = {"id": quote["id"][:64], "sender": quote["sender"][:32], "text": quote["text"][:240]}
                if valid_location(value.get("location")): content["location"] = valid_location(value["location"])
        except (ValueError, TypeError): pass
    # Old location messages remain visible as maps without migrating the database.
    if content["text"].startswith("📍 Местоположение\nhttps://maps.apple.com/"):
        try:
            url = content["text"].split("\n", 1)[1]
            lat, lon = parse_qs(urlparse(url).query)["ll"][0].split(",")
            location = valid_location({"latitude": lat, "longitude": lon})
            if location: content["location"] = location
        except (ValueError, KeyError): pass
    return content


def encode(text="", reply=None, forward=None, location=None):
    if not any((reply, forward, location)): return text
    value = {"text": text}
    if reply: value["reply"] = reply
    if forward: value["forward"] = forward
    if location: value["location"] = location
    return PREFIX + json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def preview(body, attachment=None):
    content = decode(body)
    if content.get("location"): return "📍 Местоположение"
    if attachment: return attachment.get("name", "Вложение")
    return content["text"]


def quote(item, username, peer):
    return {"id": str(item.get("local_id", "")), "sender": username if item.get("outgoing") else peer,
            "text": preview(item.get("text"), item.get("attachment"))[:240]}
