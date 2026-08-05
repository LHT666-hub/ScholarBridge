# 平台验证分级与实测记录

ScholarBridge 不再用一个百分比混合描述代码完成度和数据库覆盖度。每个平台按
以下五级独立验收：

1. **L1 页面可读**：真实网页可打开，语义树可识别；
2. **L2 检索可执行**：能填写关键词并到达结果页；
3. **L3 授权态可确认**：用户在本地完成机构或个人登录，系统能确认访问状态；
4. **L4 PDF 可下载**：从可见的原生控件捕获到完整 PDF，并通过文件校验；
5. **L5 Zotero 闭环**：PDF 与题录去重后成功关联或导入 Zotero，并回查确认。

L1 或 L2 通过不代表拥有订阅权限，也不代表 PDF 下载已经跑通。

## 2026-08-05 本机网络实测

| 平台 | 定位 | 本轮达到 | 结果 | 后端建议 |
|---|---|---:|---|---|
| 万方 | 全文平台 | L2 | 主页和检索控件可识别；“人工智能素养”进入结果页 | Playwright；登录复杂时 WebBridge |
| 维普 | 全文平台 | L2 | 主页和检索控件可识别；慢跳转后进入结果页 | Playwright；登录复杂时 WebBridge |
| ScienceDirect | 出版社全文平台 | L2 | 可提交英文关键词并得到带查询条件的页面 | Playwright；机构登录后再验 L3-L5 |
| IEEE Xplore | 出版社全文平台 | L2 | 可提交英文关键词并进入 Search Results | Playwright；机构登录后再验 L3-L5 |
| Web of Science | 授权索引 | L1 | 本机重定向到 Clarivate 登录页 | WebBridge；用于发现/导出，不当作 PDF 主机 |
| Scopus | 授权索引 | L1 | 访客首页可读，文献检索依赖授权 | WebBridge 或 Playwright；导出 DOI 后再路由 |
| CNKI | 全文平台 | 未达 L1 | 本机访问 `kns.cnki.net` 出现证书域名错误 | 先用真实 Chrome/机构入口排查网络与证书 |
| Springer Nature | 出版社全文平台 | 未达 L1 | 独立浏览器收到 HTTP 406 | 优先复用日常 Chrome 的 WebBridge |
| Wiley | 出版社全文平台 | 未达 L1 | Cloudflare challenge / HTTP 403 | WebBridge + 用户人工处理验证 |

以上是环境相关的现场结果，不是对平台永久可用性的承诺。真正的闭源全文验收仍需
用户自己的机构权限、合法下载范围和一次人工认证。账号密码、Cookie 和 Token 不写入
项目；Playwright 登录态只保存在用户指定的本地 profile 中。

本轮也启动了 Kimi WebBridge 守护进程，但 Chrome 扩展返回
`no extension connected`，所以没有把 CNKI、Springer 或 Wiley 的 WebBridge 路线
标记为通过。Zotero Desktop 的 `23119` Connector 与 `23120` MCP 均已真实连通；
当前 MCP 版本 1.8.6 有 26 个读取工具但没有 PDF 写入工具，故新增 Connector 写入
路线，且不向用户真实文库写入测试条目。

## 复现命令

只探测页面和控件：

```powershell
python scripts/probe_authorized_platforms.py `
  --output-dir literature_run/platform-probe `
  --platform wanfang --platform cqvip --platform science-direct --platform ieee
```

提交一个检索词，但不打开结果、不下载：

```powershell
python scripts/probe_authorized_platforms.py `
  --output-dir literature_run/wanfang-probe `
  --platform wanfang `
  --query "人工智能素养"
```

报告会明确声明：`page-readable` 和 `search-page-readable` 只证明相应层级，不能
冒充 L4 或 L5。
