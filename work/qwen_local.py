"""Structured requests to the private YGOKI Ollama instance."""

import json
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MODEL = "qwen3.5:9b-q4_K_M"
HOST = "http://127.0.0.1:11457"


class LocalOnly(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request(endpoint, data=None, timeout=180):
    body = None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = Request(HOST + endpoint, data=body, headers={"Content-Type": "application/json"})
    try:
        with build_opener(ProxyHandler({}), LocalOnly()).open(req, timeout=timeout) as response:
            return json.load(response)
    except (OSError, URLError) as error:
        raise ValueError(f"Lokales Ollama ist nicht erreichbar oder hat geantwortet: {error}") from error


def model_ready():
    tags = request("/api/tags", timeout=4)
    model = next((item for item in tags["models"] if item.get("name", "").lower() == MODEL.lower()), None)
    if model is None:
        raise ValueError(f"Das lokale Modell {MODEL} fehlt. Zuerst Qwen-Lokal.ps1 mit -ModellLaden aufrufen.")
    return {"name": model["name"], "digest": model.get("digest")}


def ask(role, instructions, evidence, schema, seed):
    answer = request("/api/chat", {
        "model": MODEL, "stream": False, "think": False, "format": schema, "keep_alive": "10m",
        "options": {"temperature": 0, "seed": seed, "num_ctx": 8192, "num_predict": 900},
        "messages": [{"role": "system", "content": f"Du bist {role} in YGOKI. {instructions} "
                      "Nutze nur die übergebenen Belege. Schreibe auf Deutsch und knapp."},
                     {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)}],
    })
    try:
        result = json.loads(answer["message"]["content"])
        if not isinstance(result, dict):
            raise ValueError("Antwort ist kein Objekt.")
        return result
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Qwen lieferte keine verwendbare Antwort für die Rolle {role}.") from error


def object_schema(**properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}
