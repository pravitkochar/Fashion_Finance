"""P2 — downstream catalog collection: retailer new-in items + composition.

Adapter architecture (the decided scrape-with-fallback design): every source
implements CatalogSource and yields dicts matching the downstream_items.csv
contract, so the pipeline downstream of this script never cares where the
data came from. Live adapters hit retailers' own public listing JSON
endpoints at a deliberately tiny request volume (this is personal research:
2-4s jitter between requests, composition detail fetched for at most
--detail-cap items per retailer per run). Endpoints drift and retailers
block — every request is wrapped, and any 403/429/schema miss logs to
data/_source_log.csv via lt.log_source_event and the adapter exits cleanly.

Fallback: DatasetSource reads any *.csv dropped into
data/downstream/datasets/ with a sibling {name}.mapping.json:
    {"retailer": "zara",
     "columns": {"product_name": "name", "url": "link",
                 "composition_raw": "composition", "category": "cat",
                 "price": "price", "currency": "currency", "date": "scraped"}}
Only "product_name" and one of "url"/"composition_raw" are required.

PIT note: first_seen is preserved from the existing CSV when an item is seen
again (composition updates, first_seen does not). Tag rows for items touched
this run are fully replaced, so a corrected composition cannot leave stale
material rows behind.

Denim rule (locked in DECISIONS.md/taxonomy): if category or product name
matches denim/jean, the item's cotton share is emitted as 'denim'.

Output:  data/downstream/downstream_items.csv, downstream_tags.csv
Resume:  data/downstream/_scrape_progress.json (per-retailer run stats;
         dedupe itself is via item_id upsert)
Flags:   --retailers zara,hm  --source auto|live|dataset  --limit N
         --detail-cap N (default 150)
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
import time
from datetime import date

import pandas as pd
import requests

try:
    from curl_cffi import requests as cf_requests
    from curl_cffi.requests.exceptions import RequestException as \
        CF_REQUEST_EXCEPTION
except ImportError:                                    # pragma: no cover
    cf_requests = None
    CF_REQUEST_EXCEPTION = requests.RequestException

import lib_trickle as lt

log = lt.get_logger("03_scrape_downstream")

ITEMS_CSV = lt.DOWNSTREAM / "downstream_items.csv"
TAGS_CSV = lt.DOWNSTREAM / "downstream_tags.csv"
PROGRESS = lt.DOWNSTREAM / "_scrape_progress.json"
DATASET_DIR = lt.DOWNSTREAM / "datasets"

TIMEOUT = 25
DENIM_RE = re.compile(r"\b(denim|jeans?)\b", re.I)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def jitter() -> None:
    time.sleep(random.uniform(2.0, 4.0))


def walk_collect(obj, pred, out=None) -> list:
    """Recursively collect dicts anywhere in a JSON tree matching pred."""
    if out is None:
        out = []
    if isinstance(obj, dict):
        if pred(obj):
            out.append(obj)
        for v in obj.values():
            walk_collect(v, pred, out)
    elif isinstance(obj, list):
        for v in obj:
            walk_collect(v, pred, out)
    return out


def walk_first_key(obj, key):
    """First value found for `key` anywhere in a JSON tree, else None."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = walk_first_key(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = walk_first_key(v, key)
            if found is not None:
                return found
    return None


class CatalogSource:
    """One catalog source; yields dicts per the downstream_items contract."""

    name = "abstract"
    retailer = ""
    ticker = ""

    def __init__(self, session: requests.Session, detail_cap: int = 150):
        self.session = session
        self.detail_cap = detail_cap
        self.blocked = False

    def iter_items(self, limit: int = 0):
        raise NotImplementedError

    # ------------------------------------------------------------- helpers --
    def _get(self, url: str, as_json: bool = True):
        """GET with jitter + block handling. Returns parsed body or None."""
        if self.blocked:
            return None
        try:
            r = self.session.get(url, headers=HEADERS, timeout=TIMEOUT)
        except (requests.RequestException, CF_REQUEST_EXCEPTION) as e:
            lt.log_source_event(self.retailer, self.name, "request_error",
                                f"{url} {e}")
            return None
        finally:
            jitter()
        if r.status_code in (403, 429):
            self.blocked = True
            lt.log_source_event(self.retailer, self.name, "blocked",
                                f"{r.status_code} {url}")
            log.warning("%s blocked (%s) — adapter stopping cleanly",
                        self.name, r.status_code)
            return None
        if r.status_code != 200:
            return None
        if not as_json:
            return r.text
        try:
            return r.json()
        except ValueError:
            lt.log_source_event(self.retailer, self.name, "schema_drift",
                                f"non-JSON at {url}")
            return None

    def _item(self, product_name: str, url: str, category: str = "",
              composition_raw: str = "", price=None, currency: str = "") -> dict:
        return {
            "item_id": lt.stable_id(self.retailer, url),
            "retailer": self.retailer,
            "ticker": self.ticker,
            "product_name": (product_name or "").strip(),
            "category": (category or "").strip().lower(),
            "url": url,
            "first_seen": date.today().isoformat(),
            "composition_raw": composition_raw or "",
            "price": price if price is not None else "",
            "currency": currency,
            "source": self.name,
        }


class ZaraSource(CatalogSource):
    """Zara public ajax endpoints (zara.com/es/en). Composition from the
    products-details endpoint's detailedComposition tree."""

    name = "zara_live"
    retailer = "zara"
    ticker = "ITX.MC"
    base = "https://www.zara.com/es/en"

    def _new_in_category_ids(self) -> list[int]:
        data = self._get(f"{self.base}/categories?ajax=true")
        if data is None:
            return []
        cats = walk_collect(
            data, lambda d: isinstance(d.get("id"), int) and "name" in d
            and isinstance(d.get("name"), str))
        ids = []
        for c in cats:
            name = c.get("name", "").upper()
            section = str(c.get("sectionName", "")).upper()
            if "NEW" in name and section in ("WOMAN", "WOMEN", ""):
                ids.append(c["id"])
        if not ids:
            lt.log_source_event(self.retailer, self.name, "schema_drift",
                                "no NEW categories found")
        return ids[:3]

    def _composition(self, product_id) -> str:
        data = self._get(
            f"{self.base}/products-details?productIds={product_id}&ajax=true")
        if data is None:
            return ""
        comp = walk_first_key(data, "detailedComposition")
        if not comp:
            return ""
        parts = []
        for part in walk_collect(comp, lambda d: "components" in d):
            label = part.get("description", "") or part.get("name", "")
            comps = [f"{c.get('percentage', '')} {c.get('material', '')}".strip()
                     for c in part.get("components", []) if isinstance(c, dict)]
            if comps:
                parts.append((f"{label}: " if label else "") + ", ".join(comps))
        return "; ".join(parts)

    def iter_items(self, limit: int = 0):
        n = 0
        detail_used = 0
        for cid in self._new_in_category_ids():
            if self.blocked:
                return
            data = self._get(f"{self.base}/category/{cid}/products?ajax=true")
            if data is None:
                continue
            products = walk_collect(
                data, lambda d: "seo" in d and "name" in d and "id" in d)
            for p in products:
                seo = p.get("seo") or {}
                keyword = seo.get("keyword", "")
                seo_id = seo.get("seoProductId", "")
                if not keyword or not seo_id:
                    continue
                url = f"{self.base}/{keyword}-p{seo_id}.html"
                comp = ""
                if detail_used < self.detail_cap and not self.blocked:
                    comp = self._composition(p["id"])
                    detail_used += 1
                price = p.get("price")
                yield self._item(p.get("name", ""), url,
                                 category="new-in",
                                 composition_raw=comp,
                                 price=(price / 100.0) if isinstance(price, (int, float)) else None,
                                 currency="EUR")
                n += 1
                if limit and n >= limit:
                    return


class HMSource(CatalogSource):
    """H&M search-service listing + composition regexed off product pages."""

    name = "hm_live"
    retailer = "hm"
    ticker = "HM-B.ST"
    listing = ("https://api.hm.com/search-services/v1/en_US/listing/resultpage"
               "?page=1&pageSize=72&categoryId=ladies_newarrivals"
               "&touchPoint=DESKTOP&pageId=/ladies/new-arrivals")

    _COMP_RE = re.compile(r"\d{1,3}\s*%\s*[A-Za-z][A-Za-z ]{2,30}")

    def _composition_from_page(self, url: str) -> str:
        html = self._get(url, as_json=False)
        if not html:
            return ""
        found = self._COMP_RE.findall(html)
        # keep unique matches, page order, cap to avoid picking up footers
        seen, keep = set(), []
        for f in found:
            f = f.strip()
            if f.lower() not in seen:
                seen.add(f.lower())
                keep.append(f)
            if len(keep) >= 6:
                break
        return ", ".join(keep)

    def iter_items(self, limit: int = 0):
        data = self._get(self.listing)
        if data is None:
            return
        products = walk_collect(
            data, lambda d: ("productName" in d or "name" in d) and "url" in d)
        if not products:
            lt.log_source_event(self.retailer, self.name, "schema_drift",
                                "no products in listing response")
            return
        n = detail_used = 0
        for p in products:
            rel = p.get("url", "")
            url = rel if rel.startswith("http") else f"https://www2.hm.com{rel}"
            comp = ""
            if detail_used < self.detail_cap and not self.blocked:
                comp = self._composition_from_page(url)
                detail_used += 1
            price = walk_first_key(p, "price")
            if isinstance(price, dict):
                price = price.get("value")
            yield self._item(p.get("productName") or p.get("name", ""), url,
                             category="new-arrivals", composition_raw=comp,
                             price=price if isinstance(price, (int, float)) else None,
                             currency="USD")
            n += 1
            if limit and n >= limit:
                return


class UniqloSource(CatalogSource):
    """Uniqlo US commerce API; composition from per-product materialDescription."""

    name = "uniqlo_live"
    retailer = "uniqlo"
    ticker = "9983.T"
    base = "https://www.uniqlo.com/us/api/commerce/v5/en"

    def _composition(self, product_id: str) -> str:
        data = self._get(f"{self.base}/products/{product_id}")
        if data is None:
            return ""
        for key in ("materialDescription", "material", "composition"):
            val = walk_first_key(data, key)
            if isinstance(val, str) and "%" in val:
                return val
        return ""

    # the bare /products listing returns an empty items array — the v5 API
    # only serves results against a query, so approximate new-in coverage
    # with a keyword sweep deduped by productId
    QUERIES = ["new", "t-shirt", "shirt", "dress", "pants", "jeans",
               "knit", "jacket", "skirt"]

    def iter_items(self, limit: int = 0):
        seen: set[str] = set()
        n = detail_used = 0
        for q in self.QUERIES:
            data = self._get(f"{self.base}/products?q={q}&offset=0&limit=60")
            if data is None:
                continue
            products = walk_collect(
                data, lambda d: "productId" in d and "name" in d)
            for p in products:
                pid = p.get("productId", "")
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                url = f"https://www.uniqlo.com/us/en/products/{pid}"
                comp = ""
                if detail_used < self.detail_cap and not self.blocked:
                    comp = self._composition(pid)
                    detail_used += 1
                price = walk_first_key(p.get("prices", {}), "value")
                yield self._item(p.get("name", ""), url, category="new",
                                 composition_raw=comp,
                                 price=price if isinstance(price, (int, float)) else None,
                                 currency="USD")
                n += 1
                if limit and n >= limit:
                    return
        if not seen:
            lt.log_source_event(self.retailer, self.name, "schema_drift",
                                "no products from any query")


class AsosSource(CatalogSource):
    """ASOS product search API; composition from catalogue v4 aboutMe text."""

    name = "asos_live"
    retailer = "asos"
    ticker = "ASC.L"
    listing = ("https://www.asos.com/api/product/search/v2/categories/27108"
               "?store=US&offset=0&limit=72&country=US&currency=USD&lang=en-US")

    def _composition(self, product_id) -> str:
        data = self._get(
            f"https://www.asos.com/api/product/catalogue/v4/products/{product_id}?store=US")
        if data is None:
            return ""
        for key in ("aboutMe", "description", "info"):
            val = walk_first_key(data, key)
            if isinstance(val, str) and "%" in val:
                return re.sub(r"<[^>]+>", " ", val)
        return ""

    def iter_items(self, limit: int = 0):
        data = self._get(self.listing)
        if data is None:
            return
        products = data.get("products") if isinstance(data, dict) else None
        if not products:
            lt.log_source_event(self.retailer, self.name, "schema_drift",
                                "no products in listing response")
            return
        n = detail_used = 0
        for p in products:
            if not isinstance(p, dict) or "id" not in p:
                continue
            url = "https://www.asos.com/" + str(p.get("url", "")).lstrip("/")
            comp = ""
            if detail_used < self.detail_cap and not self.blocked:
                comp = self._composition(p["id"])
                detail_used += 1
            price = walk_first_key(p.get("price", {}), "value")
            yield self._item(p.get("name", ""), url, category="new-in",
                             composition_raw=comp,
                             price=price if isinstance(price, (int, float)) else None,
                             currency="USD")
            n += 1
            if limit and n >= limit:
                return


class DatasetSource(CatalogSource):
    """Fallback: local CSV dumps (Kaggle/Apify/exports) + mapping JSON."""

    name = "dataset"

    def __init__(self, session=None, detail_cap: int = 0,
                 retailer_filter: str = ""):
        super().__init__(session or requests.Session(), detail_cap)
        self.retailer_filter = retailer_filter
        self._tickers = {r["key"]: (r.get("ticker") or "")
                         for r in lt.load_universe()["tier2_retailers"]}

    def iter_items(self, limit: int = 0):
        n = 0
        for csv_path in sorted(DATASET_DIR.glob("*.csv")):
            mapping_path = csv_path.parent / (csv_path.stem + ".mapping.json")
            if not mapping_path.exists():
                log.warning("dataset %s has no mapping.json — skipped", csv_path.name)
                continue
            try:
                mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
                retailer = mapping["retailer"]
                cols = mapping["columns"]
                df = pd.read_csv(csv_path)
            except Exception as e:
                lt.log_source_event("dataset", self.name, "schema_drift",
                                    f"{csv_path.name}: {e}")
                continue
            if self.retailer_filter and retailer != self.retailer_filter:
                continue
            src_name = f"dataset:{csv_path.stem}"
            for _, row in df.iterrows():
                def col(field, default=""):
                    c = cols.get(field)
                    if not c or c not in row.index or pd.isna(row[c]):
                        return default
                    return row[c]
                name = str(col("product_name"))
                url = str(col("url")) or f"{csv_path.stem}#{n}"
                if not name:
                    continue
                item = {
                    "item_id": lt.stable_id(retailer, url),
                    "retailer": retailer,
                    "ticker": self._tickers.get(retailer, ""),
                    "product_name": name,
                    "category": str(col("category")).lower(),
                    "url": url,
                    "first_seen": str(col("date")) or date.today().isoformat(),
                    "composition_raw": str(col("composition_raw")),
                    "price": col("price", ""),
                    "currency": str(col("currency")),
                    "source": src_name,
                }
                yield item
                n += 1
                if limit and n >= limit:
                    return


LIVE_ADAPTERS = {
    "zara": ZaraSource,
    "hm": HMSource,
    "uniqlo": UniqloSource,
    "asos": AsosSource,
}


def build_tag_rows(items: pd.DataFrame) -> pd.DataFrame:
    """Parse composition_raw -> long tag rows, applying the denim rule."""
    rows = []
    for _, it in items.iterrows():
        comp = it.get("composition_raw", "")
        if not isinstance(comp, str) or not comp.strip():
            continue
        shares = lt.parse_composition(comp)
        if not shares:
            continue
        text = f"{it.get('category', '')} {it.get('product_name', '')}"
        if DENIM_RE.search(text) and "cotton" in shares:
            shares["denim"] = shares.get("denim", 0.0) + shares.pop("cotton")
        rows.extend({"item_id": it["item_id"], "material": m, "share": s}
                    for m, s in shares.items())
    return pd.DataFrame(rows, columns=["item_id", "material", "share"])


def persist(items: list[dict]) -> tuple[int, int]:
    """Upsert items (preserving first_seen) and replace their tag rows."""
    if not items:
        return 0, 0
    df = pd.DataFrame(items)
    # variants of one item_id: the composition-bearing row must win the dedup
    df["_has_comp"] = (df["composition_raw"].fillna("").astype(str)
                       .str.strip().ne(""))
    df = (df.sort_values("_has_comp", kind="stable")
            .drop_duplicates(subset=["item_id"], keep="last")
            .drop(columns="_has_comp"))
    old = lt.read_csv_or_empty(ITEMS_CSV)
    if not old.empty:
        old_fs = dict(zip(old["item_id"], old["first_seen"]))
        df["first_seen"] = [old_fs.get(i, f) for i, f
                            in zip(df["item_id"], df["first_seen"])]
        # an empty re-scrape must not clobber a previously captured composition
        old_comp = dict(zip(old["item_id"], old["composition_raw"].fillna("")))
        df["composition_raw"] = [
            c if str(c).strip() else old_comp.get(i, "")
            for i, c in zip(df["item_id"], df["composition_raw"])]
    n_items = lt.upsert_csv(df, ITEMS_CSV, keys=["item_id"],
                            sort_by=["retailer", "first_seen"])

    tags_new = build_tag_rows(df)
    old_tags = lt.read_csv_or_empty(TAGS_CSV, ["item_id", "material", "share"])
    touched = set(df["item_id"])
    kept = old_tags[~old_tags["item_id"].isin(touched)] if not old_tags.empty else old_tags
    merged = pd.concat([kept, tags_new], ignore_index=True)
    tmp = TAGS_CSV.with_suffix(".tmp")
    merged.to_csv(tmp, index=False)
    tmp.replace(TAGS_CSV)
    return n_items, len(tags_new)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retailers", default="",
                    help="comma list of universe tier2 keys (default: scrapeable)")
    ap.add_argument("--source", choices=["auto", "live", "dataset"], default="auto")
    ap.add_argument("--limit", type=int, default=0, help="max items per retailer")
    ap.add_argument("--detail-cap", type=int, default=150,
                    help="max composition detail fetches per retailer per run")
    args = ap.parse_args()

    lt.ensure_dirs()
    uni = lt.load_universe()["tier2_retailers"]
    if args.retailers:
        keys = [k.strip() for k in args.retailers.split(",") if k.strip()]
    else:
        keys = [r["key"] for r in uni
                if r.get("scrapeable") and r["key"] in LIVE_ADAPTERS]

    progress = lt.load_progress(PROGRESS)
    if cf_requests is not None:
        # browser TLS impersonation — retail CDNs (Akamai etc.) reset plain
        # python-requests connections on product-detail endpoints
        session = cf_requests.Session(impersonate="chrome")
        log.info("live adapters using curl_cffi chrome impersonation")
    else:
        session = requests.Session()
    all_items: list[dict] = []

    for key in keys:
        collected: list[dict] = []
        if args.source in ("auto", "live") and key in LIVE_ADAPTERS:
            adapter = LIVE_ADAPTERS[key](session, detail_cap=args.detail_cap)
            log.info("[%s] live scrape via %s", key, adapter.name)
            try:
                collected = list(adapter.iter_items(limit=args.limit))
            except Exception as e:
                lt.log_source_event(key, adapter.name, "adapter_error", str(e))
                log.warning("[%s] adapter crashed cleanly-ish: %s", key, e)
        if not collected and args.source in ("auto", "dataset"):
            if args.source == "auto":
                log.info("[%s] live yielded 0 — falling back to datasets", key)
                lt.log_source_event(key, "dataset", "fallback_engaged",
                                    "live returned no items")
            ds = DatasetSource(retailer_filter=key)
            collected = list(ds.iter_items(limit=args.limit))
        with_comp = sum(1 for i in collected if i["composition_raw"].strip())
        log.info("[%s] %d items (%d with composition)", key, len(collected), with_comp)
        progress[key] = {"last_run": date.today().isoformat(),
                         "items": len(collected), "with_composition": with_comp}
        all_items.extend(collected)

    n_items, n_tags = persist(all_items)
    lt.save_progress(progress, PROGRESS)
    log.info("downstream_items.csv now %d rows; +%d tag rows this run",
             n_items, n_tags)
    return 0


if __name__ == "__main__":
    sys.exit(main())
