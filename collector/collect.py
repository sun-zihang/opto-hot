#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opto-hot — 光电行业热点统计（以 AIHOT 为模板）

流程: 多源采集(RSS + 行业站) -> 清洗去重 -> 领域分类 -> 打分 -> 热点聚类
输出: data/items.json, data/hot-topics.json, data/daily.json, data/report.csv, dist/index.html

用法:
    python collector/collect.py                 # 全流程
    python collector/collect.py --limit 30      # 每个源最多取 30 条
    python collector/collect.py --skip-html     # 跳过 HTML 站
"""

import argparse
import csv
import hashlib
import html as htmlmod
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(ROOT, "data")
DIST_DIR = os.path.join(ROOT, "dist")
SOURCES_PATH = os.path.join(HERE, "sources.json")
REPO_URL = "https://github.com/sun-zihang/opto-hot"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 opto-hot/0.1")

TZ_CN = timezone(timedelta(hours=8))
NS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
}

# ---------------- 领域词表 ----------------
DOMAIN_TERMS = [
    "激光", "光模块", "光通信", "光芯片", "光电", "光学", "镜头", "光纤", "光子", "光刻",
    "光刻机", "激光雷达", "光伏", "红外", "探测器", "成像", "显示", "面板", "OLED",
    "Mini LED", "Micro LED", "LED", "投影", "AR", "VR", "XR", "激光器", "晶圆", "掩模",
    "光电子", "传感器", "车载", "自动驾驶", "半导体", "硅光", "CPO", "相干", "WDM",
    "PON", "光网络", "数据中心", "算力", "EUV", "光刻胶", "光栅", "全息", "太赫兹",
    "摄像头", "相机", "镜片", "棱镜", "TOF", "3D传感", "屏幕", "发光", "照明", "背光",
    "驱动", "封装", "基板", "玻璃", "镀膜", "机器视觉", "激光焊接", "激光切割",
    "激光打标", "激光清洗", "医疗激光", "光纤传感", "海缆", "光缆", "硅光芯片",
    "VCSEL", "DFB", "EML", "硅基OLED", "量子点", "MicroOLED", "AMOLED", "光互联",
    "光引擎", "光交换", "OCS", "光计算", "智能驾驶", "智驾",
    "laser", "photonics", "optical", "optics", "fiber", "fibre", "lidar", "led",
    "oled", "display", "infrared", "imaging", "sensor", "semiconductor", "euv",
    "photonic", "quantum", "camera", "microled", "miniled", "vcsel", "holographic",
    "optoelectronic", "lidars", "silicon photonics",
]

STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "for", "on", "with", "and", "or", "from",
    "by", "at", "is", "are", "was", "were", "be", "been", "has", "have", "had",
    "its", "their", "this", "that", "new", "news", "how", "why", "what", "via",
    "over", "under", "into", "about", "after", "before", "between", "per", "as",
    "up", "down", "out", "off", "2026", "2025", "will", "can", "may", "could",
    "would", "should", "not", "no", "yes", "one", "two", "first", "last", "day",
    # 学术/新闻通用词
    "using", "used", "use", "show", "shows", "shown", "report", "reports",
    "review", "reviews", "key", "important", "significant", "advanced",
    "recent", "recently", "second", "third", "order", "room", "time", "times",
    "week", "weeks", "year", "years", "month", "months", "made", "make",
    "making", "build", "built", "creating", "create", "provides", "provide",
    "offer", "offers", "enable", "enables", "enabling", "allow", "allows",
    "allowing", "help", "helps", "improve", "improves", "improved", "enhance",
    "enhances", "enhanced", "achieve", "achieves", "achieved", "explore",
    "explores", "exploring", "investigate", "investigates", "investigating",
    "design", "designs", "designed", "develop", "develops", "developed",
    "development", "applications", "application", "devices", "device",
    "structures", "structure", "properties", "property", "materials",
    "material", "techniques", "technique", "technology", "technologies",
    "through", "control", "generation", "learning", "hybrid", "interaction",
    "networks", "network", "systems", "system", "methods", "method", "based",
    "model", "models", "phase", "between", "toward", "towards", "high", "low",
    "large", "small", "single", "multi", "novel", "demonstrate", "demonstrates",
    "demonstrated", "demonstrating", "study", "studies", "analysis", "approach",
    "framework", "performance", "results", "result", "beyond", "within",
    "without", "along", "across", "among", "around", "behind", "inside",
    "outside", "throughout", "upon", "analysis", "comparative", "comparison",
    "limits", "limit", "based", "using", "toward", "overcoming", "overcome",
    "break", "breaking", "power", "wall", "programmable", "programming",
    "observations", "observation", "newly", "emerging", "towards", "toward",
    "and", "the", "for", "into", "along", "silencing", "pain", "light",
    "artificial", "leaf", "hot", "electron", "based", "using", "through",
}

CATEGORY_RULES = [
    ("激光", ["激光", "laser", "lasers"]),
    ("光通信", ["光通信", "光模块", "光纤", "光缆", "海缆", "光网络", "光芯片", "硅光",
               "CPO", "WDM", "PON", "相干", "800G", "1.6T", "光互联", "光交换", "OCS",
               "光引擎", "fiber", "fibre", "photonics", "optical network",
               "optical communication", "submarine cable", "数据中心", "智算"]),
    ("显示与面板", ["OLED", "Mini LED", "Micro LED", "LED", "显示", "面板", "AMOLED",
                 "背光", "量子点", "屏幕", "display", "microled", "miniled", "AR",
                 "VR", "XR", "眼镜", "头显"]),
    ("光电芯片与半导体", ["半导体", "晶圆", "EUV", "光刻", "光刻机", "掩模", "封装",
                       "VCSEL", "DFB", "EML", "semiconductor", "euv", "wafer",
                       "lithograph", "chip", "芯片"]),
    ("光学元件与成像", ["光学", "镜头", "镜片", "棱镜", "相机", "成像", "TOF", "3D传感",
                     "红外", "探测器", "摄像头", "optics", "lens", "imaging", "camera",
                     "infrared", "全息", "光波导", "光场", "显微"]),
    ("光传感与激光雷达", ["激光雷达", "光纤传感", "传感器", "lidar", "sensor", "雷达"]),
    ("光伏与新能源", ["光伏", "太阳能", "光电转换", "photovoltaic", "solar"]),
    ("科研进展", ["arxiv", "nature photonics", "量子", "太赫兹", "quantum", "论文", "研究"]),
    ("产业与资本", ["IPO", "上市", "并购", "收购", "融资", "投资", "营收", "净利润", "财报",
                  "半年报", "产能", "扩产", "中标", "订单", "产业", "政策", "标准", "展会",
                  "博览会", "峰会", "论坛", "投产", "下线", "揭牌", "亮相", "发布", "推出",
                  "合作", "签约", "预增", "定增", "获批", "大单", "调研", "基地", "战略",
                  "人工智能大会", "WAIC"]),
    ("通信与算力", ["通信", "运营商", "5G", "6G", "算力", "人工智能", "大模型", "昇腾",
                  "云网", "数字化", "智能化", "AI", "电信", "移动", "联通", "网络",
                  "宽带", "数据"]),
]
RESEARCH_SOURCES = {"arXiv 光学与光子学 (physics.optics)", "Nature Photonics", "Phys.org 物理新闻"}
CATEGORY_ORDER = [c for c, _ in CATEGORY_RULES] + ["其他"]


def log(msg):
    print(msg, flush=True)


def now_utc():
    return datetime.now(timezone.utc)


def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/xml;q=0.9, text/html;q=0.8, */*;q=0.7",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "")


def detect_charset(data, declared=None):
    if declared:
        cs = declared.lower().split(";")[0].strip()
        if cs in ("gb2312", "gbk", "gb18030", "gb1323", "gb-2312"):
            return "gbk"
        return cs or "utf-8"
    head = data[:4096].decode("latin1", "ignore")
    m = re.search(r'charset=["\']?\s*([\w-]+)', head, re.I)
    if m:
        cs = m.group(1).lower()
        if cs in ("gb2312", "gbk", "gb18030", "gb1323", "gb-2312"):
            return "gbk"
        return cs
    return "utf-8"


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    fmts = (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    )
    for fmt in fmts:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def parse_rss(data):
    root = None
    err = None
    try:
        root = ET.fromstring(data)
    except Exception as e:
        err = e
    if root is None:
        text = None
        for enc in ("gbk", "gb18030", "utf-8"):
            try:
                text = data.decode(enc)
                break
            except Exception:
                continue
        if text is None:
            raise err if err else ValueError("cannot decode feed")
        text = re.sub(r"<\?xml[^>]*\?>", "", text, count=1)
        root = ET.fromstring(text)

    RSS1 = "{http://purl.org/rss/1.0/}"
    tag = (root.tag or "").rsplit("}", 1)[-1]
    entries = []

    if tag == "rss":  # RSS 2.0
        ch = root.find("channel")
        if ch is None:
            return None, entries
        for it in ch.findall("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            desc = it.findtext("description") or it.findtext("content:encoded", namespaces=NS) or ""
            pub = it.findtext("pubDate") or it.findtext("dc:date", namespaces=NS)
            if title or link:
                entries.append({"title": title, "link": link, "desc": desc, "pub": pub})

    elif tag == "RDF":  # RSS 1.0 (RDF)
        for it in root.findall(RSS1 + "item"):
            title = (it.findtext(RSS1 + "title") or "").strip()
            lel = it.find(RSS1 + "link")
            link = (lel.text or "").strip() if lel is not None else ""
            desc = (it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
                    or it.findtext("description") or "")
            pub = it.findtext("dc:date", namespaces=NS) or it.findtext(RSS1 + "date")
            if title or link:
                entries.append({"title": title, "link": link, "desc": desc, "pub": pub})

    elif tag == "feed":  # Atom
        for e in root.findall("atom:entry", NS):
            title = (e.findtext("atom:title", namespaces=NS) or "").strip()
            lel = e.find("atom:link", namespaces=NS)
            link = lel.get("href", "") if lel is not None else ""
            pub = e.findtext("atom:published", namespaces=NS) or e.findtext("atom:updated", namespaces=NS)
            desc = e.findtext("atom:summary", namespaces=NS) or ""
            if title or link:
                entries.append({"title": title, "link": link, "desc": desc, "pub": pub})
    return None, entries


def parse_html_links(data, charset, base, cfg):
    text = data.decode(charset, "replace")
    pattern = cfg.get("anchor_pattern")
    links = []
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, re.S | re.I):
        href = htmlmod.unescape(m.group(1)).strip()
        if href.startswith(("javascript:", "#", "mailto:", "tel:")):
            continue
        if pattern and not re.search(pattern, href):
            continue
        title = re.sub(r"<[^>]+>", "", m.group(2))
        title = htmlmod.unescape(title)
        title = re.sub(r"\s+", " ", title).strip()
        if len(title) < 8:
            continue
        pub = None
        t = title
        if cfg.get("title_date") == "prefix":
            md = re.match(r"^\s*(\d{4}-\d{2}-\d{2})\s*[|\u00b7\-\u2013\u2014]?\s*", title)
            if md:
                pub = md.group(1)
                t = title[md.end():].strip(" |\u00b7-\u2013\u2014\t").strip()
        ud = cfg.get("url_date")
        if ud == "y-m-d":
            mu = re.search(r"(20\d{2})(\d{2})(\d{2})-", href)
            if mu:
                pub = "%s-%s-%s" % (mu.group(1), mu.group(2), mu.group(3))
        elif ud == "y-m":
            mu = re.search(r"/(20\d{2})-(\d{2})/", href)
            if not mu:
                mu = re.search(r"/industry/(20\d{2})(\d{2})/", href)
            if mu:
                pub = "%s-%s" % (mu.group(1), mu.group(2))
        if not t:
            continue
        full = urllib.parse.urljoin(base, href)
        links.append({"title": t, "href": full, "pub": pub})
    seen = set()
    out = []
    for lk in links:
        k = norm_title(lk["title"])
        if k in seen:
            continue
        seen.add(k)
        out.append(lk)
    return out


def norm_title(t):
    t = t.lower()
    t = re.sub(r"[^\w\u4e00-\u9fff]+", "", t)
    return t


def kw_hit(title_lower, term):
    t = term.lower()
    if re.search(r"[a-z0-9]", t):
        return re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", title_lower) is not None
    return t in title_lower


def extract_keywords(title):
    tl = title.lower()
    kws = set()
    for term in DOMAIN_TERMS:
        if kw_hit(tl, term):
            kws.add(term.lower())
    for w in re.findall(r"[a-z][a-z0-9+.\-]{2,}", tl):
        w2 = w.strip("+.-")
        if w2 and w2 not in STOPWORDS and len(w2) >= 4 and w2 not in kws:
            kws.add(w2)
    return sorted(kws)


def classify(title, source):
    tl = title.lower()
    for cat, kws in CATEGORY_RULES:
        for kw in kws:
            if kw_hit(tl, kw):
                return cat
    if source in RESEARCH_SOURCES:
        return "科研进展"
    return "其他"


def make_id(title, url):
    return hashlib.sha1((norm_title(title) + "|" + url).encode("utf-8")).hexdigest()[:12]


def age_days(dt):
    return max(0.0, (now_utc() - dt).total_seconds() / 86400.0)


def eff_dt(it):
    """优先使用原文发布时间，缺失时回退到收录时间（AIHOT 时间轴语义）"""
    p = it.get("published_at")
    if p and len(p) >= 10:
        dt = parse_date(p)
        if dt:
            return dt
    return datetime.fromisoformat(it["discovered_at"])


# ---------------- 采集 ----------------
def fetch_rss(cfg, limit):
    data, ctype = http_get(cfg["url"])
    _, entries = parse_rss(data)
    kws = [k.lower() for k in cfg.get("filter_keywords", [])]
    items = []
    for e in entries:
        title = (e["title"] or e["link"] or "").strip()
        if not title:
            continue
        if kws and not any(k in title.lower() for k in kws):
            continue
        pub = parse_date(e["pub"])
        desc_plain = re.sub(r"<[^>]+>", " ", e["desc"] or "")
        summary = re.sub(r"\s+", " ", htmlmod.unescape(desc_plain)).strip()[:500]
        items.append({
            "title": htmlmod.unescape(title).strip(),
            "url": (e["link"] or "").strip(),
            "published_at": pub.isoformat() if pub else None,
            "summary": summary or None,
        })
        if len(items) >= limit:
            break
    return items


def fetch_html(cfg, limit):
    data, ctype = http_get(cfg["url"])
    charset = cfg.get("charset") or detect_charset(data, ctype)
    links = parse_html_links(data, charset, cfg["url"], cfg)
    items = []
    for lk in links:
        items.append({
            "title": lk["title"],
            "url": lk["href"],
            "published_at": lk["pub"],
            "summary": None,
        })
        if len(items) >= limit:
            break
    return items


def collect(sources, limit, skip_rss=False, skip_html=False):
    raw = []
    for stype in ("rss", "html"):
        if stype == "rss" and skip_rss:
            continue
        if stype == "html" and skip_html:
            continue
        for cfg in sources.get(stype, []):
            try:
                got = fetch_rss(cfg, limit) if stype == "rss" else fetch_html(cfg, limit)
                log("[OK] %-4s %s: %d 条" % (stype, cfg["name"], len(got)))
                for g in got:
                    g["source"] = cfg["name"]
                    g["source_type"] = stype
                    g["source_weight"] = cfg.get("weight", 0.8)
                raw.extend(got)
            except Exception as e:
                log("[FAIL] %-4s %s: %s" % (stype, cfg["name"], e))
    return raw


# ---------------- 热点聚类 ----------------
def cluster_topics(items):
    kw_items = {}
    for it in items:
        for kw in it["keywords"]:
            kw_items.setdefault(kw, []).append(it)
    candidates = []
    for kw, its in kw_items.items():
        if len(its) >= 2:
            candidates.append({
                "term": kw,
                "ids": {i["id"] for i in its},
                "sources": {i["source"] for i in its},
            })
    candidates.sort(key=lambda c: (len(c["ids"]), len(c["sources"])), reverse=True)
    topics = []
    for c in candidates:
        merged = False
        for t in topics:
            overlap = len(c["ids"] & t["ids"]) / max(1, len(c["ids"]))
            if overlap >= 0.6:
                t["ids"] |= c["ids"]
                t["terms"].add(c["term"])
                merged = True
                break
        if not merged:
            topics.append({"terms": {c["term"]}, "ids": set(c["ids"])})
    return topics


def compute_scores(items, topics, source_weight):
    item_topic = {}
    for t in topics:
        for iid in t["ids"]:
            item_topic[iid] = max(item_topic.get(iid, 0), len(t["ids"]))
    for it in items:
        sig = item_topic.get(it["id"], 0)
        dt = eff_dt(it)
        rec = max(0.0, 1 - age_days(dt) / 30.0)
        sw = source_weight.get(it["source"], 0.8)
        it["score"] = round(50 * sw + 25 * min(1.0, sig / 10.0) + 25 * rec, 1)
    for t in topics:
        finalize_topic(t, items)


def merge_duplicate_topics(topics, items):
    """合并高度重叠或代表条目相同的主题"""
    changed = True
    while changed:
        changed = False
        for i in range(len(topics)):
            for j in range(i + 1, len(topics)):
                a, b = topics[i], topics[j]
                inter = len(a["ids"] & b["ids"])
                if inter / max(1, min(len(a["ids"]), len(b["ids"]))) >= 0.5:
                    a["ids"] |= b["ids"]
                    a["terms"] |= b["terms"]
                    topics.pop(j)
                    changed = True
                    break
            if changed:
                break
    rep = {}
    for t in topics:
        its = [it for it in items if it["id"] in t["ids"]]
        rep[id(t)] = max(its, key=lambda i: i["discovered_at"]) if its else None
    groups = {}
    order = []
    for t in topics:
        b = rep[id(t)]
        key = b["id"] if b else ("none:" + str(id(t)))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(t)
    out = []
    for key in order:
        gs = groups[key]
        if len(gs) == 1:
            out.append(gs[0])
        else:
            base = gs[0]
            for g in gs[1:]:
                base["ids"] |= g["ids"]
                base["terms"] |= g["terms"]
            out.append(base)
    return out

def finalize_topic(t, items):
    its = [it for it in items if it["id"] in t["ids"]]
    srcs = {i["source"] for i in its}
    recent = sum(1 for i in its if age_days(eff_dt(i)) <= 2)
    t["source_count"] = len(srcs)
    t["signal_count"] = len(its)
    t["sources"] = sorted(srcs)
    t["score"] = round(
        100 * (0.45 * min(1.0, len(srcs) / 6.0)
               + 0.35 * min(1.0, len(its) / 10.0)
               + 0.20 * min(1.0, recent / max(1, len(its)))), 1)
    t["latest_at"] = max(i["discovered_at"] for i in its)
    best = max(its, key=lambda i: i["score"])
    t["title"] = best["title"]
    t["terms"] = sorted(t["terms"])
    t["id"] = make_id(t["title"], "|".join(sorted(i["id"] for i in its)))
    t["links"] = [{
        "title": i["title"], "url": i["url"], "source": i["source"],
        "score": i["score"], "published_at": i["published_at"],
    } for i in sorted(its, key=lambda x: x["score"], reverse=True)[:5]]


def dedupe_topic_titles(topics, items):
    """合并标题相同的主题（例如同一事件的多个角度）"""
    by_title = {}
    order = []
    for t in topics:
        key = t["title"]
        if key not in by_title:
            by_title[key] = []
            order.append(key)
        by_title[key].append(t)
    out = []
    for key in order:
        gs = by_title[key]
        if len(gs) == 1:
            out.append(gs[0])
            continue
        base = gs[0]
        ids = set()
        terms = set()
        for g in gs:
            ids |= g["ids"]
            terms |= set(g["terms"])
        base["ids"] = ids
        base["terms"] = terms
        finalize_topic(base, items)
        out.append(base)
    return out


# ---------------- 统计 ----------------
def build_daily(items, topics, generated):
    def in_window(it, days):
        return age_days(eff_dt(it)) <= days
    n24 = sum(1 for it in items if in_window(it, 1))
    n7 = sum(1 for it in items if in_window(it, 7))
    cats = []
    for cat in CATEGORY_ORDER:
        its = [it for it in items if it["category"] == cat]
        if its:
            cats.append({
                "category": cat,
                "total": len(its),
                "last24h": sum(1 for i in its if in_window(i, 1)),
                "last7d": sum(1 for i in its if in_window(i, 7)),
            })
    days = []
    today = (generated + timedelta(hours=8)).date()
    for k in range(13, -1, -1):
        d = today - timedelta(days=k)
        c = sum(1 for it in items
                if (eff_dt(it) + timedelta(hours=8)).date() == d)
        days.append({"date": d.isoformat(), "count": c})
    src_map = {}
    for it in items:
        s = src_map.setdefault(it["source"], {
            "source": it["source"], "count": 0, "latestAt": it["discovered_at"]})
        s["count"] += 1
        if it["discovered_at"] > s["latestAt"]:
            s["latestAt"] = it["discovered_at"]
    return {
        "generatedAt": generated.isoformat(),
        "total": len(items),
        "last24h": n24,
        "last7d": n7,
        "topicCount": len(topics),
        "byCategory": cats,
        "byDay": days,
        "bySource": sorted(src_map.values(), key=lambda s: -s["count"]),
    }


# ---------------- 日报归档 ----------------
WEEKDAYS_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
MONTHS_CN = "一二三四五六七八九十"


def cn_date(dstr):
    """2026-08-03 -> 2026年8月3日"""
    try:
        y, m, d = dstr.split("-")
        return "%s年%d月%d日" % (y, int(m), int(d))
    except Exception:
        return dstr


def role_tag(source):
    if any(k in source for k in ("arXiv", "Nature Photonics", "Phys.org")):
        return "科研"
    if any(k in source for k in ("OFweek", "LEDinside", "CIOE", "COEMA", "C114")):
        return "行业媒体"
    return "媒体"


def build_dailies(items):
    """按天生成光电日报（AIHOT 日报机制）"""
    by_date = {}
    for it in items:
        d = (eff_dt(it) + timedelta(hours=8)).date().isoformat()
        by_date.setdefault(d, []).append(it)
    out = {}
    for d, its in sorted(by_date.items()):
        its.sort(key=lambda i: i["score"], reverse=True)
        sections = []
        for cat in CATEGORY_ORDER:
            arts = [i for i in its if i["category"] == cat][:8]
            if arts:
                sections.append({
                    "category": cat,
                    "articles": [{
                        "title": a["title"],
                        "url": a["url"],
                        "source": a["source"],
                        "summary": (a.get("summary") or "")[:240],
                        "score": a["score"],
                        "role": role_tag(a["source"]),
                        "published_at": a.get("published_at"),
                    } for a in arts],
                })
        if not sections:
            continue
        try:
            wd = WEEKDAYS_CN[datetime.strptime(d, "%Y-%m-%d").weekday()]
        except Exception:
            wd = ""
        total_chars = sum(len(s["articles"][0]["summary"]) for s in sections if s["articles"])
        out[d] = {
            "date": d,
            "weekday": wd,
            "label": cn_date(d),
            "sections": sections,
            "tocCount": sum(len(s["articles"]) for s in sections),
            "readMinutes": max(1, round(total_chars / 300)),
        }
    return out


# ---------------- HTML 报告（AIHOT 风格） ----------------
CAT_CLS = {
    "激光": "laser", "光通信": "fiber", "显示与面板": "display", "光电芯片与半导体": "chip",
    "光学元件与成像": "optics", "光传感与激光雷达": "sensing", "光伏与新能源": "pv",
    "科研进展": "research", "产业与资本": "capital", "通信与算力": "telecom", "其他": "other",
}

APP_CSS = r"""
:root { --bg:#f4f5f6; --card:#fff; --border:#e2e4e7; --text:#1c2733; --muted:#5c6672;
        --accent:#135e6b; --accent-soft:rgba(19,94,107,.08); --radius:12px;
        --gold:#96702e; --gold-bg:rgba(184,135,58,.12); --score-hi:#135e6b; --score-mid:#b7791f; --score-low:#9aa3af; }
* { margin:0; padding:0; box-sizing:border-box; }
html { -webkit-text-size-adjust:100%; }
body { background:var(--bg); color:var(--text); font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","HarmonyOS Sans SC","Microsoft YaHei",sans-serif; line-height:1.6; }
a { color:inherit; text-decoration:none; }
a:hover { opacity:.85; }
.mono { font-variant-numeric:tabular-nums; font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
/* top bar */
.m-topbar { position:sticky; top:0; z-index:50; background:rgba(255,255,255,.9); backdrop-filter:blur(8px); border-bottom:1px solid var(--border); }
.topbar-inner { max-width:1180px; margin:0 auto; padding:10px 18px; display:flex; align-items:center; gap:16px; }
.brand { font-weight:700; font-size:16px; color:var(--accent); display:flex; align-items:center; gap:8px; white-space:nowrap; }
.brand .logo { width:24px; height:24px; border-radius:7px; background:linear-gradient(135deg,#135e6b,#1d8a9c); color:#fff; display:flex; align-items:center; justify-content:center; font-size:13px; }
.searchbox { flex:1; max-width:420px; display:flex; align-items:center; gap:8px; background:var(--bg); border:1px solid var(--border); border-radius:10px; padding:6px 12px; }
.searchbox input { flex:1; border:none; background:none; outline:none; font-size:14px; color:var(--text); }
.searchbox .kbd { font-size:11px; color:var(--muted); border:1px solid var(--border); border-radius:5px; padding:0 5px; }
.topbar-meta { margin-left:auto; font-size:12px; color:var(--muted); white-space:nowrap; }
/* layout */
.app-layout { max-width:1180px; margin:0 auto; display:grid; grid-template-columns:176px 1fr; gap:22px; padding:18px; }
.side-nav { position:sticky; top:66px; align-self:start; display:flex; flex-direction:column; gap:2px; }
.side-group { font-size:11px; color:var(--muted); padding:8px 10px 4px; letter-spacing:.5px; }
.side-link { display:flex; align-items:center; gap:9px; padding:8px 10px; border-radius:9px; color:var(--muted); font-size:14px; }
.side-link:hover { background:var(--accent-soft); color:var(--accent); }
.side-link-active { background:var(--accent-soft); color:var(--accent); font-weight:600; }
.side-link .si { width:16px; height:16px; display:inline-flex; align-items:center; justify-content:center; opacity:.9; }
.app-main { min-width:0; }
.view { display:none; }
.view-active { display:block; }
/* cards */
.card { background:var(--card); border:1px solid var(--border); border-radius:var(--radius); }
.pad { padding:16px 18px; }
.page-head { display:flex; align-items:baseline; gap:12px; padding:14px 18px; margin-bottom:14px; }
.page-head h1 { font-size:20px; font-weight:700; }
.page-head .sub { font-size:13px; color:var(--muted); }
/* hot card on feed */
.hotcard { margin-bottom:16px; }
.hotcard-head { display:flex; align-items:center; justify-content:space-between; padding:12px 16px 4px; }
.hotcard-head .t { font-weight:600; font-size:15px; display:flex; align-items:center; gap:8px; }
.hotcard-head .more { font-size:12px; color:var(--muted); }
.hot-topics-list { list-style:none; }
.hot-topics-row { display:flex; align-items:center; gap:12px; padding:9px 16px; border-top:1px solid var(--border); }
.hot-topics-row:first-of-type { border-top:none; }
.hot-topics-rank { min-width:22px; height:22px; border-radius:7px; background:var(--bg); color:var(--muted); font-weight:700; font-size:13px; display:flex; align-items:center; justify-content:center; }
.hot-topics-rank-1, .hot-topics-rank-2, .hot-topics-rank-3 { background:var(--accent); color:#fff; }
.hot-topics-link { flex:1; min-width:0; font-size:14.5px; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
.hot-topics-meta { font-size:12px; color:var(--muted); white-space:nowrap; }
.hot-topics-meta b { color:var(--accent); font-weight:600; }
/* feed timeline */
.timeline { display:flex; flex-direction:column; gap:16px; }
.timeline-day-head { display:flex; align-items:baseline; gap:10px; padding:2px 2px 8px; }
.timeline-day-head h2 { font-size:16px; font-weight:700; }
.timeline-day-head .week { font-size:13px; color:var(--muted); }
.timeline-day-head .cnt { margin-left:auto; font-size:12px; color:var(--muted); }
.timeline-card { background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:13px 16px; }
.timeline-card-head { display:flex; align-items:center; gap:10px; margin-bottom:8px; }
.timeline-head-left { display:flex; align-items:center; gap:7px; min-width:0; flex:1; }
.timeline-source { font-size:12.5px; font-weight:600; color:var(--text); }
.timeline-time { font-size:12px; color:var(--muted); }
.timeline-head-right { display:flex; align-items:center; gap:8px; }
.badge { font-size:11px; border-radius:6px; padding:1px 7px; white-space:nowrap; }
.b-cat { color:#3c5a9e; background:#eef2fb; }
.b-selected { color:var(--gold); background:var(--gold-bg); }
.timeline-score { font-size:13px; font-weight:600; }
.score-hi { color:var(--score-hi); } .score-mid { color:var(--score-mid); } .score-low { color:var(--score-low); }
.timeline-body { font-size:14px; color:var(--text); }
.timeline-body a { display:block; }
.timeline-summary { margin-top:4px; font-size:13px; color:var(--muted); }
.timeline-orig { margin-top:8px; display:inline-flex; align-items:center; gap:5px; font-size:12px; color:var(--muted); }
/* hot page */
.hot-rank-list { list-style:none; }
.hot-rank-row { display:flex; align-items:center; gap:14px; padding:13px 16px; border-top:1px solid var(--border); }
.hot-rank-row:first-child { border-top:none; }
.hot-rank-no { font-family:ui-monospace,Menlo,monospace; font-size:17px; font-weight:700; color:var(--muted); width:30px; text-align:center; }
.hot-rank-row:nth-child(1) .hot-rank-no, .hot-rank-row:nth-child(2) .hot-rank-no, .hot-rank-row:nth-child(3) .hot-rank-no { color:var(--accent); }
.hot-rank-main { flex:1; min-width:0; }
.hot-rank-title { font-size:15px; font-weight:600; }
.hot-rank-meta { font-size:12px; color:var(--muted); margin-top:3px; display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.hot-rank-heat { font-size:14px; font-weight:700; color:var(--accent); white-space:nowrap; }
.flag { font-size:11px; border-radius:6px; padding:1px 7px; font-weight:600; }
.flag-hot { color:#b3261e; background:rgba(179,38,30,.1); }
.flag-warm { color:#b7791f; background:rgba(183,121,31,.12); }
.flag-watch { color:var(--muted); background:var(--bg); }
.src-chips { display:flex; flex-wrap:wrap; gap:5px; margin-top:7px; }
.chip { font-size:11px; background:var(--bg); color:var(--muted); border-radius:20px; padding:1px 9px; }
/* daily */
.daily-shell { display:grid; grid-template-columns:190px 1fr; gap:16px; align-items:start; }
.daily-side { position:sticky; top:66px; }
.daily-side-card { background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:12px; }
.daily-side-card h3 { font-size:12px; color:var(--muted); margin-bottom:8px; }
.daily-day { display:flex; align-items:center; justify-content:space-between; font-size:12.5px; padding:5px 8px; border-radius:8px; cursor:pointer; }
.daily-day:hover { background:var(--accent-soft); }
.daily-day-active { background:var(--accent-soft); color:var(--accent); font-weight:600; }
.m-daily-body { background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:20px 22px; }
.m-daily-eyebrow { font-size:11px; letter-spacing:3px; color:var(--muted); }
.m-daily-issue-date { font-size:20px; font-weight:700; margin:2px 0 14px; }
.reader-toc { border:1px solid var(--border); border-radius:var(--radius); padding:12px 14px; margin-bottom:16px; background:var(--bg); }
.reader-toc-head { display:flex; align-items:baseline; gap:10px; margin-bottom:8px; }
.reader-toc-heading { font-weight:600; font-size:14px; }
.reader-toc-meta { font-size:12px; color:var(--muted); }
.reader-toc-list { list-style:none; display:flex; flex-direction:column; gap:4px; }
.reader-toc-row { display:flex; gap:10px; font-size:13px; padding:3px 2px; }
.reader-toc-no { font-family:ui-monospace,Menlo,monospace; color:var(--accent); }
.reader-toc-label { color:var(--muted); }
.daily-sec { margin-bottom:18px; }
.daily-sec h3 { font-size:14px; color:var(--accent); border-left:3px solid var(--accent); padding-left:9px; margin-bottom:9px; }
.daily-article { padding:10px 0; border-top:1px solid var(--border); }
.daily-article:first-child { border-top:none; }
.daily-article-title { font-size:15px; font-weight:600; }
.daily-article-source { font-size:12px; color:var(--muted); margin:3px 0 5px; display:flex; gap:8px; align-items:center; }
.role-tag { font-size:11px; border-radius:6px; padding:0 6px; color:#3c5a9e; background:#eef2fb; }
.daily-article-summary { font-size:13px; color:var(--muted); }
/* topics */
.topic-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(210px,1fr)); gap:12px; }
.topic-card { background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:14px 16px; cursor:pointer; }
.topic-card:hover { border-color:var(--accent); }
.topic-card .t-name { font-weight:600; font-size:14.5px; display:flex; align-items:center; justify-content:space-between; }
.topic-card .t-nums { font-size:12px; color:var(--muted); margin-top:6px; display:flex; gap:12px; }
.topic-card .t-nums b { color:var(--accent); }
/* data */
.stats { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:16px; }
.stat { background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:14px 16px; }
.stat .num { font-size:26px; font-weight:700; color:var(--accent); }
.stat .lbl { font-size:12px; color:var(--muted); }
table { width:100%; border-collapse:collapse; font-size:13px; }
th, td { text-align:left; padding:8px 12px; border-bottom:1px solid var(--border); }
th { color:var(--muted); font-weight:600; font-size:12px; }
.day-chart { display:flex; align-items:flex-end; gap:6px; height:110px; padding:8px 4px 0; }
.day-col { flex:1; display:flex; flex-direction:column; align-items:center; justify-content:flex-end; gap:4px; height:100%; }
.day-col .dbar { width:68%; background:linear-gradient(180deg,#2f9db1,var(--accent)); border-radius:5px 5px 0 0; min-height:2px; }
.day-col .dl { font-size:10px; color:var(--muted); }
.dl-row { display:flex; gap:10px; margin-top:10px; flex-wrap:wrap; }
.dl-btn { display:inline-block; border:1px solid var(--border); border-radius:9px; padding:6px 12px; font-size:13px; background:var(--card); color:var(--accent); }
.empty { color:var(--muted); padding:26px; text-align:center; font-size:13px; }
footer { max-width:1180px; margin:0 auto; padding:10px 18px 30px; font-size:12px; color:var(--muted); text-align:center; }
@media (max-width: 900px) {
  .app-layout { grid-template-columns:1fr; }
  .side-nav { position:static; flex-direction:row; overflow-x:auto; padding-bottom:6px; }
  .side-group { display:none; }
  .daily-shell { grid-template-columns:1fr; }
  .stats { grid-template-columns:1fr 1fr; }
}
"""

APP_JS = r"""
const S = __SNAPSHOT__;
const $ = (sel, root=document) => root.querySelector(sel);
const $$ = (sel, root=document) => [...root.querySelectorAll(sel)];
const esc = s => String(s==null?"":s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
const CAT_CLS = S.catCls || {};
function fmtRel(iso){
  if(!iso) return "";
  const t = new Date(iso);
  const d = (Date.now() - t.getTime())/1000;
  if(d < 60) return "刚刚";
  if(d < 3600) return Math.floor(d/60)+" 分钟前";
  if(d < 86400) return Math.floor(d/3600)+" 小时前";
  return Math.floor(d/86400)+" 天前";
}
function effDate(it){
  const p = it.published_at;
  if(p && p.length >= 10) return p.slice(0,10);
  const d = new Date(it.discovered_at);
  const off = d.getTime() + 8*3600*1000;
  return new Date(off).toISOString().slice(0,10);
}
function fmtDay(dstr){
  const [y,m,d] = dstr.split("-").map(Number);
  return y+"年"+m+"月"+d+"日";
}
function wdCN(dstr){
  const dt = new Date(dstr+"T00:00:00+08:00");
  return ["周日","周一","周二","周三","周四","周五","周六"][dt.getDay()];
}
function todayCN(){
  const d = new Date(Date.now()+8*3600*1000);
  return d.toISOString().slice(0,10);
}
function isToday(dstr){ return dstr === todayCN(); }
function scoreCls(s){ return s>=75?"score-hi":(s>=50?"score-mid":"score-low"); }
function pubLabel(it){
  if(it.published_at){
    const p = it.published_at;
    if(p.length===7) return p+"（月级）发布";
    if(p.length===10) return p+" 发布";
    return p.replace("T"," ").slice(5,16)+" 发布";
  }
  return "收录 "+fmtRel(it.discovered_at);
}
function catBadge(cat){ return '<span class="badge b-cat">'+esc(cat)+'</span>'; }
function selBadge(){ return '<span class="badge b-selected">精选</span>'; }
function scoreEl(it){ return '<span class="timeline-score mono '+scoreCls(it.score)+'" title="推荐分（满分100）">'+Math.round(it.score)+'</span>'; }
function itemCard(it){
  return '<article class="timeline-card"><div class="timeline-card-head">'+
    '<div class="timeline-head-left">'+catBadge(it.category)+'<span class="timeline-source">'+esc(it.source)+'</span>'+
    '<span class="timeline-time">'+esc(pubLabel(it))+'</span>'+(it.selected?selBadge():"")+'</div>'+
    '<div class="timeline-head-right">'+scoreEl(it)+'</div></div>'+
    '<div class="timeline-body"><a href="'+esc(it.url)+'" target="_blank" rel="noopener">'+esc(it.title)+'</a>'+
    (it.summary?'<div class="timeline-summary">'+esc(it.summary)+'</div>':"")+
    '<a class="timeline-orig" href="'+esc(it.url)+'" target="_blank" rel="noopener">↗ 查看原文</a></div></article>';
}
/* views */
const state = { q:"", cat:"全部", sort:"score", dailyDate: todayCN() };
function setView(name){ $$(".view").forEach(v=>v.classList.remove("view-active")); $("#view-"+name).classList.add("view-active"); }
function router(){
  const h = (location.hash||"#/").replace("#","");
  const name = h.split("?")[0] || "/";
  const map = {"/":"feed","/all":"all","/hot":"hot","/daily":"daily","/topics":"topics","/data":"data"};
  const v = map[name] || "feed";
  $$(".side-link").forEach(a=>a.classList.toggle("side-link-active", a.getAttribute("href")===("#"+name)));
  setView(v);
  renderers[v]();
}
function renderFeed(){
  const root = $("#view-feed"); root.innerHTML = "";
  // hot card
  const top = S.topics.slice(0,6);
  let hotHtml = '<div class="card hotcard"><div class="hotcard-head"><span class="t">🔥 光电热点</span><a class="more" href="#/hot">热点榜 →</a></div><ol class="hot-topics-list">'+
    top.map((t,i)=>'<li class="hot-topics-row"><span class="hot-topics-rank hot-topics-rank-'+(i+1)+'">'+(i+1)+'</span><a class="hot-topics-link" href="'+esc(t.links&&t.links[0]?t.links[0].url:"#/hot")+'" target="_blank" rel="noopener">'+esc(t.title)+'</a><span class="hot-topics-meta">'+t.source_count+' 来源 · <b>'+Math.round(t.heat||t.score)+'</b> 热度</span></li>').join("")+
    '</ol></div>';
  // group by day
  const groups = {};
  for(const it of S.items){ const d = effDate(it); (groups[d]=groups[d]||[]).push(it); }
  const days = Object.keys(groups).sort().reverse().slice(0,7);
  let tl = "";
  for(const d of days){
    const its = groups[d].slice().sort((a,b)=>b.score-a.score).slice(0,20);
    const label = isToday(d) ? "今天 "+fmtDay(d) : fmtDay(d);
    tl += '<div class="timeline-day"><div class="timeline-day-head"><h2>'+label+'</h2><span class="week">'+wdCN(d)+'</span><span class="cnt">'+its.length+' 条精选</span></div><div class="timeline">'+its.map(itemCard).join("")+'</div></div>';
  }
  root.innerHTML = hotHtml + tl;
}
function renderAll(){
  const root = $("#view-all");
  let its = S.items.slice();
  if(state.q){ const q = state.q.toLowerCase(); its = its.filter(i=>(i.title+" "+(i.summary||"")+" "+i.source).toLowerCase().includes(q)); }
  if(state.cat!=="全部") its = its.filter(i=>i.category===state.cat);
  if(state.sort==="score") its.sort((a,b)=>b.score-a.score);
  else if(state.sort==="time") its.sort((a,b)=>b.discovered_at.localeCompare(a.discovered_at));
  root.querySelector(".count").textContent = its.length;
  const list = $("#all-list"); list.innerHTML = its.length ? its.map(itemCard).join("") : '<div class="empty">没有匹配的条目</div>';
}
function renderHot(){
  const root = $("#view-hot");
  root.innerHTML = '<div class="card"><ol class="hot-rank-list">'+S.topics.map((t,i)=>{
    const flag = t.status==="爆"?'<span class="flag flag-hot">爆</span>':(t.status==="发酵中"?'<span class="flag flag-warm">发酵中</span>':'<span class="flag flag-watch">关注中</span>');
    const chips = (t.sources||[]).map(s=>'<span class="chip">'+esc(s)+'</span>').join("");
    const link0 = t.links&&t.links[0]?t.links[0].url:"";
    return '<li class="hot-rank-row"><span class="hot-rank-no">'+String(i+1).padStart(2,"0")+'</span>'+
      '<div class="hot-rank-main"><div class="hot-rank-title"><a href="'+esc(link0)+'" target="_blank" rel="noopener">'+esc(t.title)+'</a> '+flag+'</div>'+
      '<div class="hot-rank-meta"><span>'+(t.sources[0]||"")+'</span><span>'+fmtRel(t.latest_at)+'</span><span>'+t.source_count+' 个信源 · '+t.signal_count+' 条信号</span></div>'+
      '<div class="src-chips">'+chips+'</div></div>'+
      '<div class="hot-rank-heat">'+Math.round(t.heat||t.score)+'<div style="font-size:11px;color:var(--muted);font-weight:400">热度值</div></div></li>';
  }).join("")+'</ol></div>';
}
function renderDaily(){
  const root = $("#view-daily");
  const dates = Object.keys(S.dailies||{}).sort().reverse();
  const d = state.dailyDate && S.dailies[state.dailyDate] ? state.dailyDate : (dates[0]||todayCN());
  state.dailyDate = d;
  const rep = S.dailies[d];
  const side = '<aside class="daily-side"><div class="daily-side-card"><h3>日报归档</h3>'+
    dates.map(x=>'<div class="daily-day'+(x===d?" daily-day-active":"")+'" data-d="'+x+'">'+fmtDay(x).slice(5)+'<span class="week">'+wdCN(x)+'</span></div>').join("")+
    '</div></aside>';
  let body = '<div class="m-daily-body">';
  if(rep){
    const toc = rep.sections.map((s,i)=>'<li><a class="reader-toc-row" href="#sec-'+i+'"><span class="reader-toc-no">'+String(i+1).padStart(2,"0")+'</span><span class="reader-toc-label">'+esc(s.category)+'</span><span>'+esc(s.articles[0].title)+'</span></a></li>').join("");
    body += '<div class="m-daily-eyebrow">OPTOHOT DAILY</div><div class="m-daily-issue-date">'+esc(rep.label)+' · '+esc(rep.weekday)+'</div>'+
      '<nav class="reader-toc"><div class="reader-toc-head"><span class="reader-toc-heading">今日看点</span><span class="reader-toc-meta">'+rep.tocCount+' 篇报道 · 约 '+rep.readMinutes+' 分钟</span></div><ol class="reader-toc-list">'+toc+'</ol></nav>';
    rep.sections.forEach((s,i)=>{
      body += '<section class="daily-sec" id="sec-'+i+'"><h3>'+esc(s.category)+'</h3>'+
        s.articles.map(a=>'<article class="daily-article"><div class="daily-article-title"><a href="'+esc(a.url)+'" target="_blank" rel="noopener">'+esc(a.title)+'</a></div>'+
        '<div class="daily-article-source"><span class="role-tag">'+esc(a.role)+'</span><span>'+esc(a.source)+'</span><span>'+esc(pubLabel(a))+'</span></div>'+
        (a.summary?'<p class="daily-article-summary">'+esc(a.summary)+'</p>':"")+'</article>').join("");
      body += '</section>';
    });
  } else {
    body += '<div class="empty">该日期暂无日报</div>';
  }
  body += '</div>';
  root.innerHTML = '<div class="daily-shell">'+side+body+'</div>';
  $$(".daily-day", root).forEach(el=>el.onclick=()=>{ state.dailyDate = el.dataset.d; renderDaily(); });
}
function renderTopics(){
  const root = $("#view-topics");
  const rows = S.daily.byCategory || [];
  root.innerHTML = '<div class="topic-grid">'+rows.map(r=>
    '<div class="topic-card" data-cat="'+esc(r.category)+'"><div class="t-name">'+esc(r.category)+'<span class="badge b-cat">'+r.total+'</span></div>'+
    '<div class="t-nums"><span>24h <b>'+r.last24h+'</b></span><span>7d <b>'+r.last7d+'</b></span><span>共 <b>'+r.total+'</b></span></div></div>').join("")+'</div>';
  $$(".topic-card", root).forEach(el=>el.onclick=()=>{ state.cat = el.dataset.cat; $("#all-cat").value = state.cat; location.hash = "#/all"; });
}
function renderData(){
  const root = $("#view-data");
  const dl = S.daily;
  const maxDay = Math.max(...dl.byDay.map(x=>x.count), 1);
  const chart = '<div class="day-chart">'+dl.byDay.map(x=>'<div class="day-col"><div class="dbar" style="height:'+Math.max(2,x.count/maxDay*100).toFixed(1)+'%"></div><span class="dl">'+x.date.slice(5)+'</span></div>').join("")+'</div>';
  const rows = dl.bySource.map(s=>'<tr><td>'+esc(s.source)+'</td><td>'+s.count+'</td><td>'+fmtRel(s.latestAt)+'</td></tr>').join("");
  root.innerHTML =
    '<div class="stats">'+
    '<div class="stat"><div class="num">'+dl.total+'</div><div class="lbl">收录总数</div></div>'+
    '<div class="stat"><div class="num">'+dl.last24h+'</div><div class="lbl">24 小时新增</div></div>'+
    '<div class="stat"><div class="num">'+dl.last7d+'</div><div class="lbl">7 天新增</div></div>'+
    '<div class="stat"><div class="num">'+dl.topicCount+'</div><div class="lbl">热点话题</div></div></div>'+
    '<div class="card pad"><h3 style="font-size:14px;margin-bottom:6px">每日收录趋势（近 14 天）</h3>'+chart+'</div>'+
    '<div class="card pad" style="margin-top:14px"><h3 style="font-size:14px;margin-bottom:6px">数据来源</h3><table><thead><tr><th>来源</th><th>收录数</th><th>最新收录</th></tr></thead><tbody>'+rows+'</tbody></table></div>'+
    '<div class="dl-row"><a class="dl-btn" href="data/report.csv" download>⬇ 下载 CSV</a><a class="dl-btn" href="data/items.json" target="_blank">查看 items.json</a><a class="dl-btn" href="data/hot-topics.json" target="_blank">查看 hot-topics.json</a><a class="dl-btn" href="data/dailies.json" target="_blank">查看 dailies.json</a></div>';
}
const renderers = { feed:renderFeed, all:renderAll, hot:renderHot, daily:renderDaily, topics:renderTopics, data:renderData };
function bind(){
  const cats = new Set(S.items.map(i=>i.category));
  const sel = $("#all-cat");
  for(const c of cats){ const o = document.createElement("option"); o.value = c; o.textContent = c; sel.appendChild(o); }
  $("#q").addEventListener("input", e=>{ state.q = e.target.value; if(location.hash==="#/all") renderAll(); });
  $("#all-cat").addEventListener("change", e=>{ state.cat = e.target.value; renderAll(); });
  $("#all-sort").addEventListener("change", e=>{ state.sort = e.target.value; renderAll(); });
  window.addEventListener("hashchange", router);
  router();
}
document.addEventListener("DOMContentLoaded", bind);
"""

APP_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Opto-Hot · 光电行业热点统计</title>
<style>/*__CSS__*/</style>
</head>
<body>
<header class="m-topbar"><div class="topbar-inner">
  <a class="brand" href="#/"><span class="logo">OH</span>Opto-Hot</a>
  <label class="searchbox"><input id="q" type="search" placeholder="搜索光电资讯 / 公司 / 关键词…" autocomplete="off"><span class="kbd">⌘K</span></label>
  <span class="topbar-meta">生成于 __GEN__ · 北京时间</span>
</div></header>
<div class="app-layout">
  <nav class="side-nav">
    <div class="side-group">内容</div>
    <a class="side-link" href="#/"><span class="si">✦</span><span class="side-label">精选</span></a>
    <a class="side-link" href="#/all"><span class="si">☰</span><span class="side-label">全部动态</span></a>
    <a class="side-link" href="#/hot"><span class="si">🔥</span><span class="side-label">热点榜</span></a>
    <a class="side-link" href="#/daily"><span class="si">📰</span><span class="side-label">光电日报</span></a>
    <a class="side-link" href="#/topics"><span class="si">◈</span><span class="side-label">主题</span></a>
    <a class="side-link" href="#/data"><span class="si">◉</span><span class="side-label">数据</span></a>
  </nav>
  <main class="app-main">
    <section id="view-feed" class="view"><div class="card page-head"><h1>精选</h1><span class="sub">AIHOT 模式 · 光电行业时间线</span></div></section>
    <section id="view-all" class="view"><div class="card page-head"><h1>全部动态</h1><span class="sub">共 <span class="count">0</span> 条</span>
      <select id="all-cat" class="dl-btn" style="margin-left:auto"><option>全部</option></select>
      <select id="all-sort" class="dl-btn"><option value="score">按推荐分</option><option value="time">按时间</option></select></div>
      <div id="all-list"></div></section>
    <section id="view-hot" class="view"><div class="card page-head"><h1>光电热点榜</h1><span class="sub">按信源密度 / 信号数 / 时效加权（48 小时报道密度）</span></div></section>
    <section id="view-daily" class="view"><div class="card page-head"><h1>光电日报</h1><span class="sub">自动生成 · 每日一篇</span></div></section>
    <section id="view-topics" class="view"><div class="card page-head"><h1>主题</h1><span class="sub">光电行业分类统计，点击进入筛选</span></div></section>
    <section id="view-data" class="view"><div class="card page-head"><h1>数据</h1><span class="sub">统计与导出</span></div></section>
  </main>
</div>
<footer>
  Opto-Hot · 光电行业热点统计（AIHOT 模式） · 数据来自公开网络，仅供参考，不构成投资建议 · <a href="https://github.com/sun-zihang/opto-hot" target="_blank" rel="noopener" style="color:var(--accent)">GitHub 开源</a>
</footer>
<script>
/*__JS__*/
</script>
</body>
</html>"""


def fmt_dt(iso):
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ_CN).strftime("%m-%d %H:%M")
    except Exception:
        return iso


def pub_label(it):
    if it.get("published_at"):
        p = it["published_at"]
        if len(p) == 7:
            return p + "（月级）发布"
        if len(p) == 10:
            return p + " 发布"
        return p.replace("T", " ")[:16] + " 发布"
    return "收录 " + fmt_dt(it["discovered_at"])


def render_app_html(items, topics, daily, dailies, generated):
    import json as _json
    snapshot = {
        "generatedAt": generated.isoformat(),
        "catCls": CAT_CLS,
        "items": items,
        "topics": topics,
        "daily": daily,
        "dailies": dailies,
    }
    snap_json = _json.dumps(snapshot, ensure_ascii=False)
    snap_json = snap_json.replace("</", "<\\/")
    html = APP_HTML.replace("/*__CSS__*/", APP_CSS).replace("/*__JS__*/", APP_JS)
    html = html.replace("__SNAPSHOT__", snap_json)
    html = html.replace("__GEN__", generated.astimezone(TZ_CN).strftime("%Y-%m-%d %H:%M"))
    return html

# ---------------- 输出 ----------------
def write_outputs(items, topics, daily, dailies, generated):
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(DIST_DIR, exist_ok=True)

    def dump(obj, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)

    for it in items:
        it.setdefault("links", {})
        it["links"]["original"] = it["url"]
        it["selected"] = it["score"] >= 60
        it["role"] = role_tag(it["source"])
    for t in topics:
        t["heat"] = t["score"]
        if t["source_count"] >= 5 and t["score"] >= 80:
            t["status"] = "爆"
        elif t["source_count"] >= 3:
            t["status"] = "发酵中"
        else:
            t["status"] = "关注中"

    dump({"schemaVersion": 1, "generatedAt": generated.isoformat(),
          "count": len(items), "items": items}, os.path.join(DATA_DIR, "items.json"))
    dump({"schemaVersion": 1, "generatedAt": generated.isoformat(),
          "count": len(topics), "items": topics}, os.path.join(DATA_DIR, "hot-topics.json"))
    dump(daily, os.path.join(DATA_DIR, "daily.json"))
    dump({"schemaVersion": 1, "generatedAt": generated.isoformat(),
          "count": len(dailies), "dailies": dailies}, os.path.join(DATA_DIR, "dailies.json"))

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "title", "category", "source", "published_at", "discovered_at",
                "score", "url", "role", "selected"])
    for it in items:
        w.writerow([it["id"], it["title"], it["category"], it["source"],
                    it.get("published_at") or "", it["discovered_at"], it["score"], it["url"],
                    it["role"], it["selected"]])
    with open(os.path.join(DATA_DIR, "report.csv"), "w", encoding="utf-8-sig", newline="") as f:
        f.write(buf.getvalue())

    with open(os.path.join(DIST_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_app_html(items, topics, daily, dailies, generated))

    log("[*] 已写出: data/items.json, data/hot-topics.json, data/daily.json, data/dailies.json, data/report.csv, dist/index.html")


def main():
    ap = argparse.ArgumentParser(description="光电行业热点统计采集器")
    ap.add_argument("--limit", type=int, default=25, help="每个源最多取多少条 (默认 25)")
    ap.add_argument("--topics", type=int, default=10, help="热点榜输出条数 (默认 10)")
    ap.add_argument("--skip-rss", action="store_true", help="跳过 RSS 源")
    ap.add_argument("--skip-html", action="store_true", help="跳过 HTML 站")
    args = ap.parse_args()

    with open(SOURCES_PATH, encoding="utf-8") as f:
        sources = json.load(f)

    log("[*] 开始采集（每源上限 %d 条）..." % args.limit)
    raw = collect(sources, args.limit, args.skip_rss, args.skip_html)
    log("[*] 原始条目合计 %d 条" % len(raw))

    generated = now_utc()
    source_weight = {}
    for stype in ("rss", "html"):
        for cfg in sources.get(stype, []):
            source_weight[cfg["name"]] = cfg.get("weight", 0.8)

    items = []
    seen = set()
    for r in raw:
        k = norm_title(r["title"])
        if k in seen:
            continue
        seen.add(k)
        items.append({
            "id": make_id(r["title"], r["url"]),
            "title": r["title"],
            "url": r["url"],
            "source": r["source"],
            "source_type": r["source_type"],
            "category": classify(r["title"], r["source"]),
            "published_at": r.get("published_at"),
            "discovered_at": generated.isoformat(),
            "summary": r.get("summary"),
            "keywords": extract_keywords(r["title"]),
            "score": 0.0,
        })
    log("[*] 去重后 %d 条" % len(items))

    topics = cluster_topics(items)
    topics = merge_duplicate_topics(topics, items)
    compute_scores(items, topics, source_weight)
    items.sort(key=lambda i: i["score"], reverse=True)
    topics.sort(key=lambda t: t["score"], reverse=True)
    topics = dedupe_topic_titles(topics, items)
    topics.sort(key=lambda t: t["score"], reverse=True)
    for idx, t in enumerate(topics[:args.topics], 1):
        t["rank"] = idx
    topics = topics[:args.topics]
    for t in topics:
        t.pop("ids", None)
        t.pop("items", None)

    daily = build_daily(items, topics, generated)
    dailies = build_dailies(items)
    write_outputs(items, topics, daily, dailies, generated)

    log("[*] 完成。热点榜 TOP5：")
    for t in topics[:5]:
        log("    #%d %s (来源 %d · 信号 %d · 热度 %.0f)" % (
            t["rank"], t["title"][:50], t["source_count"], t["signal_count"], t["score"]))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)