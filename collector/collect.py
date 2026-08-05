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
import time
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
        elif ud == "y-m-d-t":
            mu = re.search(r"t(\d{4})(\d{2})(\d{2})", href)
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
    tk = [k.lower() for k in cfg.get("title_keywords", [])]
    items = []
    for e in entries:
        title = (e["title"] or e["link"] or "").strip()
        if not title:
            continue
        if kws and not any(k in title.lower() for k in kws):
            continue
        if tk and not any(k in title.lower() for k in tk):
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


SOGOU_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def fetch_sogou(cfg, limit):
    """搜狗微信：多查询 + 会话 Cookie + 反爬检测 + 公众号/时间/摘要提取"""
    import http.cookiejar
    import urllib.parse as up
    queries = cfg.get("queries") or []
    if not queries:
        m = re.search(r"[?&]query=([^&]+)", cfg["url"])
        queries = [up.unquote(m.group(1))] if m else ["光电行业"]
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    tk = [k.lower() for k in cfg.get("title_keywords", [])]
    seen = set()
    items = []
    for q in queries:
        url = "https://weixin.sogou.com/weixin?type=2&query=" + up.quote(q)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": SOGOU_UA, "Referer": "https://weixin.sogou.com/"})
            data = opener.open(req, timeout=20).read().decode("utf-8", "replace")
        except Exception as e:
            log("[FAIL] 搜狗微信 query=%s: %s" % (q, e))
            time.sleep(2)
            continue
        if "antispider" in data or "请输入验证码" in data or "news-list" not in data:
            log("[!] 搜狗微信 query=%s 触发反爬或页面异常，跳过" % q)
            time.sleep(2)
            continue
        for m2 in re.finditer(r'id="sogou_vr_\d+_box_\d+"[\s\S]*?</li>', data):
            blk = m2.group(0)
            tm = re.search(r'uigs="article_title_\d+"[^>]*>([\s\S]*?)</a>', blk)
            if not tm:
                continue
            title = re.sub(r"<[^>]+>", "", tm.group(1))
            title = re.sub(r"<!--red_beg-->|<!--red_end-->", "", title)
            title = re.sub(r"\s+", " ", htmlmod.unescape(title)).strip()
            if len(title) < 8:
                continue
            hm = re.search(r'href="(/link\?url=[^"]+)"', blk)
            if not hm:
                continue
            am = re.search(r'class="all-time-y2"[^>]*>([^<]+)<', blk)
            account = htmlmod.unescape(am.group(1)).strip() if am else ""
            tmm = re.search(r"timeConvert\('(\d+)'\)", blk)
            pub = None
            if tmm:
                try:
                    pub = datetime.fromtimestamp(int(tmm.group(1)), timezone.utc).isoformat()
                except Exception:
                    pass
            sm = re.search(r'class="txt-info"[^>]*>([\s\S]*?)</p>', blk)
            summary = re.sub(r"<[^>]+>", "", sm.group(1)) if sm else ""
            summary = re.sub(r"<!--red_beg-->|<!--red_end-->", "", summary)
            summary = re.sub(r"\s+", " ", htmlmod.unescape(summary)).strip()[:300]
            if pub:
                try:
                    if age_days(datetime.fromisoformat(pub)) > 90:
                        continue
                except Exception:
                    pass
            if tk and not any(k in title.lower() for k in tk):
                continue
            key = norm_title(title)
            if key in seen:
                continue
            seen.add(key)
            src = cfg["name"] + (" · " + account if account else "")
            items.append({"title": title,
                          "url": urllib.parse.urljoin("https://weixin.sogou.com", hm.group(1)),
                          "published_at": pub, "summary": summary or None, "source": src})
            if len(items) >= limit:
                break
        time.sleep(1.2)
        if len(items) >= limit:
            break
    return items


def fetch_html(cfg, limit):
    if cfg.get("sogou_wechat"):
        return fetch_sogou(cfg, limit)
    data, ctype = http_get(cfg["url"])
    charset = cfg.get("charset") or detect_charset(data, ctype)
    links = parse_html_links(data, charset, cfg["url"], cfg)
    tk = [k.lower() for k in cfg.get("title_keywords", [])]
    items = []
    for lk in links:
        if tk and not any(k in lk["title"].lower() for k in tk):
            continue
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
                    g["source"] = g.get("source") or cfg["name"]
                    g["source_type"] = stype
                    g["source_weight"] = cfg.get("weight", 0.8)
                raw.extend(got)
            except Exception as e:
                log("[FAIL] %-4s %s: %s" % (stype, cfg["name"], e))
    return raw


# ---------------- 热点聚类 ----------------
def text_tokens(title):
    """向量化 token：中文字符二元组 + 英文词 + 领域特征词（用于 TF-IDF 语义向量）"""
    tl = title.lower()
    toks = []
    for seg in re.findall(r"[\u4e00-\u9fff]+", tl):
        if len(seg) == 1:
            toks.append(seg)
        else:
            toks.append(seg)
            toks.extend(seg[i:i + 2] for i in range(len(seg) - 1))
    toks.extend(w for w in re.findall(r"[a-z][a-z0-9]{2,}", tl) if w not in STOPWORDS)
    for term in DOMAIN_TERMS:
        if kw_hit(tl, term):
            toks.append("DT:" + term.lower())
    return toks


def tfidf_vectors(items):
    docs = [text_tokens(it["title"]) for it in items]
    df = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    n = max(1, len(docs))
    vecs = []
    for d in docs:
        c = {}
        for t in d:
            c[t] = c.get(t, 0) + 1
        v = {t: (1 + (f ** 0.5)) * (n / (df.get(t, 1) + 1)) for t, f in c.items()}
        vecs.append(v)
    return vecs


def cosine_sim(a, b):
    inter = [t for t in a if t in b]
    if not inter:
        return 0.0
    dot = sum(a[t] * b[t] for t in inter)
    na = sum(x * x for x in a.values()) ** 0.5
    nb = sum(x * x for x in b.values()) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def cluster_semantic(items, threshold=0.14):
    """语义聚类：TF-IDF 向量贪心聚合为主；可选神经嵌入做近重复合并（OPTOHOT_EMBED=1）"""
    n = len(items)
    tfidf = tfidf_vectors(items)
    sim = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            s = cosine_sim(tfidf[i], tfidf[j])
            sim[i][j] = sim[j][i] = s
    groups = list(range(n))
    while True:
        best = (threshold, -1, -1)
        for i in range(n):
            gi = groups[i]
            if gi < 0:
                continue
            for j in range(i + 1, n):
                gj = groups[j]
                if gj < 0 or gi == gj:
                    continue
                if sim[i][j] > best[0]:
                    best = (sim[i][j], i, j)
        if best[1] < 0:
            break
        ga, gb = groups[best[1]], groups[best[2]]
        for k in range(n):
            if groups[k] == gb:
                groups[k] = ga

    # 神经近重复合并（真实嵌入；相似度>=0.70 视为同一事件的重复/改写报道）
    if os.environ.get("OPTOHOT_EMBED") == "1":
        try:
            os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "20")
            os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "10")
            try:
                urllib.request.urlopen(urllib.request.Request(
                    "https://huggingface.co/BAAI/bge-small-zh-v1.5/resolve/main/config.json",
                    headers={"User-Agent": UA}), timeout=8)
            except Exception:
                log("[!] HuggingFace 不可达，跳过神经近重复合并")
                use_nn = False
            else:
                use_nn = True
            if use_nn:
                from sentence_transformers import SentenceTransformer
                _m = SentenceTransformer("BAAI/bge-small-zh-v1.5")
                vecs = _m.encode([it["title"] for it in items], normalize_embeddings=True)

                def find(x):
                    while parent[x] != x:
                        parent[x] = parent[parent[x]]
                        x = parent[x]
                    return x

                def union(a, b):
                    ra, rb = find(a), find(b)
                    if ra != rb:
                        parent[rb] = ra

                parent = list(range(n))
                for i in range(n):
                    vi = vecs[i]
                    for j in range(i + 1, n):
                        s = float(sum(vi[k] * vecs[j][k] for k in range(len(vi))))
                        if s >= 0.70:
                            union(i, j)
                gset = {}
                for idx, g in enumerate(groups):
                    gset.setdefault(g, []).append(idx)
                for members in gset.values():
                    for k in range(1, len(members)):
                        union(members[0], members[k])
                rootmap = {}
                ng = [0] * n
                for x in range(n):
                    r = find(x)
                    if r not in rootmap:
                        rootmap[r] = len(rootmap)
                    ng[x] = rootmap[r]
                groups = ng
                log("[*] 神经近重复合并完成（sentence-transformers / bge-small-zh）")
        except Exception as e:
            log("[!] 神经嵌入不可用，仅 TF-IDF 聚类: %s" % e)

    from collections import defaultdict
    gmap = defaultdict(list)
    for idx, g in enumerate(groups):
        if g >= 0:
            gmap[g].append(items[idx])
    topics = []
    for its in gmap.values():
        if len(its) >= 2:
            terms = set()
            for it in its:
                terms.update(it.get("keywords", []))
            topics.append({"terms": terms, "ids": {i["id"] for i in its}})
    return topics


def cluster_topics(items):
    return cluster_semantic(items)


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
    topic_map = {}
    for t in topics:
        for iid in t["ids"]:
            topic_map[iid] = (t["id"], t["title"])
    for it in items:
        if it["id"] in topic_map:
            it["topic_id"], it["topic_title"] = topic_map[it["id"]]


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
    try:
        tvec = tfidf_vectors(its)
        centroid = {}
        for v in tvec:
            for kk, w in v.items():
                centroid[kk] = centroid.get(kk, 0) + w
        ranked = sorted(centroid.items(), key=lambda x: -x[1])
        t["top_terms"] = [k2 for k2, _ in ranked if not k2.startswith("DT:")][:5] or [k2 for k2, _ in ranked][:5]
    except Exception:
        t["top_terms"] = []


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


def fetch_text(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    cs = detect_charset(data)
    txt = data.decode(cs, "replace")
    txt = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", txt, flags=re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = htmlmod.unescape(txt)
    return re.sub(r"\s+", " ", txt)


def extract_biz_text(text, title=""):
    """从详情页文本提取 项目号/预算/截止时间（比标题级更可靠）"""
    biz = {}
    m = re.search(r"(?:项目|招标|采购)(?:编号|项目号|标段号)\s*[:：]\s*([^\s，。；,;]{3,40})", text)
    if not m:
        m = re.search(r"(?:招标编号|项目编号|采购编号|标段(?:编)?号)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-_（）()]{3,})", text)
    if m:
        biz["project_no"] = m.group(1).strip()
    m = re.search(r"预算(?:金额|资金)?\s*[:：]\s*([0-9,，.]+)\s*(万|亿)?\s*元", text)
    if m:
        biz["budget"] = m.group(1).replace(",", "").replace("，", "") + (m.group(2) or "") + "元"
    m = re.search(r"(?:投标|递交|报名|获取采购文件|响应文件)(?:截止|递交截止)(?:时间)?\s*[:：]?\s*(\d{4}年\d{1,2}月\d{1,2}日(?:\s*\d{1,2}[:：]\d{2})?)", text)
    if not m:
        m = re.search(r"截止时间\s*[:：]?\s*(\d{4}[-年/.]\d{1,2}[-月/.]\d{1,2}日?(?:\s*\d{1,2}[:：]\d{2})?)", text)
    if m:
        biz["deadline"] = m.group(1).replace("年", "-").replace("月", "-").replace("日", "").replace("：", ":")
    if "project_no" not in biz:
        m = re.search(r"(?:发文字号|文号|文件编号)\s*[:：]?\s*([^\s，。；]{3,30})", text)
        if m:
            biz["project_no"] = m.group(1).strip()
    return biz


BIZ_SOURCES = {"中国政府采购网", "中国招标投标公共服务平台", "工信部要闻"}


def extract_biz(title):
    """从标题提取招标/政策结构化字段（项目号/预算/截止时间）——v1 标题级解析"""
    biz = {}
    m = re.search(r"(?:项目|招标|采购)?(?:编号|标段号|文号)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-—－_（）()]{3,})", title)
    if m:
        biz["project_no"] = m.group(1).strip("（）()")
    m = re.search(r"预算(?:金额|资金)?\s*[:：]?\s*([0-9,，.]+)\s*(万|亿)?\s*元", title)
    if m:
        num = m.group(1).replace(",", "").replace("，", "")
        biz["budget"] = (num + (m.group(2) or "") + "元")
    m = re.search(r"(?:截止|开标|投标截止|递交(?:截止)?)(?:时间)?\s*[:：]?\s*(\d{4}[-年/.]\d{1,2}[-月/.]\d{1,2}日?(?:\s*\d{1,2}[:：]\d{2})?)", title)
    if m:
        biz["deadline"] = m.group(1).replace("年", "-").replace("月", "-").replace("日", "").replace("：", ":")
    return biz


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


def build_dailies(items, existing=None):
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
    result = dict(existing or {})
    result.update(out)
    cutoff = (datetime.now(TZ_CN).date() - timedelta(days=365)).isoformat()
    return {k: v for k, v in result.items() if k >= cutoff}


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

.dm { font-size:11px; color:var(--muted); margin:8px 0 2px 2px; letter-spacing:.5px; }
.lang-btn { border:1px solid var(--border); background:var(--card); color:var(--accent); border-radius:8px; padding:4px 10px; font-size:12px; cursor:pointer; }
pre { background:#0f172a; color:#dbeafe; border-radius:10px; padding:12px 14px; overflow-x:auto; font-size:12px; line-height:1.5; }
.agent-note { font-size:12.5px; color:var(--muted); margin-top:8px; }
.hot-sort { display:inline-flex; gap:6px; margin-left:auto; }
.hot-sort button { border:1px solid var(--border); background:var(--card); color:var(--muted); border-radius:8px; padding:2px 9px; font-size:12px; cursor:pointer; }
.hot-sort button.on { color:var(--accent); border-color:var(--accent); }
.chip-term { background:var(--accent-soft); color:var(--accent); }
.gh-link { display:inline-flex; align-items:center; gap:5px; border:1px solid var(--accent); color:var(--accent); background:var(--accent-soft); border-radius:9px; padding:5px 12px; font-size:12.5px; font-weight:600; white-space:nowrap; }
.gh-link:hover { background:var(--accent); color:#fff; opacity:1; }
.gh-foot { color:var(--accent); font-weight:600; }

@media (max-width: 640px) {
  .topbar-inner { flex-wrap: wrap; gap: 8px; padding: 8px 12px; }
  .brand { font-size: 15px; }
  .searchbox { order: 3; flex-basis: 100%; max-width: none; }
  .topbar-meta { display: none; }
  .app-layout { padding: 10px; gap: 10px; }
  .side-nav { position: sticky; top: 0; z-index: 40; background: #fff; border-bottom: 1px solid var(--border); padding: 6px 8px; flex-wrap: nowrap; }
  .side-link { padding: 6px 10px; font-size: 13px; white-space: nowrap; }
  .page-head { flex-wrap: wrap; padding: 10px 12px; }
  .page-head .sub { flex-basis: 100%; }
  .hot-rank-row { flex-wrap: wrap; gap: 6px; }
  .hot-rank-heat { margin-left: 44px; }
  .timeline-card-head { flex-wrap: wrap; }
  .timeline-head-left { flex-wrap: wrap; }
  .topic-grid { grid-template-columns: repeat(auto-fill, minmax(148px, 1fr)); }
  .daily-side { position: static; }
  .daily-side-card { max-height: 220px; overflow-y: auto; }
  .m-daily-body { padding: 14px; }
  .hot-sort { margin-left: 0; }
  .hotcard-head { flex-wrap: wrap; }
  .cards { grid-template-columns: 1fr 1fr; }
  .dl-row { gap: 6px; }
  .dl-btn { padding: 5px 9px; font-size: 12px; }
  .cat-row { grid-template-columns: 76px 1fr; }
  .cat-row .n { display: none; }
}

"""

APP_JS = r"""const S = __SNAPSHOT__;
const $ = (sel, root=document) => root.querySelector(sel);
const $$ = (sel, root=document) => [...root.querySelectorAll(sel)];
const esc = s => String(s==null?"":s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
const CAT_CLS = S.catCls || {};
const CAT_EN = {"激光":"Laser","光通信":"Optical Comm","显示与面板":"Display & Panel","光电芯片与半导体":"Opto Chip & Semi","光学元件与成像":"Optics & Imaging","光传感与激光雷达":"Sensing & LiDAR","光伏与新能源":"PV & Energy","科研进展":"Research","产业与资本":"Industry & Capital","通信与算力":"Telecom & Compute","其他":"Other"};
const STATUS_EN = {"爆":"Hot","发酵中":"Trending","关注中":"Watch"};
const I18N = {
  zh: { feed:"精选", all:"全部动态", hot:"热点榜", daily:"光电日报", topics:"主题", data:"数据", agent:"Agent 接入",
    search:"搜索光电资讯 / 公司 / 关键词…", allCount:"共", items:"条", catAll:"全部", sortScore:"按推荐分", sortTime:"按时间",
    hotCard:"🔥 光电热点", hotMore:"热点榜 →", src:"来源", heat:"热度", daySel:"条精选", noMatch:"没有匹配的条目",
    hotPage:"光电热点榜", hotSub:"按信源密度 / 信号数 / 时效加权（48 小时报道密度）", heatVal:"热度值", sources:"个信源", signals:"条信号",
    dailyPage:"光电日报", dailySub:"自动生成 · 每日一篇（含历史归档）", toc:"今日看点", reports:"篇报道", minutes:"约", minutes2:"分钟", archive:"日报归档",
    topicsPage:"主题", topicsSub:"光电行业分类统计，点击进入筛选",
    dataPage:"数据", dataSub:"统计与导出", total:"收录总数", h24:"24 小时新增", h7:"7 天新增", hotTopic:"热点话题", trend:"每日收录趋势（近 14 天）",
    srcTable:"数据来源", latest:"最新收录", dlCSV:"⬇ 下载 CSV", dlItems:"查看 items.json", dlHot:"查看 hot-topics.json", dlDaily:"查看 dailies.json",
    agentPage:"Agent 接入", agentSub:"面向 AI / LLM / 智能体的数据接口（免鉴权，静态 JSON）", apiTitle:"数据 API（v1）",
    apiDesc:"数据每 6 小时自动更新，接口免鉴权，AI 智能体 / 脚本可直接消费。", endpoint:"接口", desc:"说明", open:"打开",
    curl:"用法示例（curl）", llmsNote:"站点根目录提供 llms.txt（LLM 友好入口），Agent 可先读取它再按需拉取接口。", base:"接口基地址（本页 URL 去掉 index.html）",
    footer:"Opto-Hot · 光电行业热点统计（AIHOT 模式）· 数据来自公开网络，仅供参考，不构成投资建议 · GitHub 开源" },
  en: { feed:"Selected", all:"All Items", hot:"Hot Topics", daily:"Daily Brief", topics:"Topics", data:"Data", agent:"Agent API",
    search:"Search optics/photonics news…", allCount:"Total", items:"items", catAll:"All", sortScore:"By score", sortTime:"By time",
    hotCard:"🔥 Hot Topics", hotMore:"Full ranking →", src:"src", heat:"heat", daySel:"selected", noMatch:"No matching items",
    hotPage:"Opto Hot Ranking", hotSub:"Weighted by source density / signals / recency (48h)", heatVal:"heat", sources:"sources", signals:"signals",
    dailyPage:"Daily Brief", dailySub:"Auto-generated daily (with archive)", toc:"Today's picks", reports:"stories", minutes:"~", minutes2:"min read", archive:"Archive",
    topicsPage:"Topics", topicsSub:"Category stats — click to filter",
    dataPage:"Data", dataSub:"Stats & export", total:"Total items", h24:"24h new", h7:"7d new", hotTopic:"Hot topics", trend:"Daily trend (14 days)",
    srcTable:"Sources", latest:"Latest", dlCSV:"⬇ Download CSV", dlItems:"items.json", dlHot:"hot-topics.json", dlDaily:"dailies.json",
    agentPage:"Agent API", agentSub:"Open JSON APIs for AI / LLM agents (no auth)", apiTitle:"Data API (v1)",
    apiDesc:"Data refreshes every 6h. Endpoints need no auth and are agent/script friendly.", endpoint:"Endpoint", desc:"Description", open:"Open",
    curl:"Examples (curl)", llmsNote:"llms.txt at site root is an LLM-friendly entry point.", base:"Base URL (this page URL minus index.html)",
    footer:"Opto-Hot · optoelectronics hot-topic stats (AIHOT-style) · public data, for reference only · open source on GitHub" }
};
let LANG = localStorage.getItem("opto-lang") || "zh";
const T = I18N[LANG];
const state = { q:"", cat:"全部", sort:"score", dailyDate:"", hotSort:"heat" };
function tr(){ $$("[data-i18n]").forEach(el=>{ const k=el.dataset.i18n; if(T[k]) el.textContent = T[k]; }); $("#lang").textContent = LANG==="zh"?"EN":"中"; $("#q").placeholder = T.search; }
function fmtRel(iso){ if(!iso) return ""; const t=new Date(iso); const d=(Date.now()-t.getTime())/1000; if(d<60) return "刚刚"; if(d<3600) return Math.floor(d/60)+" 分钟前"; if(d<86400) return Math.floor(d/3600)+" 小时前"; return Math.floor(d/86400)+" 天前"; }
function effDate(it){ const p=it.published_at; if(p&&p.length>=10) return p.slice(0,10); const d=new Date(it.discovered_at); return new Date(d.getTime()+8*3600*1000).toISOString().slice(0,10); }
function fmtDay(dstr){ const [y,m,d]=dstr.split("-").map(Number); return y+"年"+m+"月"+d+"日"; }
function wdCN(dstr){ return ["周日","周一","周二","周三","周四","周五","周六"][new Date(dstr+"T00:00:00+08:00").getDay()]; }
function todayCN(){ return new Date(Date.now()+8*3600*1000).toISOString().slice(0,10); }
function isToday(d){ return d===todayCN(); }
function scoreCls(s){ return s>=75?"score-hi":(s>=50?"score-mid":"score-low"); }
function pubLabel(it){ if(it.published_at){ const p=it.published_at; if(p.length===7) return p+"（月级）发布"; if(p.length===10) return p+" 发布"; return p.replace("T"," ").slice(5,16)+" 发布"; } return "收录 "+fmtRel(it.discovered_at); }
function catName(c){ return LANG==="en" ? (CAT_EN[c]||c) : c; }
function statusName(s){ return LANG==="en" ? (STATUS_EN[s]||s) : s; }
function catBadge(c){ return '<span class="badge b-cat">'+esc(catName(c))+'</span>'; }
function selBadge(){ return '<span class="badge b-selected">'+(LANG==="en"?"Pick":"精选")+'</span>'; }
function scoreEl(it){ return '<span class="timeline-score mono '+scoreCls(it.score)+'" title="score/100">'+Math.round(it.score)+'</span>'; }
function itemCard(it){ return '<article class="timeline-card"><div class="timeline-card-head"><div class="timeline-head-left">'+catBadge(it.category)+'<span class="timeline-source">'+esc(it.source)+'</span><span class="timeline-time">'+esc(pubLabel(it))+'</span>'+(it.selected?selBadge():"")+'</div><div class="timeline-head-right">'+scoreEl(it)+'</div></div><div class="timeline-body"><a href="'+esc(it.url)+'" target="_blank" rel="noopener">'+esc(it.title)+'</a>'+(it.summary?'<div class="timeline-summary">'+esc(it.summary)+'</div>':"")+'<a class="timeline-orig" href="'+esc(it.url)+'" target="_blank" rel="noopener">↗ source</a></div></article>'; }
const renderers = {};
function router(){ const h=(location.hash||"#/").replace("#",""); const name=h.split("?")[0]||"/"; const map={"/":"feed","/all":"all","/hot":"hot","/daily":"daily","/topics":"topics","/data":"data","/agent":"agent"}; const v=map[name]||"feed"; $$(".side-link").forEach(a=>a.classList.toggle("side-link-active", a.getAttribute("href")===("#"+name))); $$(".view").forEach(x=>x.classList.remove("view-active")); $("#view-"+v).classList.add("view-active"); (renderers[v]||renderers.feed)(); }
function renderFeed(){ const root=$("#view-feed"); root.innerHTML=""; const top=S.topics.slice(0,6); let hot='<div class="card hotcard"><div class="hotcard-head"><span class="t">'+T.hotCard+'</span><a class="more" href="#/hot">'+T.hotMore+'</a></div><ol class="hot-topics-list">'+top.map((t,i)=>'<li class="hot-topics-row"><span class="hot-topics-rank hot-topics-rank-'+(i+1)+'">'+(i+1)+'</span><a class="hot-topics-link" href="'+(t.links&&t.links[0]?esc(t.links[0].url):"#/hot")+'" target="_blank" rel="noopener">'+esc(t.title)+'</a><span class="hot-topics-meta">'+t.source_count+' '+T.src+' · <b>'+Math.round(t.heat||t.score)+'</b> '+T.heat+'</span></li>').join("")+'</ol></div>'; const groups={}; for(const it of S.items){ const d=effDate(it); (groups[d]=groups[d]||[]).push(it); } const days=Object.keys(groups).sort().reverse().slice(0,7); let tl=""; for(const d of days){ const its=groups[d].slice().sort((a,b)=>b.score-a.score).slice(0,20); tl+='<div class="timeline-day"><div class="timeline-day-head"><h2>'+(isToday(d)?"今天 "+fmtDay(d):fmtDay(d))+'</h2><span class="week">'+wdCN(d)+'</span><span class="cnt">'+its.length+' '+T.daySel+'</span></div><div class="timeline">'+its.map(itemCard).join("")+'</div></div>'; } root.innerHTML=hot+tl; }
function renderAll(){ const root=$("#view-all"); let its=S.items.slice(); if(state.q){ const q=state.q.toLowerCase(); its=its.filter(i=>(i.title+" "+(i.summary||"")+" "+i.source).toLowerCase().includes(q)); } if(state.cat!=="全部") its=its.filter(i=>i.category===state.cat); if(state.sort==="score") its.sort((a,b)=>b.score-a.score); else if(state.sort==="time") its.sort((a,b)=>b.discovered_at.localeCompare(a.discovered_at)); root.querySelector(".count").textContent=its.length; $("#all-list").innerHTML=its.length?its.map(itemCard).join(""):'<div class="empty">'+T.noMatch+'</div>'; }
function renderHot(){ const root=$("#view-hot"); let ts=S.topics.slice(); if(state.hotSort==="sources") ts.sort((a,b)=>b.source_count-a.source_count); const head='<div class="card page-head"><h1>'+T.hotPage+'</h1><span class="sub">'+T.hotSub+'</span><span class="hot-sort"><button data-hs="heat" class="'+(state.hotSort==="heat"?"on":"")+'">'+T.heat+'</button><button data-hs="sources" class="'+(state.hotSort==="sources"?"on":"")+'">'+T.src+'</button></span></div>'; root.innerHTML=head+'<div class="card"><ol class="hot-rank-list">'+ts.map((t,i)=>{ const s=t.status; const flag=s==="爆"?'<span class="flag flag-hot">'+statusName(s)+'</span>':(s==="发酵中"?'<span class="flag flag-warm">'+statusName(s)+'</span>':'<span class="flag flag-watch">'+statusName(s)+'</span>'); const chips=(t.sources||[]).map(x=>'<span class="chip">'+esc(x)+'</span>').join(""); const terms=(t.top_terms||[]).map(x=>'<span class="chip chip-term">'+esc(x)+'</span>').join(""); const l0=t.links&&t.links[0]?t.links[0].url:""; return '<li class="hot-rank-row"><span class="hot-rank-no">'+String(i+1).padStart(2,"0")+'</span><div class="hot-rank-main"><div class="hot-rank-title"><a href="'+esc(l0)+'" target="_blank" rel="noopener">'+esc(t.title)+'</a> '+flag+'</div><div class="hot-rank-meta"><span>'+(t.sources[0]||"")+'</span><span>'+fmtRel(t.latest_at)+'</span><span>'+t.source_count+' '+T.sources+' · '+t.signal_count+' '+T.signals+'</span></div><div class="src-chips">'+terms+chips+'</div></div><div class="hot-rank-heat">'+Math.round(t.heat||t.score)+'<div style="font-size:11px;color:var(--muted);font-weight:400">'+T.heatVal+'</div></div></li>'; }).join("")+'</ol></div>'; }
function renderDaily(){ const root=$("#view-daily"); const dates=Object.keys(S.dailies||{}).sort().reverse(); const d=state.dailyDate&&S.dailies[state.dailyDate]?state.dailyDate:(dates[0]||todayCN()); state.dailyDate=d; const rep=S.dailies[d]; let side='<aside class="daily-side"><div class="daily-side-card"><h3>'+T.archive+'（'+dates.length+'）</h3>'; let cm=""; for(const x of dates){ const m=x.slice(0,7); if(m!==cm){ cm=m; side+='<div class="dm">'+m+'</div>'; } side+='<div class="daily-day'+(x===d?" daily-day-active":"")+'" data-d="'+x+'">'+fmtDay(x).slice(5)+'<span class="week">'+wdCN(x)+'</span></div>'; } side+='</div></aside>'; let body='<div class="m-daily-body">'; if(rep){ const toc=rep.sections.map((s,i)=>'<li><a class="reader-toc-row" href="#sec-'+i+'"><span class="reader-toc-no">'+String(i+1).padStart(2,"0")+'</span><span class="reader-toc-label">'+esc(catName(s.category))+'</span><span>'+esc(s.articles[0].title)+'</span></a></li>').join(""); body+='<div class="m-daily-eyebrow">OPTOHOT DAILY</div><div class="m-daily-issue-date">'+esc(rep.label)+' · '+esc(rep.weekday)+'</div><nav class="reader-toc"><div class="reader-toc-head"><span class="reader-toc-heading">'+T.toc+'</span><span class="reader-toc-meta">'+rep.tocCount+' '+T.reports+' · '+T.minutes+' '+rep.readMinutes+' '+T.minutes2+'</span></div><ol class="reader-toc-list">'+toc+'</ol></nav>'; rep.sections.forEach((s,i)=>{ body+='<section class="daily-sec" id="sec-'+i+'"><h3>'+esc(catName(s.category))+'</h3>'+s.articles.map(a=>'<article class="daily-article"><div class="daily-article-title"><a href="'+esc(a.url)+'" target="_blank" rel="noopener">'+esc(a.title)+'</a></div><div class="daily-article-source"><span class="role-tag">'+esc(a.role)+'</span><span>'+esc(a.source)+'</span><span>'+esc(pubLabel(a))+'</span></div>'+(a.summary?'<p class="daily-article-summary">'+esc(a.summary)+'</p>':"")+'</article>').join(""); body+='</section>'; }); } else { body+='<div class="empty">-</div>'; } body+='</div>'; root.innerHTML='<div class="daily-shell">'+side+body+'</div>'; $$(".daily-day", root).forEach(el=>el.onclick=()=>{ state.dailyDate=el.dataset.d; renderDaily(); }); }
function renderTopics(){ const root=$("#view-topics"); const rows=S.daily.byCategory||[]; root.innerHTML='<div class="topic-grid">'+rows.map(r=>'<div class="topic-card" data-cat="'+esc(r.category)+'"><div class="t-name">'+esc(catName(r.category))+'<span class="badge b-cat">'+r.total+'</span></div><div class="t-nums"><span>24h <b>'+r.last24h+'</b></span><span>7d <b>'+r.last7d+'</b></span><span>'+T.total+' <b>'+r.total+'</b></span></div></div>').join("")+'</div>'; $$(".topic-card", root).forEach(el=>el.onclick=()=>{ state.cat=el.dataset.cat; $("#all-cat").value=state.cat; location.hash="#/all"; }); }
function renderData(){ const root=$("#view-data"); const dl=S.daily; const maxDay=Math.max(...dl.byDay.map(x=>x.count),1); const chart='<div class="day-chart">'+dl.byDay.map(x=>'<div class="day-col"><div class="dbar" title="'+x.date+': '+x.count+'" style="height:'+Math.max(2,x.count/maxDay*100).toFixed(1)+'%"></div><span class="dl">'+x.date.slice(5)+'</span></div>').join("")+'</div>'; const rows=dl.bySource.map(s=>'<tr><td>'+esc(s.source)+'</td><td>'+s.count+'</td><td>'+fmtRel(s.latestAt)+'</td></tr>').join(""); root.innerHTML='<div class="stats"><div class="stat"><div class="num">'+dl.total+'</div><div class="lbl">'+T.total+'</div></div><div class="stat"><div class="num">'+dl.last24h+'</div><div class="lbl">'+T.h24+'</div></div><div class="stat"><div class="num">'+dl.last7d+'</div><div class="lbl">'+T.h7+'</div></div><div class="stat"><div class="num">'+dl.topicCount+'</div><div class="lbl">'+T.hotTopic+'</div></div></div><div class="card pad"><h3 style="font-size:14px;margin-bottom:6px">'+T.trend+'</h3>'+chart+'</div><div class="card pad" style="margin-top:14px"><h3 style="font-size:14px;margin-bottom:6px">'+T.srcTable+'</h3><table><thead><tr><th>'+T.srcTable+'</th><th>'+T.total+'</th><th>'+T.latest+'</th></tr></thead><tbody>'+rows+'</tbody></table></div><div class="dl-row"><a class="dl-btn" href="data/report.csv" download>'+T.dlCSV+'</a><a class="dl-btn" href="data/items.json" target="_blank">'+T.dlItems+'</a><a class="dl-btn" href="data/hot-topics.json" target="_blank">'+T.dlHot+'</a><a class="dl-btn" href="data/dailies.json" target="_blank">'+T.dlDaily+'</a></div>'; }
function renderAgent(){
  const root=$("#view-agent");
  const base=location.href.split("?")[0].split("#")[0].replace(/index\.html$/,"");
  const eps=[["items",T.dlItems],["hot-topics",T.dlHot],["dailies",T.dlDaily],["daily","daily.json"],["stories","stories.json"],["biz","政策/招投标库"]];
  const rows=eps.map(([k,d])=>'<tr class="ep-table"><td class="mono">api/v1/'+k+'.json</td><td>'+d+'</td><td><a href="'+base+'api/v1/'+k+'.json" target="_blank" rel="noopener">'+T.open+' ↗</a></td></tr>').join("");
  const curl=eps.map(([k])=>'curl '+base+'api/v1/'+k+'.json').join("\n");
  const feeds=["feed.xml","category/laser.xml","category/fiber.xml","category/display.xml","category/chip.xml","category/optics.xml","category/sensing.xml","category/pv.xml","category/research.xml","category/capital.xml","category/telecom.xml","category/other.xml"];
  const feedRows=feeds.map((f,idx)=>'<tr class="ep-table"><td class="mono">feed/'+f+'</td><td>'+(idx===0?'RSS 全部':'分类 RSS')+'</td><td><a href="'+base+'feed/'+f+'" target="_blank" rel="noopener">'+T.open+' ↗</a></td></tr>').join("");
  const moreRows='<tr class="ep-table"><td class="mono">api/v1/openapi.json</td><td>OpenAPI 3.1</td><td><a href="'+base+'api/v1/openapi.json" target="_blank" rel="noopener">'+T.open+' ↗</a></td></tr><tr class="ep-table"><td class="mono">llms.txt</td><td>LLM 友好入口</td><td><a href="'+base+'llms.txt" target="_blank" rel="noopener">'+T.open+' ↗</a></td></tr>';
  let h='<div class="card pad"><h3 style="font-size:15px;margin-bottom:4px">🤖 '+T.apiTitle+'</h3><p class="agent-note">'+T.apiDesc+'</p><p class="agent-note">'+T.base+'：<span class="mono">'+esc(base)+'</span></p><table style="margin-top:10px"><thead><tr><th>'+T.endpoint+'</th><th>'+T.desc+'</th><th></th></tr></thead><tbody>'+rows+moreRows+'</tbody></table></div>';
  h+='<div class="card pad" style="margin-top:14px"><h3 style="font-size:15px;margin-bottom:4px">RSS</h3><table style="margin-top:8px"><tbody>'+feedRows+'</tbody></table></div>';
  h+='<div class="card pad" style="margin-top:14px"><h3 style="font-size:15px;margin-bottom:4px">'+T.curl+'</h3><pre>'+esc(curl)+'</pre><p class="agent-note">'+T.llmsNote+'</p><p class="agent-note">Agent Skill：仓库 <span class="mono">agent/skills/opto-hot</span>（可安装到 ~/.agents/skills 或 ~/.codex/skills）</p></div>';
  root.innerHTML=h;
}
renderers.feed=renderFeed; renderers.all=renderAll; renderers.hot=renderHot; renderers.daily=renderDaily; renderers.topics=renderTopics; renderers.data=renderData; renderers.agent=renderAgent;
function bind(){ const cats=new Set(S.items.map(i=>i.category)); const sel=$("#all-cat"); for(const c of cats){ const o=document.createElement("option"); o.value=c; o.textContent=catName(c); sel.appendChild(o); } $("#q").addEventListener("input",e=>{ state.q=e.target.value; if(location.hash==="#/all") renderAll(); }); $("#all-cat").addEventListener("change",e=>{ state.cat=e.target.value; renderAll(); }); $("#all-sort").addEventListener("change",e=>{ state.sort=e.target.value; renderAll(); }); document.addEventListener("click", e=>{ const b=e.target.closest&&e.target.closest("[data-hs]"); if(b){ state.hotSort=b.dataset.hs; renderHot(); } }); $("#lang").onclick=()=>{ LANG = LANG==="zh"?"en":"zh"; localStorage.setItem("opto-lang", LANG); location.reload(); }; window.addEventListener("hashchange",router); tr(); router(); }
document.addEventListener("DOMContentLoaded", bind);"""

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
  <a class="gh-link" href="https://github.com/sun-zihang/opto-hot" target="_blank" rel="noopener" title="GitHub 开源仓库">⭐ GitHub 开源</a>
  <button id="lang" class="lang-btn" title="切换语言 / Language">EN</button>
  <span class="topbar-meta">生成于 __GEN__ · 北京时间</span>
</div></header>
<div class="app-layout">
  <nav class="side-nav">
    <div class="side-group">内容</div>
    <a class="side-link" href="#/"><span class="si">✦</span><span class="side-label" data-i18n="feed">精选</span></a>
    <a class="side-link" href="#/all"><span class="si">☰</span><span class="side-label" data-i18n="all">全部动态</span></a>
    <a class="side-link" href="#/hot"><span class="si">🔥</span><span class="side-label" data-i18n="hot">热点榜</span></a>
    <a class="side-link" href="#/daily"><span class="si">📰</span><span class="side-label" data-i18n="daily">光电日报</span></a>
    <a class="side-link" href="#/topics"><span class="si">◈</span><span class="side-label" data-i18n="topics">主题</span></a>
    <a class="side-link" href="#/data"><span class="si">◉</span><span class="side-label" data-i18n="data">数据</span></a>
    <a class="side-link" href="#/agent"><span class="si">🤖</span><span class="side-label" data-i18n="agent">Agent 接入</span></a>
  </nav>
  <main class="app-main">
    <section id="view-feed" class="view"><div class="card page-head"><h1 data-i18n="feed">精选</h1><span class="sub">AIHOT 模式 · 光电行业时间线</span></div></section>
    <section id="view-all" class="view"><div class="card page-head"><h1 data-i18n="all">全部动态</h1><span class="sub"><span data-i18n="allCount">共</span> <span class="count">0</span> <span data-i18n="items">条</span></span>
      <select id="all-cat" class="dl-btn" style="margin-left:auto"><option data-i18n="catAll">全部</option></select>
      <select id="all-sort" class="dl-btn"><option value="score" data-i18n="sortScore">按推荐分</option><option value="time" data-i18n="sortTime">按时间</option></select></div>
      <div id="all-list"></div></section>
    <section id="view-hot" class="view"><div class="card page-head"><h1 data-i18n="hotPage">光电热点榜</h1><span class="sub"><span data-i18n="hotSub">按信源密度 / 信号数 / 时效加权（48 小时报道密度）</span></span><span class="hot-sort"><button data-hs="heat" class="on">热度</button><button data-hs="sources">信源</button></span></div></section>
    <section id="view-daily" class="view"><div class="card page-head"><h1 data-i18n="dailyPage">光电日报</h1><span class="sub"><span data-i18n="dailySub">自动生成 · 每日一篇（含历史归档）</span></span></div></section>
    <section id="view-topics" class="view"><div class="card page-head"><h1 data-i18n="topicsPage">主题</h1><span class="sub"><span data-i18n="topicsSub">光电行业分类统计，点击进入筛选</span></span></div></section>
    <section id="view-data" class="view"><div class="card page-head"><h1 data-i18n="dataPage">数据</h1><span class="sub"><span data-i18n="dataSub">统计与导出</span></span></div></section>
    <section id="view-agent" class="view"><div class="card page-head"><h1 data-i18n="agentPage">Agent 接入</h1><span class="sub"><span data-i18n="agentSub">面向 AI / LLM / 智能体的数据接口（免鉴权，静态 JSON）</span></span></div></section>
  </main>
</div>
<footer>
  <span data-i18n="footer">Opto-Hot · 光电行业热点统计（AIHOT 模式）· 数据来自公开网络，仅供参考，不构成投资建议</span> ·
  <a class="gh-foot" href="https://github.com/sun-zihang/opto-hot" target="_blank" rel="noopener">github.com/sun-zihang/opto-hot</a>
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
def build_rss(items, title, link, description, limit=50):
    import xml.sax.saxutils as su
    its = sorted(items, key=lambda it: it["discovered_at"], reverse=True)[:limit]
    pub = max(it["discovered_at"] for it in its) if its else now_utc().isoformat()
    out = []
    for it in its:
        out.append(
            "<item><title>%s</title><link>%s</link><description>%s</description>"
            "<guid isPermaLink=\"false\">%s</guid><pubDate>%s</pubDate>"
            "<source>%s</source><category>%s</category></item>"
            % (su.escape(it["title"]), su.escape(it["url"]), su.escape((it.get("summary") or "")[:500]),
               it["id"], it["discovered_at"], su.escape(it["source"]), su.escape(it["category"])))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
            "<title>%s</title><link>%s</link><description>%s</description>"
            "<lastBuildDate>%s</lastBuildDate>%s</channel></rss>"
            % (su.escape(title), su.escape(link), su.escape(description), pub, "".join(out)))


def build_openapi(generated):
    def ep(summary):
        return {"get": {"summary": summary, "responses": {"200": {"description": "OK"}}}}
    return {
        "openapi": "3.1.0",
        "info": {"title": "Opto-Hot API v1", "version": "1.0.0",
                 "description": "光电行业热点统计静态 JSON 接口（免鉴权，每 6 小时更新，AI/Agent 可直接消费）。"},
        "servers": [{"url": ""}],
        "paths": {
            "/api/v1/index.json": ep("接口索引"),
            "/api/v1/items.json": ep("全部条目"),
            "/api/v1/hot-topics.json": ep("热点榜"),
            "/api/v1/dailies.json": ep("光电日报（按日期归档）"),
            "/api/v1/daily.json": ep("统计聚合"),
            "/api/v1/stories.json": ep("事件故事（多源聚合）"),
            "/feed.xml": ep("RSS（最新 50 条）"),
            "/feed/category/{slug}.xml": ep("分类 RSS（slug: laser/fiber/display/chip/optics/sensing/pv/research/capital/telecom/other）"),
        },
    }


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

    # ---- 静态托管副本（GitHub Pages / CloudBase 均从 dist 发布） ----
    import shutil
    dist_data = os.path.join(DIST_DIR, "data")
    os.makedirs(dist_data, exist_ok=True)
    for fn in ("items.json", "hot-topics.json", "daily.json", "dailies.json", "report.csv"):
        shutil.copyfile(os.path.join(DATA_DIR, fn), os.path.join(dist_data, fn))

    # ---- Agent / API 接口（静态 JSON，v1） ----
    api_dir = os.path.join(DIST_DIR, "api", "v1")
    os.makedirs(api_dir, exist_ok=True)
    stories = []
    for t in topics:
        stories.append({
            "id": t["id"],
            "title": t["title"],
            "status": t.get("status"),
            "heat": t.get("heat", t.get("score")),
            "sourceCount": t["source_count"],
            "signalCount": t["signal_count"],
            "latestAt": t["latest_at"],
            "sources": t.get("sources", []),
            "links": t.get("links", []),
        })
    dump({"schemaVersion": 1, "generatedAt": generated.isoformat(),
          "count": len(items), "items": items}, os.path.join(api_dir, "items.json"))
    dump({"schemaVersion": 1, "generatedAt": generated.isoformat(),
          "count": len(topics), "items": topics}, os.path.join(api_dir, "hot-topics.json"))
    dump(dailies, os.path.join(api_dir, "dailies.json"))
    dump(daily, os.path.join(api_dir, "daily.json"))
    dump({"schemaVersion": 1, "generatedAt": generated.isoformat(),
          "count": len(stories), "items": stories}, os.path.join(api_dir, "stories.json"))
    dump({
        "name": "Opto-Hot API v1",
        "description": "光电行业热点统计静态 JSON 接口（免鉴权，每 6 小时更新）",
        "endpoints": {
            "items": "api/v1/items.json",
            "hot-topics": "api/v1/hot-topics.json",
            "dailies": "api/v1/dailies.json",
            "daily": "api/v1/daily.json",
            "stories": "api/v1/stories.json",
        },
    }, os.path.join(api_dir, "index.json"))

    # ---- RSS 分类 feed + OpenAPI ----
    feed_dir = os.path.join(DIST_DIR, "feed", "category")
    os.makedirs(feed_dir, exist_ok=True)
    site_link = "https://opto-hot-a455-d3g2s3dt865d86640.webapps.tcloudbase.com"
    with open(os.path.join(DIST_DIR, "feed.xml"), "w", encoding="utf-8") as f:
        f.write(build_rss(items, "Opto-Hot 光电热点", site_link + "/", "光电行业热点统计（AIHOT 模式）", 50))
    by_cat = {}
    for it in items:
        by_cat.setdefault(it["category"], []).append(it)
    for cat, its in by_cat.items():
        slug = CAT_CLS.get(cat, "other")
        with open(os.path.join(feed_dir, slug + ".xml"), "w", encoding="utf-8") as f:
            f.write(build_rss(its, "Opto-Hot · %s" % cat, site_link + "/#/all", cat, 30))
    with open(os.path.join(api_dir, "openapi.json"), "w", encoding="utf-8") as f:
        json.dump(build_openapi(generated), f, ensure_ascii=False, indent=2)

    # ---- 政策/招投标结构化库 ----
    biz_items = [it for it in items if it["source"] in BIZ_SOURCES]
    biz_rows = [{
        "source": it["source"], "title": it["title"], "url": it["url"],
        "category": it["category"], "published_at": it.get("published_at"),
        "discovered_at": it["discovered_at"],
        "project_no": (it.get("biz") or {}).get("project_no"),
        "budget": (it.get("biz") or {}).get("budget"),
        "deadline": (it.get("biz") or {}).get("deadline"),
    } for it in biz_items]
    biz_doc = {"schemaVersion": 1, "generatedAt": generated.isoformat(),
               "count": len(biz_rows),
               "fields": ["project_no", "budget", "deadline"], "items": biz_rows}
    dump(biz_doc, os.path.join(DATA_DIR, "biz.json"))
    shutil.copyfile(os.path.join(DATA_DIR, "biz.json"), os.path.join(dist_data, "biz.json"))
    dump(biz_doc, os.path.join(api_dir, "biz.json"))
    bbuf = io.StringIO()
    bw = csv.writer(bbuf)
    bw.writerow(["source", "title", "category", "url", "published_at", "discovered_at",
                 "project_no", "budget", "deadline"])
    for r in biz_rows:
        bw.writerow([r["source"], r["title"], r["category"], r["url"],
                     r.get("published_at") or "", r["discovered_at"],
                     r.get("project_no") or "", r.get("budget") or "", r.get("deadline") or ""])
    with open(os.path.join(DATA_DIR, "biz.csv"), "w", encoding="utf-8-sig", newline="") as f:
        f.write(bbuf.getvalue())
    shutil.copyfile(os.path.join(DATA_DIR, "biz.csv"), os.path.join(dist_data, "biz.csv"))

    # ---- llms.txt（LLM / Agent 友好入口） ----
    llms = """# Opto-Hot · 光电行业热点统计

> 光电行业资讯聚合与热点统计（AIHOT 模式），数据每天 12:00（北京时间）自动更新，本站数据为公开内容，适合作为 AI / Agent 的信息来源。

## 在线入口
- 报告页面: ./index.html
- GitHub 仓库: https://github.com/sun-zihang/opto-hot

## 数据 API（静态 JSON，免鉴权）
- 接口索引 / OpenAPI: ./api/v1/index.json , ./api/v1/openapi.json
- 全部条目: ./api/v1/items.json
- 热点榜: ./api/v1/hot-topics.json
- 光电日报（按日期归档）: ./api/v1/dailies.json
- 统计聚合: ./api/v1/daily.json
- 事件故事（多源聚合）: ./api/v1/stories.json
- 政策/招投标结构化库（项目号/预算/截止时间）: ./api/v1/biz.json

## RSS 订阅（阅读器 / Agent）
- 全部: ./feed.xml
- 分类: ./feed/category/{{slug}}.xml  （slug: laser/fiber/display/chip/optics/sensing/pv/research/capital/telecom/other）

## 用法示例（匿名 GET）
curl {base}/api/v1/hot-topics.json
curl {base}/api/v1/items.json
curl {base}/api/v1/dailies.json
curl {base}/feed.xml

## 约定
- 数据每天 12:00（北京时间）更新；可对完整 URL 使用 ETag / If-None-Match 减少拉取。
- items.json 为全量快照，可本地按 publishedAt / discoveredAt / keywords 筛选。
- 公开使用请注明一次数据来源：Opto-Hot（AIHOT 模式，数据源自各公开站点）。

## 说明
数据来自公开网络（RSS / 网站首页），自动采集统计，仅供参考，不构成投资建议。
"""
    with open(os.path.join(DIST_DIR, "llms.txt"), "w", encoding="utf-8") as f:
        f.write(llms.format(base=""))

    log("[*] 已写出: data/*.json+csv, dist/index.html, dist/llms.txt, dist/api/v1/*, dist/data/*")


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
            "biz": extract_biz(r["title"]) if r["source"] in BIZ_SOURCES else None,
            "score": 0.0,
        })
    log("[*] 去重后 %d 条" % len(items))

    # 政策/招投标：有界抓取详情页，提取 项目号/预算/截止时间（失败不影响整体）
    fetched = {src: 0 for src in BIZ_SOURCES}
    for it in items:
        if it["source"] not in BIZ_SOURCES:
            continue
        if fetched[it["source"]] >= 8:
            continue
        if not re.search(r"招标|采购|公告|通知|办法|条例|规定|意见|细则|询价|磋商|谈判|中标|更正|征集|遴选", it["title"]):
            continue
        try:
            text = fetch_text(it["url"])
        except Exception:
            continue
        b = extract_biz_text(text, it["title"])
        if b:
            it["biz"] = b
        fetched[it["source"]] += 1
        time.sleep(0.8)
    log("[*] 政策/招投标详情解析完成（命中 %d 条）" % sum(1 for it in items if it.get("biz")))

    topics = cluster_topics(items)
    topics = merge_duplicate_topics(topics, items)
    compute_scores(items, topics, source_weight)
    items.sort(key=lambda i: i["score"], reverse=True)
    topics.sort(key=lambda t: t["score"], reverse=True)
    topics = dedupe_topic_titles(topics, items)
    topics.sort(key=lambda t: t["score"], reverse=True)
    # 热点榜只保留有佐证的事件（多来源 或 ≥3 信号），剔除单源碎片
    topics = [t for t in topics if t["source_count"] >= 2 or t["signal_count"] >= 3]
    for idx, t in enumerate(topics[:args.topics], 1):
        t["rank"] = idx
    topics = topics[:args.topics]
    for t in topics:
        t.pop("ids", None)
        t.pop("items", None)

    daily = build_daily(items, topics, generated)
    existing_dailies = {}
    _dp = os.path.join(DATA_DIR, "dailies.json")
    if os.path.exists(_dp):
        try:
            with open(_dp, encoding="utf-8") as _f:
                existing_dailies = (json.load(_f) or {}).get("dailies", {}) or {}
        except Exception:
            existing_dailies = {}
    dailies = build_dailies(items, existing_dailies)
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