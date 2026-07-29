---
name: scholar-bridge
description: 统一规划并执行授权范围内的学术文献获取工作流。用于处理 DOI、BibTeX、RIS、CSV、数据库导出、学校 WebVPN/CARSI/EZproxy/出版社机构登录、论文批量获取、PDF 核验和失败清单生成。
---

# ScholarBridge 文献桥

ScholarBridge 将文献发现、机构认证、全文获取和 PDF 核验统一成一个可审计流程。

核心流程：

1. 标准化输入文献记录。
2. 提取 DOI 并去重。
3. 判断数据库角色：全文平台、索引平台、认证入口或电子书平台。
4. 优先使用开放获取、官方 API 和合法机构访问。
5. 对需要登录的平台生成浏览器接管队列。
6. 核验 PDF 并生成报告。

原则：
- 不绕过付费墙、验证码、DRM 或访问控制。
- 不要求用户提供账号密码。
- 默认保守执行，遇到 403/429/验证码/封禁立即停止。
- 不把 Scopus、Web of Science、SciFinder 等索引数据库误认为全文仓库。

详细流程见 references/ 文件。
