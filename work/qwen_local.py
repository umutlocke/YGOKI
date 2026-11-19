"""Optional LLM roles for YGOKI: local Ollama (Qwen) or a remote OpenAI-compatible model.

The duel training itself never needs a language model. Only the text roles use it: trainer coach, spectator
reviewers, judge explanations, deck analysis and combo names. By default they use the private local Ollama
instance. To use a remote model instead, create `work/llm.json` (not tracked by git):

    {
      "backend": "openai",
      "base_url": "https://your-provider.example/v1",
      "model": "your-model",
      "api_key_env": "YGOKI_LLM_API_KEY",
      "timeout": 180
    }

The key itself is never stored in the project: set the named environment variable. Environment variables
YGOKI_LLM_BACKEND, YGOKI_LLM_BASE_URL, YGOKI_LLM_HOST, YGOKI_LLM_MODEL and YGOKI_LLM_API_KEY override the file.
Only the text roles leave the computer; the duels always run locally.
"""

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MODEL = "qwen3.5:9b-q4_K_M"
HOST = "http://127.0.0.1:11457"
CONFIG = Path(__file__).resolve().parent / "llm.json"


class LocalOnly(HTTPRedirectHandler):
    """Never follow redirects: a local service must not be reachable through a proxy, and an API key must
    not travel to another host."""

    def redirect_request(self, *args, **kwargs):
        return None


def settings():
    """Backend settings from work/llm.json, overridden by environment variables."""
    data = {}
    try:
        loaded = json.loads(CONFIG.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        data = {}
    base_url = str(os.environ.get("YGOKI_LLM_BASE_URL") or data.get("base_url") or "").strip()
    backend = str(os.environ.get("YGOKI_LLM_BACKEND") or data.get("backend") or
                  ("openai" if base_url else "ollama")).strip().lower()
    if backend not in ("ollama", "openai"):
        raise ValueError(f"Unbekanntes LLM-Backend {backend!r}. Erlaubt sind 'ollama' und 'openai'.")
    key_env = str(data.get("api_key_env", "YGOKI_LLM_API_KEY") or "")
    key = os.environ.get("YGOKI_LLM_API_KEY") or (os.environ.get(key_env, "") if key_env else "")
    return {
        "backend": backend,
        "base_url": base_url.rstrip("/"),
        "host": str(os.environ.get("YGOKI_LLM_HOST") or data.get("host") or HOST).rstrip("/"),
        "model": str(os.environ.get("YGOKI_LLM_MODEL") or data.get("model") or
                     (MODEL if backend == "ollama" else "")).strip(),
        "api_key": key,
        "api_key_env": key_env,
        "timeout": int(data.get("timeout", 180)),
        "send_seed": bool(data.get("send_seed", False)),
    }


def request(endpoint, data=None, timeout=180, cfg=None):
    """POST/GET against the local Ollama instance (kept for the existing self-test)."""
    cfg = cfg or settings()
    body = None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = Request(cfg["host"] + endpoint, data=body, headers={"Content-Type": "application/json"})
    try:
        with build_opener(ProxyHandler({}), LocalOnly()).open(req, timeout=timeout) as response:
            return json.load(response)
    except (OSError, URLError) as error:
        raise ValueError(f"Lokales Ollama ist nicht erreichbar oder hat geantwortet: {error}") from error


def model_ready():
    """Return the configured model or raise a ValueError that says what is missing."""
    cfg = settings()
    if cfg["backend"] == "openai":
        if not cfg["base_url"]:
            raise ValueError("Remote-LLM: In work/llm.json fehlt base_url (oder YGOKI_LLM_BASE_URL).")
        if not cfg["model"]:
            raise ValueError("Remote-LLM: In work/llm.json fehlt model (oder YGOKI_LLM_MODEL).")
        if cfg["api_key_env"] and not cfg["api_key"]:
            raise ValueError(f"Remote-LLM: Kein API-Schlüssel. Umgebungsvariable {cfg['api_key_env']} setzen "
                             "oder in work/llm.json api_key_env leer lassen.")
        return {"name": cfg["model"], "digest": None, "backend": "openai", "remote": True}
    tags = request("/api/tags", timeout=4, cfg=cfg)
    model = next((item for item in tags.get("models", [])
                  if item.get("name", "").lower() == cfg["model"].lower()), None)
    if model is None:
        raise ValueError(f"Das lokale Modell {cfg['model']} fehlt. Zuerst Qwen-Lokal.ps1 mit -ModellLaden aufrufen.")
    return {"name": model["name"], "digest": model.get("digest"), "backend": "ollama", "remote": False}


def status():
    """State for the app: ready, backend, model and a readable German message."""
    cfg = {}
    try:
        cfg = settings()
        model = model_ready()
    except ValueError as error:
        return {"ready": False, "backend": cfg.get("backend"), "model": cfg.get("model"),
                "remote": cfg.get("backend") == "openai", "message": str(error)}
    remote = bool(model.get("remote"))
    return {"ready": True, "backend": model.get("backend"), "model": model["name"], "remote": remote,
            "message": f"KI-Coach bereit: {model['name']} ({'remote' if remote else 'lokal'})"}


def model_name():
    try:
        return settings()["model"] or MODEL
    except ValueError:
        return MODEL


def _object(content):
    """Parse a JSON object; tolerate a surrounding Markdown code block."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = text[7:] if text.lower().startswith("```json") else text[3:]
        text = text.rsplit("```", 1)[0].strip()
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError("Antwort ist kein Objekt.")
    return result


def _remote(cfg, role, instructions, evidence, schema, seed, max_tokens=900):
    url = cfg["base_url"] + "/chat/completions"
    system = (f"Du bist {role} in YGOKI. {instructions} Nutze nur die übergebenen Belege. Schreibe auf Deutsch "
              "und knapp. Antworte ausschließlich mit einem JSON-Objekt ohne Codeblock. Das Objekt muss zu "
              f"diesem JSON-Schema passen: {json.dumps(schema, ensure_ascii=False)}")
    body = {"model": cfg["model"], "stream": False, "temperature": 0, "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)}]}
    if cfg.get("send_seed"):
        body["seed"] = seed
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=headers)
    try:
        with build_opener(ProxyHandler({}), LocalOnly()).open(req, timeout=cfg["timeout"]) as response:
            payload = json.load(response)
    except HTTPError as error:
        detail = ""
        try:
            detail = error.read(300).decode("utf-8", "replace").replace("\n", " ").strip()
        except OSError:
            pass
        raise ValueError(f"Remote-LLM antwortete mit HTTP {error.code}" + (f": {detail}" if detail else "")) from error
    except (OSError, URLError) as error:
        raise ValueError(f"Remote-LLM ist nicht erreichbar: {error}") from error
    try:
        content = payload["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not isinstance(content, str) or not content.strip():
            raise KeyError("content")
        return _object(content)
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ValueError(f"Das Remote-LLM lieferte keine verwendbare Antwort für die Rolle {role}.") from error


def ask(role, instructions, evidence, schema, seed, max_tokens=900):
    cfg = settings()
    if cfg["backend"] == "openai":
        return _remote(cfg, role, instructions, evidence, schema, seed, max_tokens)
    answer = request("/api/chat", {
        "model": cfg["model"], "stream": False, "think": False, "format": schema, "keep_alive": "10m",
        "options": {"temperature": 0, "seed": seed, "num_ctx": 8192, "num_predict": max_tokens},
        "messages": [{"role": "system", "content": f"Du bist {role} in YGOKI. {instructions} "
                      "Nutze nur die übergebenen Belege. Schreibe auf Deutsch und knapp."},
                     {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)}],
    }, timeout=cfg["timeout"], cfg=cfg)
    try:
        return _object(answer["message"]["content"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Der KI-Coach lieferte keine verwendbare Antwort für die Rolle {role}.") from error


def object_schema(**properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}
