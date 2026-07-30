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
   `scripts/prepare_authorized_queue.py`，再按 `browser-handoff.md` 使用可见本地浏览器。
6. 让用户亲自完成机构登录和 CAPTCHA；只用页面上可见的原生下载控制。
7. 将实际下载文件名写入队列后运行 `scripts/ingest_downloads.py`，验证并归档。
8. 运行 `scripts/build_zotero_handoff.py`，再调用可用的 Zotero MCP 工具逐项查重、导入或关联 PDF。
9. 检查开放下载、浏览器下载、Zotero交接三段的 manifest 和失败原因。

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

用户在真实浏览器完成登录并通过数据库原生按钮下载后：

```powershell
python scripts/ingest_downloads.py `
  literature_run/authorized/authorized-queue.jsonl `
  --download-dir "$env:USERPROFILE\Downloads" `
  --output-dir literature_run/authorized-ingest

python scripts/build_zotero_handoff.py `
  literature_run/authorized-ingest/ingest-manifest.csv `
  --output-dir literature_run/zotero `
  --collection "ScholarBridge"
```

优先使用现有 Chrome 会话：Kimi WebBridge或 Playwright MCP浏览器扩展。专用平台适配器可使用可见的 Playwright持久化配置。两者都是复用数据库已建立的浏览器会话，不是模拟账号登录。

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
