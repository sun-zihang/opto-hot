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


# ---------------- HTML 报告 ----------------
CAT_CLS = {
    "激光": "laser", "光通信": "fiber", "显示与面板": "display", "光电芯片与半导体": "chip",
    "光学元件与成像": "optics", "光传感与激光雷达": "sensing", "光伏与新能源": "pv",
    "科研进展": "research", "产业与资本": "capital", "通信与算力": "telecom", "其他": "other",
}

CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans SC", "Segoe UI", sans-serif;
       background: #f4f6fb; color: #1f2430; line-height: 1.6; }
a { color: #2557d6; text-decoration: none; }
a:hover { text-decoration: underline; }
.wrap { max-width: 1080px; margin: 0 auto; padding: 0 20px; }
.top { background: linear-gradient(120deg, #0f2a5f 0%, #1b4b9e 55%, #2f7ce0 100%);
       color: #fff; padding: 34px 0 26px; }
.top h1 { font-size: 26px; letter-spacing: 1px; }
.top h1 .en { font-size: 15px; opacity: .85; font-weight: 500; margin-left: 8px; }
.top .sub { margin-top: 8px; font-size: 13px; opacity: .9; }
.top .sub a { color: #cfe0ff; }
.cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 22px 0 6px; }
.card { background: #fff; border-radius: 12px; padding: 16px 18px; box-shadow: 0 1px 4px rgba(20,40,90,.08); }
.card .num { font-size: 30px; font-weight: 700; color: #1b4b9e; }
.card .lbl { font-size: 13px; color: #6b7280; margin-top: 2px; }
section { margin: 26px 0; }
h2 { font-size: 19px; color: #0f2a5f; margin-bottom: 12px; display: flex; align-items: baseline; gap: 10px; }
h2 .hint { font-size: 12px; color: #8a93a6; font-weight: 400; }
.topics { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; min-width: 0; }
.topic { background: #fff; border-radius: 12px; padding: 16px 18px; box-shadow: 0 1px 4px rgba(20,40,90,.08);
         border-left: 4px solid #2f7ce0; min-width: 0; overflow: hidden; }
.topic .t-head { display: flex; align-items: center; gap: 10px; }
.topic .rank { min-width: 26px; height: 26px; border-radius: 8px; background: #0f2a5f; color: #fff;
               font-size: 14px; font-weight: 700; display: flex; align-items: center; justify-content: center; }
.topic .t-title { font-size: 15.5px; font-weight: 600; color: #1b3a75; }
.topic .t-meta { font-size: 12px; color: #7a8396; margin-top: 6px; }
.topic .t-src { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
.chip { font-size: 11px; background: #eef2fb; color: #3c5a9e; border-radius: 20px; padding: 2px 10px; }
.topic .t-links { margin-top: 8px; font-size: 12.5px; }
.topic .t-links li { list-style: none; margin: 2px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.items { background: #fff; border-radius: 12px; box-shadow: 0 1px 4px rgba(20,40,90,.08); list-style: none; min-width: 0; }
.item { display: flex; align-items: center; gap: 12px; padding: 11px 16px; border-bottom: 1px solid #eef1f7; }
.item:last-child { border-bottom: none; }
.item .it-main { flex: 1; min-width: 0; }
.item .it-title { font-size: 14.5px; color: #1f2430; font-weight: 500; }
.item .it-meta { font-size: 12px; color: #8a93a6; margin-top: 2px; }
.item .it-score { font-size: 13px; color: #2f7ce0; font-weight: 600; min-width: 34px; text-align: right; }
.badge { font-size: 11px; color: #fff; border-radius: 6px; padding: 2px 8px; white-space: nowrap; }
.b-laser { background: #e0563c; } .b-fiber { background: #2f7ce0; } .b-display { background: #8e44ad; }
.b-chip { background: #16a085; } .b-optics { background: #e67e22; } .b-sensing { background: #27ae60; }
.b-pv { background: #f39c12; } .b-research { background: #5b6ee1; } .b-capital { background: #c0392b; } .b-telecom { background: #34495e; }
.b-other { background: #7f8c8d; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; min-width: 0; }
.panel { background: #fff; border-radius: 12px; padding: 16px 18px; box-shadow: 0 1px 4px rgba(20,40,90,.08); min-width: 0; overflow: hidden; }
.panel h3 { font-size: 14px; color: #0f2a5f; margin-bottom: 10px; }
.cat-row { display: grid; grid-template-columns: 84px 1fr 120px; align-items: center; gap: 10px; margin: 7px 0; font-size: 12.5px; }
.cat-row .bar { height: 10px; border-radius: 6px; background: #eef1f7; overflow: hidden; }
.cat-row .bar > i { display: block; height: 100%; background: linear-gradient(90deg, #2f7ce0, #6aa4f0); border-radius: 6px; }
.cat-row .n { color: #6b7280; text-align: right; }
.day-chart { display: flex; align-items: flex-end; gap: 6px; height: 120px; padding-top: 6px; }
.day-col { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; gap: 4px; height: 100%; }
.day-col .dbar { width: 70%; background: linear-gradient(180deg, #6aa4f0, #2f7ce0); border-radius: 5px 5px 0 0; min-height: 2px; }
.day-col .dl { font-size: 10px; color: #8a93a6; }
table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 4px rgba(20,40,90,.08); font-size: 13px; }
th, td { padding: 9px 14px; text-align: left; border-bottom: 1px solid #eef1f7; }
th { background: #f7f9fd; color: #556; font-weight: 600; }
footer { margin: 34px 0 26px; font-size: 12px; color: #8a93a6; text-align: center; }
footer a { color: #2f7ce0; }
@media (max-width: 860px) { .cards { grid-template-columns: 1fr 1fr; } .topics, .cols { grid-template-columns: 1fr; } }
"""


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


def item_html(it):
    t = htmlmod.escape(it["title"])
    u = htmlmod.escape(it["url"])
    cat = it["category"]
    src = htmlmod.escape(it["source"])
    return ('<li class="item"><span class="badge b-%s">%s</span>'
            '<div class="it-main"><a class="it-title" href="%s" target="_blank" rel="noopener">%s</a>'
            '<div class="it-meta">%s · %s</div></div>'
            '<span class="it-score">%.0f</span></li>'
            % (CAT_CLS.get(cat, "other"), htmlmod.escape(cat), u, t, src,
               pub_label(it), it["score"]))


def render_html(items, topics, daily, generated):
    cards = ""
    cards += '<div class="card"><div class="num">%d</div><div class="lbl">收录总数</div></div>' % daily["total"]
    cards += '<div class="card"><div class="num">%d</div><div class="lbl">24 小时新增</div></div>' % daily["last24h"]
    cards += '<div class="card"><div class="num">%d</div><div class="lbl">7 天新增</div></div>' % daily["last7d"]
    cards += '<div class="card"><div class="num">%d</div><div class="lbl">热点话题</div></div>' % daily["topicCount"]

    topic_html = []
    for t in topics:
        links = "".join(
            '<li><a href="%s" target="_blank" rel="noopener">%s</a> · <span style="color:#8a93a6">%s</span></li>'
            % (htmlmod.escape(l["url"]), htmlmod.escape(l["title"][:46]), htmlmod.escape(l["source"]))
            for l in t["links"][:3])
        chips = "".join('<span class="chip">%s</span>' % htmlmod.escape(s) for s in t["sources"][:8])
        topic_html.append(
            '<div class="topic"><div class="t-head"><span class="rank">%d</span>'
            '<span class="t-title"><a href="%s" target="_blank" rel="noopener">%s</a></span></div>'
            '<div class="t-meta">来源 %d 个 · 信号 %d 条 · 更新 %s · 热度 %.0f</div>'
            '<div class="t-src">%s</div><ul class="t-links">%s</ul></div>'
            % (t["rank"], htmlmod.escape(t["links"][0]["url"] if t["links"] else "#"),
               htmlmod.escape(t["title"][:52]), t["source_count"], t["signal_count"],
               fmt_dt(t["latest_at"]), t["score"], chips, links))
    topics_block = "\n".join(topic_html)

    items_24 = [i for i in items if age_days(eff_dt(i)) <= 1]
    items_7 = [i for i in items if age_days(eff_dt(i)) <= 7][:30]
    list_24 = "\n".join(item_html(i) for i in items_24) or '<li class="item" style="color:#8a93a6">24 小时内暂无收录</li>'
    list_7 = "\n".join(item_html(i) for i in items_7) or '<li class="item" style="color:#8a93a6">7 天内暂无收录</li>'

    max24 = max([c["last24h"] for c in daily["byCategory"]] + [1])
    max7 = max([c["last7d"] for c in daily["byCategory"]] + [1])
    cat_rows = []
    for c in daily["byCategory"]:
        w24 = c["last24h"] / max24 * 100
        w7 = c["last7d"] / max7 * 100
        cat_rows.append(
            '<div class="cat-row"><span>%s</span><div class="bar"><i style="width:%.1f%%"></i></div>'
            '<span class="n">24h %d · 7d %d · 共 %d</span></div>'
            % (htmlmod.escape(c["category"]), w24, c["last24h"], c["last7d"], c["total"]))
    cat_block = "\n".join(cat_rows)

    maxday = max([d["count"] for d in daily["byDay"]] + [1])
    day_cols = []
    for d in daily["byDay"]:
        h = max(2, d["count"] / maxday * 100)
        day_cols.append('<div class="day-col"><div class="dbar" style="height:%.1f%%"></div>'
                        '<span class="dl">%s</span></div>' % (h, d["date"][5:]))
    day_block = '<div class="day-chart">%s</div>' % "\n".join(day_cols)

    src_rows = "".join(
        "<tr><td>%s</td><td>%d</td><td>%s</td></tr>"
        % (htmlmod.escape(s["source"]), s["count"], fmt_dt(s["latestAt"]))
        for s in daily["bySource"])

    gen_cn = generated.astimezone(TZ_CN).strftime("%Y-%m-%d %H:%M:%S")
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>光电行业热点统计 · Opto-Hot</title>
<style>%s</style>
</head>
<body>
<header class="top"><div class="wrap">
<h1>光电行业热点统计 <span class="en">Opto-Hot</span></h1>
<p class="sub">以 AIHOT 为模板的光电产业资讯聚合与热点统计 · 生成于 %s（北京时间） · <a href="%s" target="_blank" rel="noopener">GitHub 开源仓库</a></p>
</div></header>
<main class="wrap">
<section class="cards">%s</section>
<section><h2>热点榜 <span class="hint">按来源数 / 信号数 / 时效加权</span></h2><div class="topics">%s</div></section>
<section><h2>24 小时精选 <span class="hint">共 %d 条</span></h2><ul class="items">%s</ul></section>
<section><h2>7 天精选 Top 30 <span class="hint">共 %d 条</span></h2><ul class="items">%s</ul></section>
<section class="cols">
<div class="panel"><h3>分类统计（24h / 7d / 总计）</h3>%s</div>
<div class="panel"><h3>每日收录趋势（近 14 天，北京时间）</h3>%s</div>
</section>
<section><h2>数据来源</h2><table><thead><tr><th>来源</th><th>收录数</th><th>最新收录</th></tr></thead><tbody>%s</tbody></table></section>
<footer>
数据来自公开网络（RSS / 行业网站首页），由 opto-hot 自动采集统计，仅供参考，不构成任何投资建议。
<br>生成时间：%s（北京时间）· <a href="%s" target="_blank" rel="noopener">opto-hot</a> · 数据模式参考 AIHOT（自建实现）
</footer>
</main>
</body>
</html>""" % (
        CSS, gen_cn, REPO_URL, cards, topics_block, daily["last24h"], list_24,
        daily["last7d"], list_7, cat_block, day_block, src_rows, gen_cn, REPO_URL)
    return html


# ---------------- 输出 ----------------
def write_outputs(items, topics, daily, generated):
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(DIST_DIR, exist_ok=True)

    def dump(obj, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)

    dump({"schemaVersion": 1, "generatedAt": generated.isoformat(),
          "count": len(items), "items": items}, os.path.join(DATA_DIR, "items.json"))
    dump({"schemaVersion": 1, "generatedAt": generated.isoformat(),
          "count": len(topics), "items": topics}, os.path.join(DATA_DIR, "hot-topics.json"))
    dump(daily, os.path.join(DATA_DIR, "daily.json"))

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "title", "category", "source", "published_at", "discovered_at", "score", "url"])
    for it in items:
        w.writerow([it["id"], it["title"], it["category"], it["source"],
                    it.get("published_at") or "", it["discovered_at"], it["score"], it["url"]])
    with open(os.path.join(DATA_DIR, "report.csv"), "w", encoding="utf-8-sig", newline="") as f:
        f.write(buf.getvalue())

    with open(os.path.join(DIST_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_html(items, topics, daily, generated))

    log("[*] 已写出: data/items.json, data/hot-topics.json, data/daily.json, data/report.csv, dist/index.html")


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
    write_outputs(items, topics, daily, generated)

    log("[*] 完成。热点榜 TOP5：")
    for t in topics[:5]:
        log("    #%d %s (来源 %d · 信号 %d · 热度 %.0f)" % (
            t["rank"], t["title"][:50], t["source_count"], t["signal_count"], t["score"]))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)