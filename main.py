#!/usr/bin/env python3
"""
AutoRSS Lite (one-shot) — static site generator for GitHub Pages.

- Reads config.json (required).
- Fetches ONE item from ONE RSS URL.
- Uses DeepSeek (OpenAI-compatible) to generate an HTML body.
- Renders a small static site into the repository root (GitHub Pages: main / root).
- Lite lock: can only run once (creates .lite_lock.json).

No ads. No affiliate. No scheduling. No background automation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import feedparser
import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape
from slugify import slugify


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
CONFIG_EXAMPLE_PATH = ROOT / "config.example.json"
LITE_LOCK_PATH = ROOT / ".lite_lock.json"

TEMPLATES_DIR = ROOT / "templates"
ASSETS_SRC_DIR = ROOT / "assets"  # Source assets shipped with the tool
ASSETS_OUT_DIR = ROOT / "assets"  # Output assets (same path for Pages root)

POSTS_DIR = ROOT / "posts"


# -----------------------------
# Utilities
# -----------------------------
def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, s: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(s, encoding="utf-8")


def write_bytes(path: Path, b: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b)


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def strip_tags(html: str) -> str:
    return normalize_ws(re.sub(r"(?is)<[^>]+>", " ", html or ""))


def safe_filename(s: str) -> str:
    return slugify(s)[:80] or "post"


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


# -----------------------------
# Config
# -----------------------------
@dataclass
class SiteConfig:
    title: str
    description: str
    base_url: str


@dataclass
class GenConfig:
    model: str
    temperature: float
    max_tokens: int


@dataclass
class AppConfig:
    site: SiteConfig
    rss_url: str
    generation: GenConfig
    contact_email: str


def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        die('Copy config.example.json to config.json', code=2)

    cfg = read_json(CONFIG_PATH)

    # Required fields (keep errors beginner-clear)
    site = cfg.get("site") or {}
    title = str(site.get("title") or "").strip()
    desc = str(site.get("description") or "").strip()
    base_url = str(site.get("base_url") or "").strip().rstrip("/")

    rss_url = str(cfg.get("rss_url") or "").strip()

    gen = cfg.get("generation") or {}
    model = str(gen.get("model") or "deepseek-chat").strip()
    temperature = float(gen.get("temperature") if gen.get("temperature") is not None else 0.7)
    max_tokens = int(gen.get("max_tokens") if gen.get("max_tokens") is not None else 2200)

    contact_email = str(cfg.get("contact_email") or "").strip()

    missing = []
    if not title:
        missing.append("site.title")
    if not desc:
        missing.append("site.description")
    if not base_url:
        missing.append("site.base_url")
    if not rss_url:
        missing.append("rss_url")
    if not contact_email:
        missing.append("contact_email")

    if missing:
        die("Missing required config fields: " + ", ".join(missing), code=2)

    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        die("config.site.base_url must start with https:// (example: https://YOURNAME.github.io/YOURREPO)", code=2)

    return AppConfig(
        site=SiteConfig(title=title, description=desc, base_url=base_url),
        rss_url=rss_url,
        generation=GenConfig(model=model, temperature=temperature, max_tokens=max_tokens),
        contact_email=contact_email,
    )


# -----------------------------
# DeepSeek (OpenAI-compatible)
# -----------------------------
def deepseek_chat(api_key: str, model: str, temperature: float, max_tokens: int, system: str, user: str) -> str:
    """
    DeepSeek is OpenAI-compatible. This uses the chat/completions endpoint.
    """
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    r = requests.post(url, headers=headers, json=payload, timeout=60)
    if r.status_code != 200:
        die(f"DeepSeek API error: HTTP {r.status_code}\n{r.text[:800]}", code=3)

    data = r.json()
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        die("DeepSeek API response format unexpected.", code=3)


# -----------------------------
# RSS
# -----------------------------
def fetch_latest_item(rss_url: str) -> Dict[str, Any]:
    """
    Fetch RSS and return the latest entry.
    """
    r = requests.get(rss_url, timeout=30, headers={"User-Agent": "AutoRSSLite/1.0"})
    r.raise_for_status()
    feed = feedparser.parse(r.text)

    if not feed.entries:
        die("RSS has no entries.", code=4)

    e = feed.entries[0]
    title = str(e.get("title") or "").strip()
    link = str(e.get("link") or "").strip()
    summary = str(e.get("summary") or e.get("description") or "").strip()
    published = str(e.get("published") or e.get("updated") or "").strip()

    if not title or not link:
        die("RSS entry is missing title/link.", code=4)

    return {
        "title": title,
        "link": link,
        "summary": summary,
        "published": published,
        "rss_url": rss_url,
        "_raw_entry": e,
    }


# -----------------------------
# Rendering
# -----------------------------
def jinja_env() -> Environment:
    if not TEMPLATES_DIR.exists():
        die(f"templates/ folder missing: {TEMPLATES_DIR}", code=5)

    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )


def build_robots(base_url: str) -> str:
    return f"""User-agent: *
Allow: /

Sitemap: {base_url}/sitemap.xml
"""


def build_sitemap(urls: list[str]) -> str:
    items = "\n".join([f"<url><loc>{u}</loc></url>" for u in urls])
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{items}
</urlset>
"""


def copy_assets() -> None:
    # Keep design: just ensure assets/style.css exists in output location.
    css = ASSETS_SRC_DIR / "style.css"
    if not css.exists():
        die("assets/style.css missing.", code=5)
    # Overwrite (generated output)
    write_text(ASSETS_OUT_DIR / "style.css", css.read_text(encoding="utf-8"))

    # Optional app.js
    appjs = ASSETS_SRC_DIR / "app.js"
    if appjs.exists():
        write_text(ASSETS_OUT_DIR / "app.js", appjs.read_text(encoding="utf-8"))


def render_site(cfg: AppConfig, item: Dict[str, Any], body_html: str) -> Tuple[str, str]:
    """
    Render:
      - index.html
      - posts/<slug>.html
      - robots.txt
      - sitemap.xml

    Returns (post_rel_path, post_url)
    """
    env = jinja_env()

    # Published datetime (best-effort)
    published_dt = None
    try:
        # feedparser sometimes provides a struct_time
        if getattr(item.get("_raw_entry"), "published_parsed", None):
            import time
            published_dt = datetime.fromtimestamp(time.mktime(item["_raw_entry"].published_parsed), tz=timezone.utc)
    except Exception:
        published_dt = None

    if not published_dt:
        published_dt = datetime.now(timezone.utc)

    slug = safe_filename(item["title"])
    post_rel = f"posts/{slug}.html"

    post_url = cfg.site.base_url + "/" + post_rel
    index_url = cfg.site.base_url + "/index.html"

    post_obj = {
        "slug": slug,
        "title": item["title"],
        "source": item["link"],
        "url": item["link"],
        "published": published_dt,
        "summary": strip_tags(item.get("summary", "")),
    }

    # index
    tpl_index = env.get_template("index.html")
    index_html = tpl_index.render(
        site_title=cfg.site.title,
        site_description=cfg.site.description,
        base_url=cfg.site.base_url,
        generated_at=datetime.now(timezone.utc),
        posts=[post_obj],
    )
    write_text(ROOT / "index.html", index_html)

    # post
    tpl_post = env.get_template("post.html")
    post_html = tpl_post.render(
        site_title=cfg.site.title,
        base_url=cfg.site.base_url,
        post={
            **post_obj,
            "summary": post_obj["summary"],
            "body_html": body_html,
            "rss_url": item["rss_url"],
            "generated_utc": now_utc_iso(),
            "contact_email": cfg.contact_email,
        },
    )

    # The shipped template uses post.summary and post.url; we inject body_html by replacing a placeholder div
    # If the template already contains {{ post.body_html|safe }}, it will be used directly.
    write_text(ROOT / post_rel, post_html)

    # robots/sitemap
    urls = [cfg.site.base_url + "/", cfg.site.base_url + "/index.html", post_url]
    write_text(ROOT / "robots.txt", build_robots(cfg.site.base_url))
    write_text(ROOT / "sitemap.xml", build_sitemap(urls))

    return post_rel, post_url
# Lite lock
# -----------------------------
def check_lite_lock() -> None:
    if LITE_LOCK_PATH.exists():
        data = {}
        try:
            data = read_json(LITE_LOCK_PATH)
        except Exception:
            pass
        when = data.get("created_utc") if isinstance(data, dict) else None
        msg = "LITE already ran once. This package is one-shot by design."
        if when:
            msg += f" (first run: {when})"
        print(msg)
        raise SystemExit(0)


def write_lite_lock(post_url: str) -> None:
    payload = {
        "created_utc": now_utc_iso(),
        "post_url": post_url,
        "note": "Lite one-shot lock. Delete this file if you are the author and want to rerun locally.",
    }
    write_text(LITE_LOCK_PATH, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


# -----------------------------
# Generation prompt
# -----------------------------
def generate_body_html(cfg: AppConfig, item: Dict[str, Any]) -> str:
    api_key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        die("Missing DEEPSEEK_API_KEY (set it as a GitHub Actions secret).", code=2)

    title = item["title"]
    link = item["link"]
    summary = strip_tags(item.get("summary", ""))[:800]

    system = (
        "You are a careful technical writer. Write in English only. "
        "Do not fabricate facts. If something is not stated in the source, say: 'Not stated in the source.' "
        "Output HTML only (no markdown)."
    )

    user = f"""
OUTPUT RULES:
- Output HTML body only.
- Allowed tags: <p>, <h2>, <ul>, <li>, <strong>, <code>, <a>
- No <h1>.
- No scripts.
- Be concise but useful.

INPUT:
Title: {title}
Link: {link}
RSS snippet: {summary}

STRUCTURE:
1) <p><strong>Summary</strong>: 2–4 sentences. Mention what happened and who it matters to.</p>
2) <h2>Key points</h2> + 4–6 bullets
3) <h2>Practical takeaway</h2> + 2–4 bullets
4) <h2>Original source</h2> link to the URL
""".strip()

    out = deepseek_chat(
        api_key=api_key,
        model=cfg.generation.model,
        temperature=cfg.generation.temperature,
        max_tokens=cfg.generation.max_tokens,
        system=system,
        user=user,
    )

    # Safety: keep only allowed tags (very lightweight sanitizer)
    allowed = {"p", "h2", "ul", "li", "strong", "code", "a"}
    # remove script/style tags and their content
    out = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1\s*>", "", out).strip()
    # remove any other tags not in allowed
    def _strip_disallowed(m: re.Match) -> str:
        tag = (m.group(1) or "").lower()
        return m.group(0) if tag in allowed else ""

    out = re.sub(r"(?is)</?([a-z0-9]+)(\s+[^>]*)?>", _strip_disallowed, out)

    if not out:
        out = "<p><strong>Summary</strong>: Not stated in the source.</p>"

    return out


# -----------------------------
# Self test
# -----------------------------
def selftest() -> None:
    """
    Fast local sanity checks (also runs in Actions).
    """
    if not CONFIG_EXAMPLE_PATH.exists():
        die("config.example.json missing.", code=5)
    if not (TEMPLATES_DIR / "index.html").exists():
        die("templates/index.html missing.", code=5)
    if not (TEMPLATES_DIR / "post.html").exists():
        die("templates/post.html missing.", code=5)
    if not (ASSETS_SRC_DIR / "style.css").exists():
        die("assets/style.css missing.", code=5)
    print("SELFTEST OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true", help="run quick sanity checks")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    check_lite_lock()
    cfg = load_config()

    item = fetch_latest_item(cfg.rss_url)
    body_html = generate_body_html(cfg, item)

    copy_assets()
    _post_rel, post_url = render_site(cfg, item, body_html)
    write_lite_lock(post_url)

    print("DONE")
    print(f"Post: {post_url}")


if __name__ == "__main__":
    main()
