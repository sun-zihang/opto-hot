# Opto-Hot · 光电行业热点统计

以 [AIHOT](https://aihot.virxact.com) 为模板的开源「光电行业热点统计」工具：自动采集公开网络上的光电产业资讯，去重分类、聚类打分，输出热点榜 / 精选 / 分类统计 / 每日趋势，并生成可离线打开的中文 HTML 报告。

## 特性

- **多源采集**：13 个公开数据源（RSS + 行业网站），中文为主、兼顾国际（arXiv / Nature Photonics / Phys.org / C114 / OFweek / LEDinside / CIOE / COEMA）
- **时间窗口**：24 小时 / 7 天精选，优先采用原文发布时间，缺失时回退为收录时间（AIHOT 时间轴语义）
- **领域分类**：激光、光通信、显示与面板、光电芯片与半导体、光学元件与成像、光传感与激光雷达、光伏与新能源、科研进展、产业与资本、通信与算力
- **热点榜**：按「来源数 / 信号数 / 时效」加权打分，自动聚类并合并同一事件的多角度报道
- **零依赖**：仅用 Python 标准库；HTML 报告为自包含单文件（无 CDN / 无外部资源）
- **自动化**：内置 GitHub Actions，每 6 小时自动刷新数据并提交

## 快速开始

```bash
git clone https://github.com/sun-zihang/opto-hot.git
cd opto-hot
python collector/collect.py          # 需要联网；Python 3.8+
```

生成产物：

| 文件 | 说明 |
|---|---|
| `dist/index.html` | 中文 HTML 报告（热点榜 / 精选 / 统计图表） |
| `data/items.json` | 全部采集条目（含分类、关键词、得分） |
| `data/hot-topics.json` | 热点榜（rank / 来源数 / 信号数 / 链接） |
| `data/daily.json` | 统计：分类、每日趋势、来源分布 |
| `data/report.csv` | 条目 CSV 导出（Excel 可直接打开） |

常用参数：

```bash
python collector/collect.py --limit 30   # 每个源最多取 30 条
python collector/collect.py --topics 15  # 热点榜输出 15 条
python collector/collect.py --skip-html  # 跳过行业网站（只跑 RSS）
```

## 数据源（13 个）

| 类型 | 名称 | 地址 | 权重 |
|---|---|---|---|
| RSS | arXiv 光学与光子学 (physics.optics) | `http://export.arxiv.org/rss/physics.optics` | 0.8 |
| RSS | Nature Photonics | `https://www.nature.com/nphoton.rss` | 0.9 |
| RSS | Phys.org 物理新闻（关键词过滤） | `https://phys.org/rss-feed/physics-news/` | 0.6 |
| RSS | C114中国通信网_要闻精选 | `http://www.c114.com.cn/rss/rss_news_489.xml` | 0.9 |
| RSS | C114中国通信网_通信财经 | `http://www.c114.com.cn/rss/rss_news_24.xml` | 0.9 |
| RSS | C114中国通信网_IT资讯 | `http://www.c114.com.cn/rss/rss_news_27.xml` | 0.8 |
| RSS | C114中国通信网_设备商 | `http://www.c114.com.cn/rss/rss_news_18.xml` | 0.9 |
| RSS | C114中国通信网_监管 | `http://www.c114.com.cn/rss/rss_news_550.xml` | 0.7 |
| HTML | OFweek 光电频道 | `https://optics.ofweek.com/` | 1.0 |
| HTML | OFweek 激光频道 | `https://laser.ofweek.com/` | 1.0 |
| HTML | LEDinside 中文 | `https://www.ledinside.cn/` | 0.9 |
| HTML | CIOE 中国光博会 | `https://cioe.cn/` | 0.9 |
| HTML | COEMA 中国光电子行业协会 | `https://www.coema.org.cn/` | 0.8 |

> 抓取说明：COEMA 页面实际为 GBK 编码（meta 声明为 utf-8）；OFweek 为 GB2312；C114 RSS 为 GBK 编码的 RSS 2.0；Nature Photonics 为 RSS 1.0 (RDF)。采集器已做对应处理。源配置在 `collector/sources.json`，可自由增删。

## 打分模型（透明可复现）

- 条目得分 = `50 × 来源权重 + 25 × min(1, 主题信号数/10) + 25 × 时效`，其中时效 = `max(0, 1 − 距今天数/30)`
- 主题热度 = `100 × (0.45 × min(1, 来源数/6) + 0.35 × min(1, 信号数/10) + 0.20 × 48 小时内信号占比)`
- 聚类：以领域词表 + 英文词（去停用词）做关键词索引，≥2 条命中的词构成候选主题；重叠 ≥50% 或代表条目相同的主题自动合并

## 目录结构

```
opto-hot/
├── collector/
│   ├── collect.py        # 主脚本：采集→清洗→分类→打分→聚类→输出
│   └── sources.json      # 数据源配置（RSS / HTML 解析规则）
├── data/                 # 生成的数据（JSON / CSV）
├── dist/index.html       # 生成的 HTML 报告
├── .github/workflows/update.yml  # 每 6 小时自动更新
├── README.md
└── LICENSE               # MIT
```

## GitHub Actions 自动更新

`.github/workflows/update.yml` 每 6 小时运行一次采集器并自动提交数据更新（也可手动 `workflow_dispatch` 触发）。因为 GitHub 服务器位于海外，个别国内站点可能超时，采集器对每个源单独容错，单源失败不影响整体输出。

## 路线图

- [ ] 接入更多源（英文行业媒体、微信公众号精选、政策/招投标信息）
- [ ] 用嵌入向量做语义聚类，替代关键词聚类（减少噪声主题）
- [ ] 历史日报归档（daily archive），支持按日期回看
- [ ] 多语言报告 / 图表交互（筛选、排序）

## 数据与免责声明

数据来自公开网络（RSS / 网站首页），由本工具自动采集与统计，仅供行业资讯参考，**不构成任何投资建议**。各源内容版权归原作者/原站所有；如原站不允许抓取，请在 `sources.json` 中移除对应源。

## License

[MIT](LICENSE)