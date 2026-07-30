# ScholarBridge｜开放与授权 PDF 文献桥

ScholarBridge 将 DOI、PMCID、arXiv ID、BibTeX、RIS、CSV 和数据库导出转化为经过核验的本地学术 PDF，并为每条记录保留来源、访问类型、版本、哈希与失败原因。开放版本自动解析；CNKI、万方、维普和出版社内容通过用户已经登录的可见浏览器进行授权下载，再交接到 Zotero。

它不是 Google Scholar 爬虫，也不是付费墙绕过器。它解决的是：

> 如何从开放学术基础设施中批量定位合法全文，验证下载结果确实是 PDF，并把“没有开放版本”和“下载失败”如实保留下来。

## 已实现

- CSV、TSV、JSON、JSONL、TXT、BibTeX 和 RIS 输入；
- DOI、arXiv ID、PMCID、题名和 URL 规范化；
- 标题高度匹配时通过 Crossref 保守补全 DOI；
- DOI 和标识符去重；
- arXiv、PMC、Europe PMC、Unpaywall、OpenAlex、CORE、DOAJ 适配器；
- 直接 PDF 与 HTML `citation_pdf_url` 解析；
- `%PDF-`、文件体积、`%%EOF` 和 SHA-256 校验；
- 内容哈希去重，不覆盖已有文件；
- dry run、请求间隔、数量和文件大小限制；
- 私网、回环和本地 URL 默认拒绝；
- `manifest.csv`、`plan.jsonl`、`attempts.jsonl`、`report.md`；
- Windows/Linux 兼容的标准库实现；
- 自动测试和可安装 Skill ZIP。
- CNKI、万方、维普、出版社等授权浏览器下载队列；
- 浏览器下载目录接管、残缺文件检测、PDF匹配与归档；
- Zotero MCP查重、导入与附件关联交接任务。

## 开放来源

| 来源 | ScholarBridge 中的作用 | 是否直接提供 PDF |
|---|---|---|
| CORE | 聚合全球开放仓储 | 很多记录可以 |
| Unpaywall | DOI → 合法 OA 位置 | 可能是 PDF 或落地页 |
| arXiv | 预印本全文 | 可以 |
| PMC OA Subset | 医学与生命科学开放全文 | 可以 |
| Europe PMC | DOI → 开放 PMCID | 通过 PMC 获取 |
| OpenAlex | 学术图谱与 OA 位置 | 部分记录可以 |
| DOAJ | 开放期刊文章目录 | 多数链接到外部站点 |
| Zenodo/机构知识库 | 用户提供的开放 PDF 地址 | 视具体记录而定 |

Crossref、PubMed、OpenCitations 和 Google Scholar 主要用于发现、元数据或引用关系，不能把检索命中数当作 PDF 下载成功数。

详细说明见 [`references/open-sources.md`](references/open-sources.md)。

## Google Scholar 的位置

Google Scholar适合：

- 查漏补缺；
- 查看“所有版本”；
- 发现右侧的开放 PDF；
- 导出 BibTeX、EndNote 等题录；
- 检查被引和相关文献。

Google Scholar官方不提供批量访问接口，因此 ScholarBridge不实施自动翻页、无人值守抓取或验证码绕过。正确流程是：

```text
Google Scholar 人工检索/导出
             ↓
DOI、题名、BibTeX、RIS
             ↓
ScholarBridge 开放来源解析
             ↓
合法 PDF 下载与验证
```

## 快速开始

要求 Python 3.10 或更高版本，无第三方 Python 依赖。

```bash
git clone https://github.com/LHT666-hub/ScholarBridge.git
cd ScholarBridge
python scripts/doctor.py
python -m unittest discover -s tests -v
```

`doctor.py` 同时检查开放 API 配置、Kimi WebBridge Skill/本地端口、可选
`cnki-mcp` 命令、Zotero Desktop Connector 与 Zotero MCP端口。端口未监听通常
只是相关桌面程序尚未启动，不等于安装失败。

### 1. 规范化文献清单

```bash
python scripts/normalize_records.py input.ris \
  --output-dir literature_run/normalized
```

### 2. 先生成计划

```bash
python scripts/fetch_open_pdfs.py \
  literature_run/normalized/records.jsonl \
  --output-dir literature_run/acquisition \
  --email researcher@example.edu
```

不加 `--execute` 时不会下载。

### 3. 执行下载

```bash
python scripts/fetch_open_pdfs.py \
  literature_run/normalized/records.jsonl \
  --output-dir literature_run/acquisition \
  --email researcher@example.edu \
  --max-records 100 \
  --execute
```

Windows PowerShell 如果找不到 `python`，可以使用已经安装的解释器：

```powershell
& "C:\anaconda3\python.exe" scripts\fetch_open_pdfs.py `
  assets\input.example.csv `
  --output-dir literature_run\acquisition `
  --email researcher@example.edu `
  --execute
```

### 4. 验证已有 PDF

```bash
python scripts/verify_pdfs.py literature_run/acquisition/pdf \
  --output-dir literature_run/verification
```

### 5. 处理机构订阅数据库

```bash
python scripts/prepare_authorized_queue.py \
  literature_run/normalized/records.jsonl \
  --output-dir literature_run/authorized
```

按生成的 `browser-handoff.md` 在可见浏览器里登录并使用平台原生 PDF
下载按钮。ScholarBridge不接收账号密码，也不把 Cookie 写进项目。

```bash
python scripts/ingest_downloads.py \
  literature_run/authorized/authorized-queue.jsonl \
  --download-dir ~/Downloads \
  --output-dir literature_run/authorized-ingest
```

### 6. 交接到 Zotero

```bash
python scripts/build_zotero_handoff.py \
  literature_run/authorized-ingest/ingest-manifest.csv \
  --output-dir literature_run/zotero \
  --collection ScholarBridge
```

Agent读取 `zotero-handoff.jsonl` 后，优先通过 Zotero MCP 按 DOI/题名查重：
已有条目使用 `zotero_attach_file`，新条目使用 `zotero_add_from_file`。若当前
环境没有 Zotero写入工具，必须报告“只生成交接任务”，不能宣称已经入库。

## 登录态到底怎么保持

ScholarBridge不模拟用户输入账号密码。可选方式是：

1. Kimi WebBridge或 Playwright MCP扩展连接到用户已经登录的真实 Chrome；
2. 平台专项工具启动一个可见的 Playwright持久化浏览器目录，用户首次手动登录；
3. 不推荐但部分项目采用的 Cookie JSON导出/恢复。

前两种让认证材料留在浏览器。详细项目分析、技术路线和限制见
[`references/acquisition-routes.md`](references/acquisition-routes.md)。

## 可选配置

```text
SCHOLARBRIDGE_EMAIL=researcher@example.edu
OPENALEX_API_KEY=...
CORE_API_KEY=...
```

- Unpaywall要求真实联系邮箱；
- OpenAlex与CORE在配置相应密钥后启用；
- 没有密钥时，arXiv、PMC、Europe PMC 和 DOAJ 仍可使用；
- 密钥只放环境变量，不要提交到 Git。

## 输出

```text
literature_run/acquisition/
├── pdf/
├── plan.jsonl
├── attempts.jsonl
├── manifest.csv
├── report.md
└── summary.json
```

只有通过 PDF 头、文件大小、EOF 和 SHA-256 校验的文件才会标记为 `downloaded`。

主要状态：

| 状态 | 含义 |
|---|---|
| `downloaded` | 下载且校验成功 |
| `duplicate` | 内容哈希与已有 PDF 相同 |
| `no_open_pdf` | 未找到合法开放 PDF |
| `failed` | 找到候选但下载或校验失败 |
| `dry_run` | 只生成计划，未执行下载 |

## 批量快照不是普通论文下载

OpenAlex、arXiv、PMC、Europe PMC 和 CORE 都有不同形式的数据集或批量服务，但完整数据可能达到数百 GB 或数 TB。完整镜像需要单独的：

- 存储容量评估；
- 分片和断点续传；
- 官方清单与校验和；
- 增量更新；
- 许可证与再分发审计。

ScholarBridge当前的默认执行器面向有界文献清单，不用于镜像整个数据库。

## 安全与合规

- 不绕过付费墙、验证码、DRM 和下载配额；
- 不记录密码、Cookie 或会话 Token；
- 不抓取 Google Scholar 搜索结果；
- 不把学校订阅权限解释为无限自动下载许可；
- 403、429、验证码或访问警告时停止对应来源；
- 不把下载的论文提交进本仓库；
- 大规模 TDM 应申请平台官方数据集或 TDM/API 权限。

详见 [`references/compliance.md`](references/compliance.md) 与 [`SECURITY.md`](SECURITY.md)。

## Skill 安装包

生成：

```bash
python scripts/package_skill.py --output dist/skill.zip
```

ZIP 保留 `scholar-bridge/` 根目录，可上传到支持 Skills 的环境。

## 项目结构

```text
ScholarBridge/
├── SKILL.md
├── README.md
├── agents/openai.yaml
├── assets/
├── references/
├── scripts/
├── tests/
└── .github/workflows/test.yml
```

## 尚未完全实现

- Google Scholar自动抓取——有意不做；
- 知网、万方、维普的通用无人值守下载——有意保留用户登录、CAPTCHA和下载确认；
- Zenodo REST 与通用 OAI-PMH 专项适配器；
- 无 Zotero MCP 时的跨版本直接附件写入；
- 全数据库快照镜像；
- 各闭源平台长期稳定的 DOM 选择器与实库回归测试。

## 不采用的路线

SciPDF（也常被称为 ScanSciPDF）通过向 Zotero写入 Sci-Hub自定义 PDF resolver，
按 DOI尝试补附件。它不是开放获取校验，也不是机构登录路线。ScholarBridge仅在
技术路线文档中说明其机制，不集成、不测试也不分发 Sci-Hub resolver。
