# Opportunity Radar

Opportunity Radar collects publicly available official policy notices and identifies
potential business opportunities. It uses only checked-in public source configuration
and does not require enterprise data.

## Manual run

Install the project and development dependencies:

```bash
uv sync --extra dev
```

The OpenAI-compatible provider remains the default. Configure it at runtime
through environment variables:

```bash
export OPPORTUNITY_RADAR_LLM_PROVIDER="openai"
export OPPORTUNITY_RADAR_LLM_API_KEY="..."
export OPPORTUNITY_RADAR_LLM_MODEL="..."
export OPPORTUNITY_RADAR_LLM_BASE_URL="https://api.openai.com/v1"
```

To use MiniMax's Anthropic-compatible Messages API, select `minimax`. The base
URL and model shown below are the built-in MiniMax defaults, so only the
provider and API key are required unless an override is needed:

```bash
export OPPORTUNITY_RADAR_LLM_PROVIDER="minimax"
export OPPORTUNITY_RADAR_LLM_API_KEY="..."
export OPPORTUNITY_RADAR_LLM_MODEL="MiniMax-M3"  # optional override
export OPPORTUNITY_RADAR_LLM_BASE_URL="https://api.minimaxi.com/anthropic"  # optional override
```

Credentials are read only from the runtime environment and must not be written
to source, configuration, reports, or generated artifacts.

## 本地可视化控制台

安装项目和浏览器采集依赖：

```powershell
python -m pip install -e ".[dev,browser]"
```

启动本地控制台：

```powershell
opportunity-radar-ui
```

浏览器会打开 `http://localhost:8501`。控制台提供五个入口：

1. **信源编辑**：修改信源启用状态、列表网址、允许域名和请求间隔；
2. **发起采集**：选择日期、信源和浏览器模式，在后台执行采集；
3. **查看结构化数据**：筛选批次、公文元数据和规范正文，下载单篇 JSON 或原始 HTML；
4. **发起分析**：配置 OpenAI 兼容或 MiniMax 接口并后台分析，可强制重新分析完整批次；
5. **查看结果**：筛选重点商机和政策观察，下载 Excel 与 JSON 运行报告。

“发起分析”页面还可以编辑系统提示词和用户提示词模板。用户模板必须保留
`{{document_text}}`、`{{industry_catalog}}`、`{{business_tags}}` 和
`{{json_schema}}` 四个占位符，运行时会分别替换为政策正文、本地行业目录、
业务标签和严格输出结构。提示词可以仅用于本次任务，也可以保存到
`config/analysis_prompts.json` 作为本机默认配置。

结构化数据详情使用弹窗展示；左侧功能菜单可折叠并记住本机偏好。分析页面会先
列出所选批次中的公文，只有勾选的公文会写入临时子批次并发送给模型，适合使用
少量样本反复调整提示词。信源、公文、分析候选、后台任务和结果列表均支持分页及
每页条数调整。

页面中输入的 API Key 只传给当前分析子进程，不会写入信源配置、批次、日志或结果。
关闭控制台后需要重新输入，或者在启动控制台前设置
`OPPORTUNITY_RADAR_LLM_API_KEY` 环境变量。

## 分离采集与本地分析

安装浏览器采集依赖，并下载 Playwright Chromium：

```powershell
python -m pip install -e ".[dev,browser]"
python -m playwright install chromium
```

对于已完成合规核验且已启用的来源，可以先只采集并保存本地批次，不读取
LLM 密钥，也不调用模型：

```powershell
opportunity-radar collect `
  --start-date 2026-06-30 `
  --end-date 2026-07-30 `
  --sources VERIFIED_SOURCE_ID `
  --browser fallback
```

`--browser fallback` 先尝试低频普通 HTTP；静态解析失败或没有发现候选时，
使用 Playwright 渲染页面。`--browser always --headed` 可强制使用可见浏览器，
`--browser off` 可完全禁用浏览器。浏览器最多访问 20 个列表页，可通过
`--max-pages` 调整。浏览器不会处理登录或验证码，遇到 401、403、429、验证码
或跨白名单域名跳转会停止当前来源。

采集批次保存在 `data/normalized/batches/`，原始 HTML 和附件保存在
`data/raw/`，增量采集状态保存在 `data/state/collection.sqlite3`。相同内容不会
在后续采集批次中重复写入。

采集结束后，可以完全从本地批次进行 AI 分析：

```powershell
opportunity-radar analyze-local
```

默认分析最新批次，也可以指定历史批次：

```powershell
opportunity-radar analyze-local --batch data/normalized/batches/policy-batch-2026-07-30.json
```

本地分析仍需要上文的 LLM 环境变量，但不再访问政府网站。分析结果写入
`outputs/`。原有 `opportunity-radar run` 命令继续支持一次性采集和分析。

### 仅用于开发的未核验来源开关

本地开发和适配器调试时，可以显式跳过合规台账资格检查：

```powershell
opportunity-radar collect `
  --start-date 2026-07-01 `
  --end-date 2026-07-30 `
  --sources miit `
  --browser always `
  --headed `
  --max-pages 3 `
  --dev-unverified-sources
```

该开关只对 `collect` 生效，不能用于原有的一次性 `run` 命令。生成的批次会记录
`development_mode=true`，且不会伪造合规审计记录。开发模式仍保留允许域名、单并发、
配置请求间隔、附件大小限制以及验证码、401、403、429 停止规则。上线或常态化运行
时不得使用此开关。

当前没有任何自动来源具备运行资格。`config/sources.json` 中现有适配器没有对应的
已核验合规记录，`config/compliance_sources.json` 中现有记录也仍全部是候选项。
因此，首次实时运行前，运营人员必须同时：

1. 在 `config/sources.json` 登记匹配的来源适配器、稳定的
   `adapter_version`，并明确设置 `enabled=true`；
2. 在 `config/compliance_sources.json` 登记同一 `source_id`，完成条款、注册、
   授权、结构化限频、数据范围和字段许可核验，再设置 `phase=verified` 与
   `enabled=true`。

完成两项登记并通过复核后，使用已核验的来源 ID 运行：

```bash
uv run opportunity-radar run --start-date 2026-06-29 --end-date 2026-07-29 --sources VERIFIED_SOURCE_ID
```

If dates are omitted, the command uses the latest 30-day window. If `--sources` is
omitted, the CLI considers only sources that have both a matching enabled adapter
configuration and a complete, current verified compliance record. Because none exists
now, an omitted source selection exits locally with an eligibility error. Results from
a valid run are written to `outputs/` as one Excel workbook with only the `重点商机` and
`政策观察` business sheets, plus a JSON run report containing the immutable compliance
audit snapshot. Existing workbooks and reports are not overwritten.

## 合规来源开关

`config/compliance_sources.json` 是自动访问的前置台账。候选来源默认
`candidate` 和 `enabled=false`；CLI 会在构造来源适配器、读取模型密钥、构造正文
检索器或发起网络请求前拒绝它们。只有确认开放条款，完成注册/API 或书面授权，
选择明确的数据集或数据范围，确认允许字段，记录结构化官方限频、HTTPS 证据链接、
负责人和 90 天内复核日期，并将来源更新为 `verified` 与 `enabled=true` 后，匹配的
已启用适配器才可运行。

无 API 或授权尚未完成的政策，使用人工导入官方链接或 PDF 的方式处理；不得通过
浏览器指纹、验证码绕过或代理轮换访问来源。

## Verification and safe source checks

Run the complete local verification suite with:

```bash
uv run pytest -q
uv run ruff check src tests scripts
uv run opportunity-radar run --sources state_council_policy_library
```

The final command is a local negative eligibility check against a disabled candidate.
It must exit before reading an LLM key or making a network request. A live smoke check
is permitted only after both required records have been registered and verified; then
follow [the source smoke-check procedure](docs/operations/policy-source-smoke-check.md)
and stop on login, CAPTCHA, 401, 403, or 429 responses.
