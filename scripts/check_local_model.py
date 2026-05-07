from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "sources.json"


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    settings = config.get("settings", {}).get("local_models", {})
    base_url = str(settings.get("base_url", "http://localhost:11434")).rstrip("/")
    summary_model = str(settings.get("summary_model", "llama3.1:8b"))
    translation_model = str(settings.get("translation_model", "qwen2.5:3b"))
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Ollama no responde en {base_url}: {exc}")
        print("Arranca Ollama y ejecuta: ollama pull " + summary_model)
        return 1

    names = {entry.get("name") for entry in data.get("models", [])}
    missing = [model for model in (summary_model, translation_model) if model not in names]
    if missing:
        print(f"Ollama responde, pero faltan modelos: {', '.join(missing)}.")
        for model in missing:
            print("Descargalo con: ollama pull " + model)
        return 1

    print(f"Modelos locales listos: resumen={summary_model}, traduccion={translation_model} en {base_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
