# 政策来源安全冒烟检查

This procedure is a manual, non-destructive check of a single public official source.
It must never be used to evade a source's access controls.

1. 在 `config/compliance_sources.json` 确认来源为 `verified`、`enabled=true`，
   条款、注册、授权、结构化限频、数据范围和字段许可均已确认，`verified_at` 未空、
   `review_due_at` 未过期且距核验日不超过 90 天，并已保存 HTTPS `evidence_url` 和
   非占位 `owner`。同时确认 `config/sources.json` 中存在同一 `source_id` 的已启用
   适配器和非占位 `adapter_version`。任何一项不满足时停止，不执行命令。
2. Run only one official source and a one-day range.
3. Confirm the source returns public content without login, CAPTCHA, 403, or 429 responses.
4. Confirm output rows preserve source URLs and the saved snapshot is readable.
5. 如来源出现登录、验证码、401、403、429、权限失效或条款不明确，必须同步降级
   两份记录：
   - 在 `config/sources.json` 中将 `enabled` 设为 `false`；
   - 在 `config/compliance_sources.json` 中设置 `phase=candidate`、
     `enabled=false`、`verified_at=null`，将 `review_due_at` 设置为未来复核日期，
     并在 `verification_notes` 记录限制原因。
   两项均完成前不得再次运行该来源，避免复用陈旧批准。
6. Record page structure changes with the source ID, URL, date, and a redacted HTML fixture before changing that adapter.

Stop immediately on a login page, CAPTCHA, 401, 403, or 429 response. Do not bypass
controls, add authentication, alter request headers, automate a browser, or retry the
source. Complete both downgrade edits described above and record the restriction.

Command template (replace the placeholder only after both matching records pass step 1):

```bash
opportunity-radar run --start-date 2026-07-01 --end-date 2026-07-02 --sources VERIFIED_SOURCE_ID
```
