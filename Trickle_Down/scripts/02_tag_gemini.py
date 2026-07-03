"""P1 — Gemini vision tagging: every runway look -> materials/colors/category.

For each look in runway_looks.csv not yet tagged, download the image once to
data/runway/images/ (cache), send it to Gemini with a strict JSON response
schema built from config/material_taxonomy.json, validate/renormalize, and
upsert into runway_tags.csv / runway_colors.csv / runway_categories.csv.

Cost note (gemini-2.5-flash, mid-2026 pricing ~$0.30/M input, $2.50/M output):
one look is roughly an image (~560 tok, downscaled to 768px) + ~200 prompt tok
+ ~150 output tok => ~$0.0006/look, i.e. ~$0.60 per 1,000 looks. The full
~2015-2026 backfill (~25k looks) is on the order of $15.

Requires: GEMINI_API_KEY env var, google-genai package.
Output:   data/runway/runway_tags.csv, runway_colors.csv, runway_categories.csv
Soft log: data/runway/_tag_failures.csv (API/parse failures; run continues)
Resume:   data/runway/_tag_progress.json  look_id -> "ok"|"fail"
Flags:    --limit N  --season SS2025  --model gemini-2.5-flash
          --retry-failures (re-attempt previous fails)
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import random
import sys
import time
from datetime import date

import pandas as pd
import requests
from tqdm import tqdm

import lib_trickle as lt

try:
    from google import genai
    from google.genai import types
except ImportError:  # surfaced as a clear error in main()
    genai = None
    types = None

log = lt.get_logger("02_tag_gemini")

TAGS_CSV = lt.RUNWAY / "runway_tags.csv"
COLORS_CSV = lt.RUNWAY / "runway_colors.csv"
CATS_CSV = lt.RUNWAY / "runway_categories.csv"
FAIL_CSV = lt.RUNWAY / "_tag_failures.csv"
PROGRESS = lt.RUNWAY / "_tag_progress.json"
IMG_DIR = lt.RUNWAY / "images"

FLUSH_EVERY = 20
MAX_IMG_DIM = 768

PROMPT = (
    "You are tagging a single runway look for a quantitative fashion-trend "
    "study. Estimate the visible garment(s) only (ignore background, skin, "
    "hair). Return: materials — the apparent fabric composition of the outfit "
    "as worn, 1-4 entries with shares summing to 1.0 (best visual estimate; "
    "e.g. a wool coat over a silk dress seen half-and-half => wool 0.5, silk "
    "0.5); colors — the 1-3 dominant garment colors with weights summing to "
    "1.0; category — the single dominant garment type. Use only the enum "
    "values provided by the schema. If the fabric is ambiguous, pick the most "
    "likely canonical material rather than 'other'; use 'other' only for "
    "clearly non-listed materials (feathers, raffia, metal, PVC-look plastics)."
)


def build_schema() -> dict:
    tax = lt.load_taxonomy()
    return {
        "type": "OBJECT",
        "properties": {
            "materials": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "material": {"type": "STRING",
                                     "enum": lt.canonical_materials()},
                        "share": {"type": "NUMBER"},
                    },
                    "required": ["material", "share"],
                },
            },
            "colors": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "color": {"type": "STRING", "enum": tax["colors"]},
                        "weight": {"type": "NUMBER"},
                    },
                    "required": ["color", "weight"],
                },
            },
            "category": {"type": "STRING", "enum": tax["categories"]},
        },
        "required": ["materials", "colors", "category"],
    }


class QuotaExhausted(Exception):
    """Provider returned 429 — stop the run, leave remaining looks pending."""


PROVIDERS = {
    "groq": {"base": "https://api.groq.com/openai/v1",
             "env": "GROQ_API_KEY",
             "default_model": "meta-llama/llama-4-scout-17b-16e-instruct"},
    "mistral": {"base": "https://api.mistral.ai/v1",
                "env": "MISTRAL_API_KEY",
                "default_model": "pixtral-12b-2409"},
}


def tag_openai_compat(img: bytes, provider: str, model: str,
                      session: requests.Session) -> dict:
    """Vision tag via an OpenAI-compatible endpoint (Groq / Mistral).

    Same PROMPT as Gemini; enums are inlined in the instruction since these
    endpoints lack response_schema. Output goes through the same
    validate_result() as Gemini, so off-enum answers are normalized/dropped
    identically. Model is recorded per look in _tag_log.csv (DECISIONS.md
    multi-model disclosure)."""
    import base64
    cfg = PROVIDERS[provider]
    key = os.environ.get(cfg["env"])
    if not key:
        raise RuntimeError(f"{cfg['env']} not set")
    tax = lt.load_taxonomy()
    instr = (
        PROMPT + " Respond with ONLY a JSON object exactly shaped as "
        '{"materials":[{"material":"...","share":0.0}],'
        '"colors":[{"color":"...","weight":0.0}],"category":"..."} using '
        f"material values from {lt.canonical_materials()}, color values from "
        f"{tax['colors']}, category values from {tax['categories']}.")
    b64 = base64.b64encode(img).decode()
    r = session.post(
        f"{cfg['base']}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model,
              "messages": [{"role": "user", "content": [
                  {"type": "image_url",
                   "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                  {"type": "text", "text": instr}]}],
              "response_format": {"type": "json_object"},
              "temperature": 0.0, "max_tokens": 400},
        timeout=60)
    if r.status_code == 429:
        raise QuotaExhausted(r.text[:200])
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"]["content"].strip()
    if txt.startswith("```"):
        txt = txt.strip("`").removeprefix("json").strip()
    return json.loads(txt)


def img_cache_path(look_id: str):
    return IMG_DIR / (look_id.replace("|", "__") + ".jpg")


def fetch_image(look_id: str, url: str, session: requests.Session) -> bytes | None:
    """Download-once cache; downscale to MAX_IMG_DIM to cut token cost."""
    path = img_cache_path(look_id)
    if path.exists() and path.stat().st_size > 0:
        return path.read_bytes()
    try:
        r = session.get(url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
        if r.status_code != 200 or not r.content:
            return None
        data = r.content
    except requests.RequestException as e:
        log.warning("image fetch failed %s: %s", look_id, e)
        return None
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((MAX_IMG_DIM, MAX_IMG_DIM))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        data = buf.getvalue()
    except Exception:
        pass  # send the original bytes if Pillow chokes
    path.write_bytes(data)
    return data


def validate_result(raw: dict, tax: dict) -> tuple[list, list, str] | None:
    """Normalize a Gemini response into (materials, colors, category) rows."""
    mats: dict[str, float] = {}
    for m in raw.get("materials", []):
        canon = lt.normalize_material(str(m.get("material", ""))) or "other"
        try:
            share = float(m.get("share", 0))
        except (TypeError, ValueError):
            continue
        if share > 0:
            mats[canon] = mats.get(canon, 0.0) + min(share, 1.0)
    total = sum(mats.values())
    if total <= 0:
        return None
    materials = [(mat, round(v / total, 6)) for mat, v in mats.items()]

    cols: dict[str, float] = {}
    for c in raw.get("colors", []):
        name = str(c.get("color", "")).lower().strip()
        if name not in tax["colors"]:
            continue
        try:
            w = float(c.get("weight", 0))
        except (TypeError, ValueError):
            continue
        if w > 0:
            cols[name] = cols.get(name, 0.0) + min(w, 1.0)
    ctotal = sum(cols.values())
    colors = [(c, round(w / ctotal, 6)) for c, w in cols.items()] if ctotal > 0 else []

    category = str(raw.get("category", "")).lower().strip()
    if category not in tax["categories"]:
        category = "unknown"
    return materials, colors, category


def append_failure(look_id: str, reason: str) -> None:
    row = pd.DataFrame([{"look_id": look_id, "reason": reason[:300],
                         "logged": date.today().isoformat()}])
    row.to_csv(FAIL_CSV, mode="a", header=not FAIL_CSV.exists(), index=False)


def flush(tag_rows: list, color_rows: list, cat_rows: list, progress: dict) -> None:
    if tag_rows:
        lt.upsert_csv(pd.DataFrame(tag_rows), TAGS_CSV,
                      keys=["look_id", "material"], sort_by=["look_id"])
        tag_rows.clear()
    if color_rows:
        lt.upsert_csv(pd.DataFrame(color_rows), COLORS_CSV,
                      keys=["look_id", "color"], sort_by=["look_id"])
        color_rows.clear()
    if cat_rows:
        lt.upsert_csv(pd.DataFrame(cat_rows), CATS_CSV,
                      keys=["look_id"], sort_by=["look_id"])
        cat_rows.clear()
    lt.save_progress(progress, PROGRESS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="tag at most N looks")
    ap.add_argument("--season", default="", help="only this season_code")
    ap.add_argument("--model", default="")
    ap.add_argument("--provider", choices=["gemini", "groq", "mistral"],
                    default="gemini")
    ap.add_argument("--retry-failures", action="store_true")
    ap.add_argument("--pace", type=float, default=5.5,
                    help="seconds between requests (free tier ~10 RPM)")
    args = ap.parse_args()
    if not args.model:
        args.model = ("gemini-2.5-flash" if args.provider == "gemini"
                      else PROVIDERS[args.provider]["default_model"])

    if args.provider == "gemini":
        if genai is None:
            log.error("google-genai not installed (pip install google-genai)")
            return 1
        if not os.environ.get("GEMINI_API_KEY"):
            log.error("GEMINI_API_KEY not set")
            return 1
    elif not os.environ.get(PROVIDERS[args.provider]["env"]):
        log.error("%s not set", PROVIDERS[args.provider]["env"])
        return 1

    lt.ensure_dirs()
    looks = lt.read_csv_or_empty(lt.RUNWAY / "runway_looks.csv")
    if looks.empty:
        log.error("runway_looks.csv is empty — run 01_scrape_runway.py first")
        return 1
    if args.season:
        looks = looks[looks["season_code"] == args.season]

    progress = lt.load_progress(PROGRESS)
    if args.retry_failures:
        progress = {k: v for k, v in progress.items() if v != "fail"}
    pending = looks[~looks["look_id"].isin(progress.keys())].copy()
    # breadth-first: 1st look of every show, then 2nd, ... — coverage grows
    # across all brands/seasons instead of depleting one brand at a time
    pending["_rank"] = pending.groupby(["brand_slug", "season_code"]).cumcount()
    pending = (pending.sort_values(["_rank", "season_code", "brand_slug"])
               .drop(columns="_rank"))
    if args.limit:
        pending = pending.head(args.limit)
    log.info("%d looks pending (%d already done/failed)", len(pending), len(progress))
    if pending.empty:
        return 0

    tax = lt.load_taxonomy()
    schema = build_schema()
    client = genai.Client() if args.provider == "gemini" else None
    session = requests.Session()
    tag_rows: list[dict] = []
    color_rows: list[dict] = []
    cat_rows: list[dict] = []
    n_ok = n_fail = 0

    for _, look in tqdm(pending.iterrows(), total=len(pending), desc="gemini tag"):
        look_id = look["look_id"]
        img = fetch_image(look_id, look["image_url"], session)
        if img is None:
            progress[look_id] = "fail"
            append_failure(look_id, "image download failed")
            n_fail += 1
            continue
        try:
            if args.provider == "gemini":
                resp = client.models.generate_content(
                    model=args.model,
                    contents=[types.Part.from_bytes(data=img,
                                                    mime_type="image/jpeg"),
                              PROMPT],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=schema,
                        temperature=0.0,
                    ),
                )
                raw = json.loads(resp.text)
            else:
                raw = tag_openai_compat(img, args.provider, args.model, session)
            parsed = validate_result(raw, tax)
        except QuotaExhausted:
            log.warning("quota exhausted on %s — stopping run; remaining "
                        "looks stay pending for the daily job", args.model)
            break
        except Exception as e:  # API error, JSON error, schema drift
            msg = str(e)
            if ("429" in msg or "RESOURCE_EXHAUSTED" in msg
                    or "quota" in msg.lower()):
                log.warning("quota exhausted on %s — stopping run; remaining "
                            "looks stay pending for the daily job", args.model)
                break
            progress[look_id] = "fail"
            append_failure(look_id, f"{type(e).__name__}: {e}")
            n_fail += 1
            time.sleep(args.pace + random.uniform(0, 1.5))
            continue
        if parsed is None:
            progress[look_id] = "fail"
            append_failure(look_id, "empty/invalid materials")
            n_fail += 1
            continue

        materials, colors, category = parsed
        tag_rows.extend({"look_id": look_id, "material": m, "share": s}
                        for m, s in materials)
        color_rows.extend({"look_id": look_id, "color": c, "weight": w}
                          for c, w in colors)
        cat_rows.append({"look_id": look_id, "category": category})
        with open(lt.RUNWAY / "_tag_log.csv", "a", encoding="utf-8") as f:
            if f.tell() == 0:
                f.write("look_id,model,tagged_at\n")
            f.write(f"{look_id},{args.model},{date.today().isoformat()}\n")
        progress[look_id] = "ok"
        n_ok += 1
        if n_ok % FLUSH_EVERY == 0:
            flush(tag_rows, color_rows, cat_rows, progress)
        time.sleep(args.pace + random.uniform(0, 1.5))

    flush(tag_rows, color_rows, cat_rows, progress)
    log.info("tagging done: +%d ok, +%d fail (model=%s)", n_ok, n_fail, args.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
