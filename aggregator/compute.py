"""
读 observations.jsonl + products.json + rate.json
→ 算每个款的：最低价/中位价/24h 观察数/是否命中目标价/各平台来源分布
→ 写到 aggregates.json，给前端读。

幂等。每次 cron 重算，不依赖前次结果。
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def to_cny(amount: float, currency: str, jpy_to_cny: float) -> float | None:
    if currency == "CNY":
        return amount
    if currency == "JPY":
        return amount * jpy_to_cny
    return None  # 暂不处理 USD 等


def main():
    products = json.loads((DATA / "products.json").read_text())
    obs = load_jsonl(DATA / "observations.jsonl")
    rate_path = DATA / "rate.json"
    jpy_to_cny = 0.0471  # fallback
    if rate_path.exists():
        jpy_to_cny = json.loads(rate_path.read_text())["jpy_to_cny"]

    cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)

    out: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "jpy_to_cny": jpy_to_cny,
        "products": {},
    }

    for pid, p in products.items():
        if pid.startswith("_"):
            continue  # _meta 等元数据 key 跳过
        own = [
            o for o in obs
            if o.get("product_id") == pid and o.get("price") and o.get("currency")
        ]
        cny_prices = []
        for o in own:
            cny = to_cny(o["price"], o["currency"], jpy_to_cny)
            if cny is not None:
                cny_prices.append(cny)

        try:
            recent_24h = sum(
                1 for o in own
                if datetime.fromisoformat(o["source"]["captured_at"]) >= cutoff_24h
            )
        except Exception:
            recent_24h = 0

        target = p.get("target_price_cny")
        lowest = min(cny_prices) if cny_prices else None
        out["products"][pid] = {
            "name": p.get("name_cn") or pid,
            "lowest_cny": round(lowest) if lowest else None,
            "median_cny": round(median(cny_prices)) if cny_prices else None,
            "official_cny": p.get("official_price_cn"),
            "diff_vs_official": (
                round(lowest - p["official_price_cn"])
                if lowest and p.get("official_price_cn") else None
            ),
            "target_hit": bool(target and lowest and lowest <= target),
            "observations_24h": recent_24h,
            "source_breakdown": _source_breakdown(own),
        }

    (DATA / "aggregates.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"[aggregate] wrote {len(out['products'])} products")


def _source_breakdown(records: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in records:
        plat = r.get("source", {}).get("platform", "unknown")
        counts[plat] = counts.get(plat, 0) + 1
    return counts


if __name__ == "__main__":
    main()
