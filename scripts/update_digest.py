from __future__ import annotations

import email.utils
import hashlib
import html
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "sources.json"
DATA_DIR = ROOT / "data"
PUBLIC_DATA_PATH = DATA_DIR / "digest.js"
JSON_DATA_PATH = DATA_DIR / "digest.json"
PUBLIC_SITE_DATA_PATH = ROOT / "public" / "digest.js"
TRANSLATION_CACHE_PATH = DATA_DIR / "translation_cache.json"

USER_AGENT = "AgenteWebNoticias/1.0 (+local morning digest)"


@dataclass
class Item:
    topic: str
    title: str
    url: str
    source: str
    source_type: str
    published: str | None = None
    summary: str = ""
    score: float = 0.0
    raw_score: float = 0.0
    comments_url: str | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", " ", value))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def strip_markdown_links(value: str) -> str:
    value = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", value)
    value = re.sub(r"https?://\S+", "", value)
    value = value.replace("----START HUMAN TEXT----", " ")
    return re.sub(r"\s+", " ", value).strip()


def truncate_text(value: str, max_length: int) -> str:
    compact = clean_text(strip_markdown_links(value))
    if len(compact) <= max_length:
        return compact
    trimmed = compact[: max_length - 1].rsplit(" ", 1)[0].strip()
    return (trimmed or compact[: max_length - 1]).rstrip(" ,;:.-") + "…"


def fetch_url(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def post_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_rss_date(entry: ET.Element) -> str | None:
    for tag in ("pubDate", "published", "updated"):
        found = entry.find(tag)
        if found is not None and found.text:
            return found.text
    for child in entry:
        if child.tag.endswith("}published") or child.tag.endswith("}updated"):
            return child.text
    return None


def child_text(entry: ET.Element, names: tuple[str, ...]) -> str:
    for name in names:
        found = entry.find(name)
        if found is not None and found.text:
            return found.text
    for child in entry:
        local = child.tag.split("}", 1)[-1]
        if local in names and child.text:
            return child.text
    return ""


def fetch_rss(topic_id: str, source: dict[str, Any], timeout: int) -> list[Item]:
    payload = fetch_url(source["url"], timeout)
    root = ET.fromstring(payload)
    entries = root.findall(".//item")
    if not entries:
        entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    items: list[Item] = []
    for entry in entries[:40]:
        title = clean_text(child_text(entry, ("title",)))
        link = clean_text(child_text(entry, ("link",)))
        if not link:
            for child in entry:
                if child.tag.endswith("}link") and child.attrib.get("href"):
                    link = child.attrib["href"]
                    break
        summary = clean_text(child_text(entry, ("description", "summary", "content")))
        published = parse_rss_date(entry)
        if title and link:
            items.append(
                Item(
                    topic=topic_id,
                    title=title,
                    url=link,
                    source=source["name"],
                    source_type="rss",
                    published=published,
                    summary=summary,
                    raw_score=1.0,
                    score=float(source.get("weight", 0.7)),
                )
            )
    return items


def fetch_reddit(topic_id: str, source: dict[str, Any], timeout: int) -> list[Item]:
    subreddit = source["subreddit"]
    url = f"https://www.reddit.com/r/{urllib.parse.quote(subreddit)}/top.json?t=day&limit=25"
    data = json.loads(fetch_url(url, timeout).decode("utf-8"))
    items: list[Item] = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        title = clean_text(post.get("title"))
        permalink = post.get("permalink")
        if not title or not permalink:
            continue
        score = float(post.get("score") or 0)
        comments = int(post.get("num_comments") or 0)
        created = datetime.fromtimestamp(float(post.get("created_utc") or time.time()), timezone.utc)
        discussion_url = "https://www.reddit.com" + permalink
        items.append(
            Item(
                topic=topic_id,
                title=title,
                url=post.get("url_overridden_by_dest") or discussion_url,
                source=source["name"],
                source_type="forum",
                published=created.isoformat(),
                summary=truncate_text(post.get("selftext", ""), 320),
                raw_score=score + comments * 1.5,
                score=float(source.get("weight", 0.7)) * (1 + math.log10(max(score + comments, 1))),
                comments_url=discussion_url,
            )
        )
    return items


def fetch_hn(topic_id: str, source: dict[str, Any], timeout: int) -> list[Item]:
    query = urllib.parse.quote(source["query"])
    url = f"https://hn.algolia.com/api/v1/search_by_date?query={query}&tags=story&hitsPerPage=25"
    data = json.loads(fetch_url(url, timeout).decode("utf-8"))
    items: list[Item] = []
    for hit in data.get("hits", []):
        title = clean_text(hit.get("title") or hit.get("story_title"))
        story_url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        points = float(hit.get("points") or 0)
        comments = int(hit.get("num_comments") or 0)
        items.append(
            Item(
                topic=topic_id,
                title=title,
                url=story_url,
                source=source["name"],
                source_type="forum",
                published=hit.get("created_at"),
                summary="Conversacion destacada en Hacker News.",
                raw_score=points + comments * 2,
                score=float(source.get("weight", 0.7)) * (1 + math.log10(max(points + comments, 1))),
                comments_url=f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
            )
        )
    return [item for item in items if item.title and item.url]


def fetch_arxiv(topic_id: str, source: dict[str, Any], timeout: int) -> list[Item]:
    query = urllib.parse.quote(source["query"])
    url = f"https://export.arxiv.org/api/query?search_query={query}&sortBy=submittedDate&sortOrder=descending&max_results=20"
    payload = fetch_url(url, timeout)
    root = ET.fromstring(payload)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items: list[Item] = []
    for entry in root.findall("atom:entry", ns):
        title = clean_text(child_text(entry, ("title",)))
        summary = clean_text(child_text(entry, ("summary",)))
        link = ""
        for child in entry:
            if child.tag.endswith("}link") and child.attrib.get("href") and child.attrib.get("rel") == "alternate":
                link = child.attrib["href"]
                break
        published = child_text(entry, ("published", "updated"))
        items.append(
            Item(
                topic=topic_id,
                title=title,
                url=link,
                source=source["name"],
                source_type="paper",
                published=published,
                summary=truncate_text(summary, 360),
                raw_score=1.0,
                score=float(source.get("weight", 0.7)),
            )
        )
    return [item for item in items if item.title and item.url]


FETCHERS = {
    "rss": fetch_rss,
    "reddit": fetch_reddit,
    "hn_algolia": fetch_hn,
    "arxiv": fetch_arxiv,
}


def title_key(title: str) -> str:
    words = re.findall(r"[a-z0-9]{3,}", title.lower())
    ignored = {"the", "and", "for", "with", "from", "that", "this", "are", "sobre", "para", "con", "del", "las", "los"}
    return " ".join(word for word in words if word not in ignored)


def dedupe(items: list[Item]) -> list[Item]:
    seen: dict[str, Item] = {}
    for item in items:
        words = re.findall(r"[a-z0-9]{4,}", item.title.lower())
        key = " ".join(words[:10])
        if not key:
            key = item.url
        existing = seen.get(key)
        if existing is None or item.score > existing.score:
            seen[key] = item
    return list(seen.values())


def keyword_bonus(item: Item, keywords: list[str]) -> float:
    haystack = f"{item.title} {item.summary}".lower()
    hits = sum(1 for keyword in keywords if keyword.lower() in haystack)
    return min(hits * 0.16, 0.8)


def keyword_hits(item: Item, keywords: list[str]) -> int:
    haystack = f"{item.title} {item.summary} {item.url}".lower()
    return sum(1 for keyword in keywords if keyword.lower() in haystack)


def age_penalty(item: Item) -> float:
    published = parse_date(item.published)
    if not published:
        return 0.0
    hours = max((utc_now() - published).total_seconds() / 3600, 0)
    return min(hours / 120, 0.75)


def is_relevant_item(topic: dict[str, Any], item: Item) -> bool:
    keywords = topic.get("keywords", [])
    hits = keyword_hits(item, keywords)
    low_signal_patterns = (
        "housemate",
        "landlord",
        "career",
        "laid off",
        "silly question",
        "my room",
        "drying laundry",
    )
    text = f"{item.title} {item.summary}".lower()
    if any(pattern in text for pattern in low_signal_patterns):
        return False
    if item.source_type == "forum":
        if hits > 0:
            return True
        return item.raw_score >= 80
    return True


def summarize_topic(topic: dict[str, Any], items: list[Item]) -> dict[str, Any]:
    top_titles = [item.title for item in items[:6]]
    forum_count = sum(1 for item in items if item.source_type == "forum")
    sources = sorted({item.source for item in items})
    themes = extract_themes(items, topic.get("keywords", []))
    if not items:
        headline = "No se han encontrado novedades recientes en las fuentes configuradas."
        bullets = ["Revisa los avisos de fuentes para ver si alguna consulta ha fallado."]
    else:
        headline = f"{topic['label']}: {len(items)} senales relevantes detectadas en {len(sources)} fuentes."
        bullets = [
            f"Lo mas repetido gira alrededor de: {', '.join(themes[:4]) if themes else 'noticias dispersas sin tema dominante'}.",
            f"Hay {forum_count} conversaciones de foros/comunidades y {len(items) - forum_count} piezas de medios, papers o RSS.",
            f"Titulares a vigilar: {'; '.join(top_titles[:3])}.",
        ]
    return {
        "headline": headline,
        "bullets": bullets,
        "themes": themes,
        "model": "heuristic",
        "sourceCount": len(sources),
        "forumCount": forum_count,
    }


def summarize_topic_with_local_model(
    topic: dict[str, Any],
    items: list[Item],
    model_settings: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    if not model_settings.get("enabled", True):
        return None, "modelo local desactivado en config/sources.json"
    if model_settings.get("provider") != "ollama":
        return None, f"proveedor de modelo no soportado: {model_settings.get('provider')}"
    if not items:
        return None, None

    model = os.environ.get("AGENTE_SUMMARY_MODEL") or str(model_settings.get("summary_model", "llama3.1:8b"))
    base_url = str(os.environ.get("OLLAMA_BASE_URL") or model_settings.get("base_url", "http://localhost:11434")).rstrip("/")
    timeout = int(model_settings.get("timeout_seconds", 180))
    compact_items = [
        {
            "title": item.title,
            "source": item.source,
            "type": item.source_type,
            "published": item.published,
            "score": round(item.score, 2),
            "summary": item.summary[:420],
        }
        for item in items[:12]
    ]
    prompt = f"""
Eres un analista que prepara un briefing matinal para una persona en Espana.
Tema: {topic['label']}
Descripcion: {topic.get('description', '')}

Usa solo los datos de entrada. No inventes hechos, cifras ni fuentes.
Devuelve exclusivamente JSON valido con esta forma:
{{
  "headline": "una frase breve con la lectura principal",
  "bullets": ["3 puntos accionables en espanol", "sin relleno", "con cautela si la evidencia es debil"],
  "themes": ["hasta 8 temas cortos"]
}}

Datos:
{json.dumps(compact_items, ensure_ascii=False)}
""".strip()

    try:
        response = post_json(
            f"{base_url}/api/generate",
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.2,
                    "num_ctx": 8192,
                },
            },
            timeout,
        )
        parsed = json.loads(response.get("response", "{}"))
        headline = clean_text(parsed.get("headline"))[:220]
        bullets = [clean_text(str(bullet))[:260] for bullet in parsed.get("bullets", []) if clean_text(str(bullet))]
        themes = [clean_text(str(theme))[:40] for theme in parsed.get("themes", []) if clean_text(str(theme))]
        if not headline or not bullets:
            return None, "el modelo local respondio sin headline/bullets validos"
        heuristic = summarize_topic(topic, items)
        return (
            {
                "headline": headline,
                "bullets": bullets[:4],
                "themes": themes[:8] or heuristic["themes"],
                "model": f"ollama:{model}",
                "sourceCount": heuristic["sourceCount"],
                "forumCount": heuristic["forumCount"],
            },
            None,
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError) as exc:
        return None, f"Ollama/modelo local no disponible ({type(exc).__name__}: {exc})"


def build_item_translations_with_local_model(
    items: list[Item],
    model_settings: dict[str, Any],
) -> dict[int, dict[str, dict[str, str]]]:
    if not model_settings.get("enabled", True) or not items:
        return {}
    if model_settings.get("provider") != "ollama":
        return {}

    model = os.environ.get("AGENTE_TRANSLATION_MODEL") or str(model_settings.get("translation_model", "qwen2.5:3b"))
    base_url = str(os.environ.get("OLLAMA_BASE_URL") or model_settings.get("base_url", "http://localhost:11434")).rstrip("/")
    timeout = int(model_settings.get("timeout_seconds", 180))
    payload_items = [
        {
            "id": index,
            "title": truncate_text(item.title, 180),
            "summary": truncate_text(item.summary, 260),
        }
        for index, item in enumerate(items)
    ]
    translated: dict[int, dict[str, dict[str, str]]] = {}

    for chunk_start in range(0, len(payload_items), 3):
        chunk = payload_items[chunk_start : chunk_start + 3]
        prompt = f"""
Traduce y adapta para una interfaz de noticias.
Devuelve exclusivamente JSON valido con esta forma:
{{
  "items": [
    {{
      "id": 0,
      "es": {{"title": "titulo en espanol", "summary": "resumen breve en espanol"}}
    }}
  ]
}}

Reglas:
- Mantener nombres propios, productos y cifras.
- En espanol usa redaccion natural.
- Cada summary debe ser breve, claro y apto para tarjeta.

Datos:
{json.dumps(chunk, ensure_ascii=False)}
""".strip()

        try:
            response = post_json(
                f"{base_url}/api/generate",
                {
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0.1,
                        "num_ctx": 8192,
                    },
                },
                timeout,
            )
            parsed = json.loads(response.get("response", "{}"))
            for entry in parsed.get("items", []):
                try:
                    entry_id = int(entry["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                translated[entry_id] = {
                    "es": {
                        "title": truncate_text(str(entry.get("es", {}).get("title", "")), 180),
                        "summary": truncate_text(str(entry.get("es", {}).get("summary", "")), 260),
                    },
                }
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError):
            continue
    return translated


def translation_cache_key(item: Item) -> str:
    fingerprint = "||".join(
        [
            item.topic,
            item.url,
            truncate_text(item.title, 180),
            truncate_text(item.summary, 260),
        ]
    )
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


def load_translation_cache(enabled: bool) -> dict[str, dict[str, dict[str, str]]]:
    if not enabled or not TRANSLATION_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(TRANSLATION_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_translation_cache(cache: dict[str, dict[str, dict[str, str]]], enabled: bool) -> None:
    if not enabled:
        return
    DATA_DIR.mkdir(exist_ok=True)
    TRANSLATION_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def build_cached_top_translations(
    items: list[Item],
    model_settings: dict[str, Any],
    translate_top_n: int,
    cache: dict[str, dict[str, dict[str, str]]],
) -> dict[int, dict[str, dict[str, str]]]:
    results: dict[int, dict[str, dict[str, str]]] = {}
    missing_items: list[Item] = []
    missing_indexes: list[int] = []

    for index, item in enumerate(items[:translate_top_n]):
        cache_key = translation_cache_key(item)
        cached = cache.get(cache_key)
        if cached:
            results[index] = cached
            continue
        missing_items.append(item)
        missing_indexes.append(index)

    if missing_items:
        fresh = build_item_translations_with_local_model(missing_items, model_settings)
        for local_index, translated in fresh.items():
            absolute_index = missing_indexes[local_index]
            original_item = items[absolute_index]
            results[absolute_index] = translated
            cache[translation_cache_key(original_item)] = translated

    return results


def extract_themes(items: list[Item], keywords: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    text = " ".join(f"{item.title} {item.summary}" for item in items).lower()
    for keyword in keywords:
        count = text.count(keyword.lower())
        if count:
            counts[keyword] = count
    return [name for name, _ in sorted(counts.items(), key=lambda pair: pair[1], reverse=True)[:8]]


def item_to_dict(item: Item, translations: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
    base_title = truncate_text(item.title, 180)
    base_summary = truncate_text(item.summary, 260)
    return {
        "topic": item.topic,
        "title": base_title,
        "url": item.url,
        "source": item.source,
        "sourceType": item.source_type,
        "published": item.published,
        "summary": base_summary,
        "score": round(item.score, 3),
        "rawScore": round(item.raw_score, 2),
        "commentsUrl": item.comments_url,
        "translations": translations or {},
    }


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def run() -> int:
    config = load_config()
    settings = config.get("settings", {})
    model_settings = settings.get("local_models", {})
    cache_enabled = bool(settings.get("translation_cache_enabled", True))
    translate_top_n = int(settings.get("translate_top_items_per_topic", 5))
    timeout = int(settings.get("request_timeout_seconds", 18))
    max_items = int(settings.get("max_items_per_topic", 18))
    lookback_hours = int(settings.get("lookback_hours", 72))
    cutoff = utc_now() - timedelta(hours=lookback_hours)
    digest_topics = []
    errors = []
    translation_cache = load_translation_cache(cache_enabled)

    for topic in config["topics"]:
        collected: list[Item] = []
        for source in topic["sources"]:
            fetcher = FETCHERS.get(source["type"])
            if not fetcher:
                errors.append(f"{topic['id']} / {source['name']}: tipo no soportado {source['type']}")
                continue
            try:
                collected.extend(fetcher(topic["id"], source, timeout))
            except (urllib.error.URLError, TimeoutError, ET.ParseError, json.JSONDecodeError, KeyError) as exc:
                errors.append(f"{topic['id']} / {source['name']}: {type(exc).__name__} - {exc}")

        fresh_items = []
        for item in collected:
            published = parse_date(item.published)
            if published is None or published >= cutoff:
                item.score = item.score + keyword_bonus(item, topic.get("keywords", [])) - age_penalty(item)
                if is_relevant_item(topic, item):
                    fresh_items.append(item)

        ranked = sorted(dedupe(fresh_items), key=lambda candidate: candidate.score, reverse=True)[:max_items]
        model_summary, model_error = summarize_topic_with_local_model(topic, ranked, model_settings)
        item_translations = build_cached_top_translations(
            ranked,
            model_settings,
            translate_top_n,
            translation_cache,
        )
        if model_error:
            errors.append(f"{topic['id']} / modelo local: {model_error}")
        digest_topics.append(
            {
                "id": topic["id"],
                "label": topic["label"],
                "description": topic["description"],
                "summary": model_summary or summarize_topic(topic, ranked),
                "items": [
                    item_to_dict(item, item_translations.get(index))
                    for index, item in enumerate(ranked)
                ],
            }
        )

    generated_at = utc_now().isoformat()
    digest = {
        "generatedAt": generated_at,
        "settings": {
            "lookbackHours": lookback_hours,
            "maxItemsPerTopic": max_items,
        },
        "topics": digest_topics,
        "errors": errors,
    }

    DATA_DIR.mkdir(exist_ok=True)
    save_translation_cache(translation_cache, cache_enabled)
    JSON_DATA_PATH.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
    public_payload = "window.DIGEST_DATA = " + json.dumps(digest, ensure_ascii=False, indent=2) + ";\n"
    PUBLIC_DATA_PATH.write_text(public_payload, encoding="utf-8")
    PUBLIC_SITE_DATA_PATH.write_text(public_payload, encoding="utf-8")
    print(f"Informe actualizado: {PUBLIC_DATA_PATH}")
    print(f"Temas: {', '.join(topic['label'] for topic in digest_topics)}")
    if errors:
        print("Avisos de fuentes:")
        for error in errors:
            print(f"- {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
