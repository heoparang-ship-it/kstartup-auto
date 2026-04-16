#!/usr/bin/env python3
"""
K-Startup ê³µê³  í¬ë¡¤ë¬ v5 â detail-page og:title íë¡ë¹ ë°©ì
- K-Startupì JS SPA + ìí°ë´ ë³´í¸ â ë¦¬ì¤í¸ íì´ì§ í¬ë¡¤ ë¶ê°
- ê°ë³ ìì¸ íì´ì§(pbancSn)ì og:titleì ì ì ìë (v4ìì ê²ì¦ë¨)
- pbancSn ìíì íë¡ë¹ì¼ë¡ ì í¨ ê³µê³  íì
- ê¸°ì¡´ recommendations.jsonì pbancSn ë²ì + ì ë°© íì
"""
import json
import subprocess
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime("%Y-%m-%d")

BASE = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"
# ì ë°© íì ë²ì: ê¸°ì¡´ max SN ì´íë¡ ì´ ë§í¼ ë ì¤ìº
FORWARD_PROBE = 500
# íë°© íì ë²ì: ê¸°ì¡´ min SN ì´ì ì¼ë¡ ì´ ë§í¼ ë ì¤ìº
BACKWARD_PROBE = 200
# ë³ë ¬ ìì»¤ ì (rate limit ê³ ë ¤)
MAX_WORKERS = 10
# curl íììì
CURL_TIMEOUT = 15


def fetch_detail(sn: int) -> dict | None:
    """ê°ë³ ìì¸ íì´ì§ìì og:title + ë§ê°ì¼ì ì¶ì¶."""
    url = f"{BASE}?schM=ALL&pbancSn={sn}"
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", str(CURL_TIMEOUT),
             "-H", "User-Agent: Mozilla/5.0 (compatible; KStartupBot/1.0)",
             url],
            capture_output=True, text=True, timeout=CURL_TIMEOUT + 5
        )
        html = r.stdout
        if not html:
            return None

        # og:title ì¶ì¶
        m = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', html)
        if not m or not m.group(1).strip():
            return None  # ë¹ og:title = ì¡´ì¬íì§ ìë SN

        title = m.group(1).strip()

        # og:description ì¶ì¶ (ìì¼ë©´)
        desc = ""
        dm = re.search(r'<meta\s+property="og:description"\s+content="([^"]*)"', html)
        if dm:
            desc = dm.group(1).strip()

        # ê¸°ê´ëª ì¶ì¶: ì ëª©ìì [ê¸°ê´ëª] í¨í´ ëë og:descriptionìì
        agency = ""
        am = re.search(r'\[([^\]]+)\]', title)
        if am:
            agency = am.group(1).strip()

        # ë§ê°ì¼ì ì¶ì¶ â ì£¼ì: ì¬ì´ëë° íë ì´ì¤íëì êµ¬ë¶ íì
        # og:descriptionìì ë§ê°ì¼ í¨í´ ì°ì  íì
        deadline = ""
        # 1) descriptionìì ë§ê° ë ì§ ì°¾ê¸°
        dl_m = re.search(r'ë§ê°[ì¼ì:\s]*(\d{4}[-./]\d{2}[-./]\d{2})', desc)
        if dl_m:
            deadline = dl_m.group(1).replace('.', '-').replace('/', '-')
        else:
            # 2) HTML ë³¸ë¬¸ìì ì²« ë²ì§¸ ë§ê°ì¼ì (ì¬ì´ëë° ê°ë¥ì± ìì)
            # ì ë¢°ë ë®ì¼ë¯ë¡ ë¹ ê° ì ì§ â ë¶ë¥ì ìí¥ ì ì¤
            pass

        return {
            "pbancSn": str(sn),
            "title": title,
            "agency": agency,
            "deadline": deadline,
            "url": f"{BASE}?schM=ALL&pbancSn={sn}",
            "first_seen": TODAY,
            "last_seen": TODAY
        }
    except Exception:
        return None


def load_existing_sns(path: str) -> set:
    """ê¸°ì¡´ recommendations.jsonìì pbancSn ëª©ë¡ ë¡ë."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        sns = set()
        for item in data.get("items", []):
            sn = item.get("pbancSn", "")
            if sn:
                sns.add(int(sn))
        for item in data.get("reds_today", []):
            sn = item.get("pbancSn", "")
            if sn:
                sns.add(int(sn))
        return sns
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return set()


def main():
    # ê¸°ì¡´ íìì SN ë²ì íì
    existing_sns = load_existing_sns("recommendations.json")

    if existing_sns:
        min_sn = min(existing_sns)
        max_sn = max(existing_sns)
        print(f"ê¸°ì¡´ í: {len(existing_sns)}ê±´, SN ë²ì {min_sn}~{max_sn}", file=sys.stderr)
    else:
        # ì´ê¸° ì¤í: ìµê·¼ ê³µê³  ë²ì ì¶ì 
        # 2026ë 4ì ê¸°ì¤ ëëµ 177000~178000 ë
        min_sn = 176500
        max_sn = 177500
        print(f"ì´ê¸° ì¤í: SN ë²ì {min_sn}~{max_sn} ì¶ì ", file=sys.stderr)

    # íë¡ë¹ ë²ì ê³ì°
    probe_start = max(min_sn - BACKWARD_PROBE, 1)
    probe_end = max_sn + FORWARD_PROBE

    # ì´ë¯¸ ìë ¤ì§ SNì ì¤íµ (ì¬íì¸ ë¶íì â classify.pyê° ê¸°ì¡´ í ê´ë¦¬)
    sns_to_probe = [sn for sn in range(probe_start, probe_end + 1)
                    if sn not in existing_sns]

    print(f"íë¡ë¹ ëì: {len(sns_to_probe)}ê±´ (ë²ì {probe_start}~{probe_end})",
          file=sys.stderr)

    # ë³ë ¬ íë¡ë¹
    found_items = []
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_detail, sn): sn for sn in sns_to_probe}
        for f in as_completed(futures):
            done += 1
            if done % 100 == 0:
                print(f"  ì§í: {done}/{len(sns_to_probe)} ({len(found_items)}ê±´ ë°ê²¬)",
                      file=sys.stderr)
            result = f.result()
            if result:
                found_items.append(result)

    # ê²°ê³¼ ì ì¥
    found_items.sort(key=lambda x: int(x.get("pbancSn", 0)), reverse=True)

    with open("crawl_results.json", "w", encoding="utf-8") as f:
        json.dump(found_items, f, ensure_ascii=False, indent=2)

    print(f"\ní¬ë¡¤ ìë£: {len(found_items)}ê±´ ì ê· ë°ê²¬ "
          f"(íë¡ë¹ {len(sns_to_probe)}ê±´ ì¤)", file=sys.stderr)


if __name__ == "__main__":
    main()
