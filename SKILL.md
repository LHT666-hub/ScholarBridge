---
name: scholar-bridge
description: 批量发现、下载、核验并归档学术 PDF，再交接到 Zotero。用于 DOI、PMCID、arXiv ID、PDF URL、BibTeX、RIS、CSV、Google Scholar 或数据库导出；优先从 CORE、Unpaywall、arXiv、PMC、Europe PMC、OpenAlex 与 DOAJ 获取合法开放全文，也为 CNKI、万方、维普和出版社生成用户授权的可见浏览器下载队列，接管下载目录、验证 PDF、去重并生成 Zotero MCP 入库任务。
---

# ScholarBridge

将学术检索结果转化为经过验证、可追溯的本地 PDF。默认只处理开放获取或用户明确提供的合法直接链接；机构订阅内容需要用户在可见浏览器中完成认证和原生下载。

## 执行流程

1. 读取用户目标、输入文件、Zotero收藏夹和允许的访问范围。
2. 运行 `scripts/normalize_records.py`，统一 DOI、PMCID、arXiv ID、题名和 URL；仅在标题高度匹配时使用 Crossref 补 DOI。
3. 先以 dry run 运行 `scripts/fetch_open_pdfs.py`，检查候选来源和任务规模。
4. 获得用户明确下载请求后，加 `--execute` 获取开放 PDF。
5. 对仍未获得全文且用户拥有正常访问权的记录，运行
   `scripts/prepare_authorized_queue.py`。
6. 让用户选择 `webbridge` 或 `playwright` 后端，并亲自完成机构登录和 CAPTCHA；
   再运行 `scripts/run_authorized_browser.py --execute`，只操作可见的搜索、结果
   和原生 PDF 下载控件。遇到验证码、异常访问或平台警告立即停止。
7. 使用浏览器执行后的队列运行 `scripts/ingest_downloads.py`，验证并归档下载文件。
8. 运行 `scripts/build_zotero_handoff.py`；Zotero MCP 提供兼容工具时，再运行
   `scripts/execute_zotero_handoff.py --execute` 完成查重、导入或附件关联并重新查询验证。
9. 检查开放下载、浏览器执行、PDF 接管、Zotero 写入四段的状态和失败原因。

## 快速命令

Windows 上若 `python` 不可用，优先定位已有解释器；不要假定必须存在 `python3`。

```powershell
python scripts/doctor.py --online --output literature_run/doctor.json
python scripts/normalize_records.py input.ris --output-dir literature_run/normalized
python scripts/fetch_open_pdfs.py literature_run/normalized/records.jsonl `
  --output-dir literature_run/acquisition `
  --email researcher@example.edu
```

确认计划后执行：

```powershell
python scripts/fetch_open_pdfs.py literature_run/normalized/records.jsonl `
  --output-dir literature_run/acquisition `
  --email researcher@example.edu `
  --resume `
  --execute
```

Unpaywall需要联系邮箱；OpenAlex与CORE适配器在配置相应环境变量后启用：

```text
SCHOLARBRIDGE_EMAIL
OPENALEX_API_KEY
CORE_API_KEY
```

不把密钥写入仓库、日志、命令示例或报告。

## 机构订阅与 Zotero

生成浏览器接管队列：

```powershell
python scripts/prepare_authorized_queue.py `
  literature_run/normalized/records.jsonl `
  --output-dir literature_run/authorized
```

### 复用现有 Chrome

用户先在真实 Chrome 完成登录；再使用 Kimi WebBridge 执行有界下载任务：

```powershell
python scripts/run_authorized_browser.py `
  literature_run/authorized/authorized-queue.jsonl `
  --backend webbridge `
  --download-dir "$env:USERPROFILE\Downloads" `
  --output-dir literature_run/browser `
  --max-records 10 `
  --execute
```

### 使用独立持久化 Chrome

不依赖 Kimi WebBridge。首次由用户在专用 Playwright profile 中手动登录：

```powershell
python scripts/prepare_browser_profile.py `
  --profile-dir "$env:USERPROFILE\.scholarbridge\browser-profiles\cnki" `
  --url "https://www.cnki.net/"
```

随后复用该 profile：

```powershell
python scripts/run_authorized_browser.py `
  literature_run/authorized/authorized-queue.jsonl `
  --backend playwright `
  --profile-dir "$env:USERPROFILE\.scholarbridge\browser-profiles\cnki" `
  --download-dir "$env:USERPROFILE\Downloads" `
  --output-dir literature_run/browser `
  --max-records 10 `
  --execute
```

若缺少依赖，运行 `python -m pip install playwright`。后端调用电脑已有的 Chrome，
通常不需要下载额外 Chromium。profile 不得写入项目或分享；纯会话 Cookie 和失效
SSO 仍可能要求重新登录。

未找到控件、需要登录、触发验证码或下载后没有出现 PDF 时，保留相应状态并转人工，
不要反复点击。对浏览器执行结果运行：

```powershell
python scripts/ingest_downloads.py `
  literature_run/browser/authorized-queue.browser.jsonl `
  --download-dir "$env:USERPROFILE\Downloads" `
  --output-dir literature_run/authorized-ingest

python scripts/build_zotero_handoff.py `
  literature_run/authorized-ingest/ingest-manifest.csv `
  --output-dir literature_run/zotero `
  --collection "ScholarBridge"

python scripts/execute_zotero_handoff.py `
  literature_run/zotero/zotero-handoff.jsonl `
  --output-dir literature_run/zotero-executed `
  --url "http://127.0.0.1:23120/mcp" `
  --max-tasks 20 `
  --execute
```

`run_authorized_browser.py` 已实现 `webbridge` 与 `playwright` 两个后端，并用
语义化页面树寻找控件。若页面结构无法可靠识别，保留
`needs-manual-browser-step`，不要猜测选择器。前者复用日常 Chrome，后者复用
ScholarBridge 专用 profile；两者都不是模拟账号登录。

读取 [acquisition-routes.md](references/acquisition-routes.md) 了解各条技术路线、参考仓库、登录态实现及限制。

## 来源选择

按照以下顺序使用：

1. 用户提供的公开 PDF URL。
2. arXiv 与 PMC 明确标识符。
3. Europe PMC 将 DOI 解析到 PMC 开放子集。
4. Unpaywall查找合法开放版本。
5. OpenAlex、CORE 与 DOAJ 补充开放位置。
6. 无开放版本时生成失败记录，不把元数据命中冒充为全文成功。

读取 [open-sources.md](references/open-sources.md) 了解来源能力、密钥、许可与限制。需要判断平台角色时读取 [platform-matrix.md](references/platform-matrix.md)。处理机构订阅、验证码、DRM 或批量限制时读取 [compliance.md](references/compliance.md)。需要比较现有仓库与实现机制时读取 [acquisition-routes.md](references/acquisition-routes.md)。

## Google Scholar

仅把 Google Scholar 用于人工或浏览器辅助发现：

- 接收用户导出的 BibTeX、EndNote、RIS、题名或 DOI。
- 使用“所有版本”和右侧 PDF 链接寻找候选来源。
- 将候选 DOI/题名交回开放来源路由。
- 不实施无人值守抓取、验证码规避或批量翻页。

Google Scholar没有官方批量接口，也不是 PDF 仓库。学校订阅链接标记为 `authorized-subscription`，不能标记为开放获取。

## PDF 成功标准

只有同时满足以下条件才标记 `downloaded`：

- 响应最终解析为 PDF，而不是登录页或验证码 HTML；
- 文件具有 `%PDF-` 头；
- 文件体积达到最低阈值；
- 文件尾包含 `%%EOF`；
- 已计算 SHA-256；
- 记录来源 URL、提供者、许可和版本（可获得时）。

发现相同 SHA-256 时保留一个文件并标记重复。不要覆盖已有文件。

## 失败与降级

- `no_open_pdf`：仅发现元数据或没有开放版本。
- `failed`：候选存在但下载、重定向或 PDF 校验失败。
- `dry_run`：只建立计划，没有下载。
- `browser-download-complete`：浏览器点击后监测到完整 PDF。
- `needs-user-authentication`：必须由用户在真实浏览器完成登录。
- `needs-manual-browser-step`：页面语义不足，不能安全自动选择控件。
- `download-clicked-no-file`：点击后没有监测到完成的 PDF。
- `zotero-complete`：MCP 写入后已重新查询到条目。
- `zotero-write-unverified`：工具调用成功但重新查询未确认结果。
- 403、429、验证码、访问警告或异常登录：立即停止该来源并报告。
- 没有 DOI：保留题名，交给人工或浏览器发现，不编造标识符。
- 只有受限全文：生成浏览器接管或人工处理队列。

## 安全边界

- 不绕过付费墙、验证码、DRM、下载配额或访问控制。
- 不索取或记录用户密码、Cookie、Token；登录态留在用户浏览器或专用本地配置目录。
- 不自动抓取 Google Scholar 搜索结果。
- 不将机构订阅权限解释为无限批量许可。
- 默认拒绝 localhost、内网和私有 IP URL，避免 SSRF；`--allow-private` 只用于受控测试。
- 下载体量应有 `--max-records`、`--max-mb` 与请求间隔限制。
- 大规模文本与数据挖掘优先使用平台官方数据集、快照或 TDM 接口。

## 输出

每次运行保留：

```text
acquisition/
├── pdf/
├── plan.jsonl
├── attempts.jsonl
├── manifest.csv
├── report.md
└── summary.json
```

最终回复必须区分：

- 已成功下载并验证的 PDF；
- 重复文件；
- 只有元数据的记录；
- 没有开放版本的记录；
- 需要用户授权浏览器处理的记录；
- 因平台限制停止的记录。
- 已成功关联进 Zotero 的记录与仅生成交接任务的记录。
- 浏览器或 Zotero 执行器已经实际验证的记录与仅通过模拟服务测试的能力。
