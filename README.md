# AI 商机雷达

AI 商机雷达是一套面向政府政策、公示和通知的本地采集与分析工具。它可以从已配置的公开信源采集公文，保存原文和结构化元数据，再通过兼容 OpenAI 或 Anthropic 协议的大模型识别潜在行业商机，最终生成 Excel 和 JSON 结果。

项目提供本地 Web 控制台，适合在 Windows 上进行信源维护、数据采集、提示词调试和结果查看。

> 当前为开发版本。网页结构变化、访问限制以及模型输出差异都可能影响结果，正式使用前请完成信源授权、数据质量和分析结果复核。

## 主要功能

- 可视化编辑信源：启用状态、列表地址、允许域名、请求间隔等；
- 发起网页采集：支持普通 HTTP、Playwright 浏览器和可见浏览器模式；
- 本地保存公文：原始页面、附件、元数据、规范正文和增量采集状态；
- 查看结构化数据：按批次浏览、分页筛选，并通过弹窗查看详情；
- 选择性分析：可从一个批次中勾选少量公文进行提示词调试；
- 配置分析提示词：支持编辑、保存和恢复系统提示词及用户模板；
- 兼容多种模型服务：OpenAI 兼容接口和 MiniMax Anthropic 接口；
- 查看分析结果：分页查看重点商机和政策观察，下载 Excel 与 JSON 报告；
- 后台任务与日志：查看采集、分析任务状态和具体运行日志；
- 可折叠菜单与分页列表：改善较多数据时的页面操作体验。

## 运行环境

- Windows 10/11
- Python 3.11 或 3.12（64 位）
- 能够访问目标政府网站和所选模型 API 的网络
- 浏览器采集需要 Playwright Chromium

## 快速开始

### 1. 获取源码

```powershell
git clone https://github.com/duoling55/AI-opportunity-radar.git
cd AI-opportunity-radar
```

### 2. 创建虚拟环境

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

如果 PowerShell 禁止执行激活脚本，可以只对当前窗口放开：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 3. 安装依赖

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[browser]"
python -m playwright install chromium
```

需要运行测试或参与开发时：

```powershell
python -m pip install -e ".[dev,browser]"
```

### 4. 启动控制台

```powershell
opportunity-radar-ui
```

浏览器打开：

```text
http://127.0.0.1:8501
```

停止程序时，在启动窗口按 `Ctrl+C`。

## 配置 MIMO

项目通过 OpenAI 兼容协议调用 MIMO。在 PowerShell 中可以这样配置：

```powershell
$env:OPPORTUNITY_RADAR_LLM_PROVIDER="openai"
$env:OPPORTUNITY_RADAR_LLM_API_KEY="替换成你自己的新Key"
$env:OPPORTUNITY_RADAR_LLM_BASE_URL="https://api.xiaomimimo.com/v1"
$env:OPPORTUNITY_RADAR_LLM_MODEL="mimo-v2.5"

opportunity-radar-ui
```

也可以启动控制台后，在“发起分析”页面填写模型配置。页面输入的 API Key 只会传给当前分析子进程，不会写入项目配置、批次、日志或结果文件。

不要把真实 API Key 写入 README、源码、配置文件或 Git 提交。已经在聊天、截图或终端记录中公开过的 Key 应立即作废并重新生成。

## 控制台使用流程

1. 在“信源编辑”中检查或调整目标信源；
2. 在“发起采集”中选择日期、信源和浏览器模式；
3. 在任务列表中查看运行状态和日志；
4. 在“结构化数据”中选择批次并检查公文详情；
5. 在“发起分析”中选择部分或全部公文；
6. 根据需要调整系统提示词和用户提示词模板；
7. 发起分析后，在“查看结果”中查看和下载报告。

用户提示词模板必须保留以下占位符：

```text
{{document_text}}
{{industry_catalog}}
{{business_tags}}
{{json_schema}}
```

它们会在运行时分别替换为政策正文、行业目录、业务标签和输出结构定义。

## 命令行用法

### 只采集，不调用模型

```powershell
opportunity-radar collect `
  --start-date 2026-07-01 `
  --end-date 2026-07-31 `
  --sources miit `
  --browser fallback
```

浏览器模式：

- `off`：只使用普通 HTTP；
- `fallback`：普通 HTTP 无法得到有效内容时再使用浏览器；
- `always`：始终使用 Playwright 浏览器；
- `--headed`：显示浏览器窗口，便于开发调试；
- `--max-pages`：限制列表页访问数量。

### 开发阶段跳过信源资格检查

```powershell
opportunity-radar collect `
  --start-date 2026-07-01 `
  --end-date 2026-07-31 `
  --sources miit `
  --browser always `
  --headed `
  --max-pages 3 `
  --dev-unverified-sources
```

`--dev-unverified-sources` 仅用于本地开发和适配器调试。它不会绕过允许域名、请求间隔、单并发、附件大小、验证码以及 401、403、429 停止规则。
该开关只对 `collect` 生效，不能用于采集与分析一体化的 `run` 命令。

### 分析本地批次

分析最新批次：

```powershell
opportunity-radar analyze-local
```

分析指定批次：

```powershell
opportunity-radar analyze-local `
  --batch "data\normalized\batches\policy-batch-2026-07-30-2.json"
```

采集与本地分析是分开的：采集阶段不需要模型 API Key，分析阶段也不会再次访问政府网站。

## 数据目录

```text
AI-opportunity-radar/
├─ config/
│  ├─ sources.json                 # 信源与采集参数
│  ├─ compliance_sources.json      # 信源资格与访问规则
│  ├─ analysis_prompts.json        # 默认分析提示词
│  └─ business_industries.json     # 业务行业配置
├─ data/
│  ├─ raw/                         # 原始网页、附件和元数据
│  ├─ normalized/batches/          # 结构化公文批次
│  ├─ state/                       # 增量采集和分析状态
│  └─ industry/                    # 行业分类词典
├─ outputs/                        # Excel 和 JSON 分析结果
├─ src/opportunity_radar/          # 项目源码
├─ tests/                          # 自动化测试
└─ pyproject.toml
```

运行数据、输出文件、虚拟环境、日志和压缩包默认由 `.gitignore` 排除，不会随普通的 `git add .` 上传到 GitHub。需要共享演示数据时，建议先脱敏并放入单独的样例目录。

## 信源与访问边界

`config/sources.json` 保存采集适配器配置，`config/compliance_sources.json` 保存信源资格和访问规则。

当前没有任何自动来源具备运行资格；现有信源只能在本地开发模式下调试。正式启用一个来源前，必须同时完成 `config/sources.json` 中的适配器启用配置，以及 `config/compliance_sources.json` 中的核验记录。

生产或常态化运行前，应确认：

- 目标页面和字段允许自动访问与保存；
- 已完成所需的注册、API 申请或书面授权；
- 来源处于启用状态并记录有效的访问频率；
- 不绕过登录、验证码、访问控制或网站明确限制；
- 遇到验证码、401、403、429 等情况时停止并人工检查。

## 开发验证

```powershell
pytest -q
ruff check src tests scripts
```

当前项目包含自动化测试和静态检查配置。修改采集、解析、提示词或导出逻辑后，建议在提交前运行完整测试。

## 常见问题

### `opportunity-radar-ui` 提示模块不存在

确认已经在项目根目录重新安装当前源码：

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[browser]"
```

### 页面打开但分析没有结果

依次检查：

1. 选中的批次是否包含有效公文；
2. 是否勾选了需要分析的公文；
3. API Key、Base URL 和模型名称是否正确；
4. 后台分析日志中是否存在接口错误、超时或 JSON 校验失败；
5. 提示词是否保留四个必需占位符；
6. 政策正文是否确实包含可验证的行业商机证据。

### 页面无法访问

确认命令窗口仍在运行，并打开：

```text
http://127.0.0.1:8501
```

如果 8501 端口已被占用，可以指定其他端口：

```powershell
opportunity-radar-ui --port 8502
```

## 项目状态

本项目仍处于持续开发阶段。建议先在本地、小批量数据和人工复核条件下使用，再逐步扩展信源与自动化范围。
