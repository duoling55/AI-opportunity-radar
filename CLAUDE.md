# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

AI 商机雷达是一个面向政府政策、公示和通知的本地采集与分析工具。它从公开信源采集公文，使用大模型识别潜在行业商机，生成 Excel 和 JSON 结果。提供本地 Web 控制台用于信源维护、数据采集、提示词调试和结果查看。

## 快速开始命令

```powershell
# 激活虚拟环境
.\.venv\Scripts\Activate.ps1

# 安装依赖（开发模式）
python -m pip install -e ".[dev,browser]"

# 安装 Playwright 浏览器
python -m playwright install chromium

# 启动 Web 控制台
opportunity-radar-ui

# 命令行采集
opportunity-radar collect --start-date 2026-07-01 --end-date 2026-07-31 --sources miit --browser fallback

# 命令行分析本地批次
opportunity-radar analyze-local --batch "data\normalized\batches\policy-batch-2026-07-30-2.json"

# 运行测试
pytest -q

# 静态检查
ruff check src tests scripts
```

## 架构概览

### 核心模块

```
src/opportunity_radar/
├── cli.py              # 命令行入口 (collect, analyze-local, run)
├── ui_server.py        # Web 控制台 (Gradio, 端口 8501)
├── pipeline.py         # 采集→解析→分析→导出主流程
├── collection.py       # 批次采集逻辑
├── browser.py          # Playwright 浏览器采集
├── http.py             # HTTP 客户端
├── config.py           # 配置加载 (sources.json)
├── compliance.py       # 信源资格与访问规则校验
├── models.py           # 数据模型 (PolicyDocument, PolicyAnalysis, IndustryOpportunity)
├── state.py            # 增量采集状态存储 (SQLite)
├── normalization.py    # 正文规范化与跨源去重键
│
├── sources/            # 信源适配器
│   ├── registry.py     # 适配器注册表 (miit, ndrc, zhejiang_*, jiangsu_*)
│   ├── base.py         # 源接口定义
│   └── *.py            # 各信源实现
│
├── parsing/            # 文档解析
│   ├── html.py         # HTML 解析与正文提取
│   ├── attachments.py  # 附件处理 (PDF, DOCX)
│   └── snapshot.py     # 页面快照保存
│
├── analysis/           # LLM 分析
│   ├── client.py       # OpenAI/MiniMax 客户端
│   └── prompts.py      # 系统/用户提示词
│
├── quality/            # 质量评分
│   ├── scoring.py      # 商机评分逻辑
│   ├── scripts.py      # 推荐话术生成
│   └── validation.py   # 分析结果校验
│
└── export/             # 结果导出
    ├── excel.py        # Excel 工作簿导出
    └── report.py       # 运行报告生成
```

### 数据流

1. **采集阶段** (`collect`): CLI → `pipeline.run_pipeline` → `collection.collect_batch` → 信源适配器 → `browser.py`/`http.py` → `parsing/html.py` → 保存至 `data/raw/` 和 `data/normalized/batches/`

2. **分析阶段** (`analyze-local`): CLI → `pipeline.run_pipeline` → `analysis/client.py` 调用 LLM → `quality/scoring.py` 评分 → `export/excel.py` 导出至 `outputs/`

3. **一体化运行** (`run`): 采集 + 分析连续执行

### 关键数据模型

- `PolicyCandidate`: 采集候选项 (标题、URL、发布日期)
- `PolicyDocument`: 规范化公文 (含正文、元数据、附件 URL)
- `PolicyAnalysis`: LLM 分析结果 (摘要、支持方向、商机列表)
- `IndustryOpportunity`: 结构化商机 (行业代码、业务标签、置信度、证据)
- `QualityResult`: 质量评分 (等级、分数、理由)

### 信源适配器

信源适配器实现 `GenericHtmlSource` 接口，负责:
- `discover(start, end)`: 发现指定日期范围内的政策候选项
- 各适配器位于 `sources/` 目录，通过 `registry.py` 注册

当前支持的信源：`miit`, `ndrc`, `zhejiang_huiqi`, `zhejiang_eit`, `jiangsu_government`, `jiangsu_eit`

### 合规性机制

`config/compliance_sources.json` 定义信源资格和访问规则，包括:
- 允许域名、请求间隔、单并发限制
- 停止规则 (验证码、401/403/429)
- 附件大小限制

开发模式使用 `--dev-unverified-sources` 绕过资格检查，但不会绕过上述访问边界。

### 提示词系统

分析提示词存储在 `config/analysis_prompts.json`，包含:
- 系统提示词 (`SYSTEM_PROMPT`)
- 用户提示词模板 (必须保留 `{{document_text}}`, `{{industry_catalog}}`, `{{business_tags}}`, `{{json_schema}}` 四个占位符)

支持通过环境变量 `OPPORTUNITY_RADAR_SYSTEM_PROMPT` 和 `OPPORTUNITY_RADAR_USER_PROMPT_TEMPLATE` 覆盖默认提示词。

## 配置说明

### 环境配置

项目通过 OpenAI 兼容协议调用 LLM，配置方式:

```powershell
# MIMO 配置示例
$env:OPPORTUNITY_RADAR_LLM_PROVIDER="openai"
$env:OPPORTUNITY_RADAR_LLM_API_KEY="<your-key>"
$env:OPPORTUNITY_RADAR_LLM_BASE_URL="https://api.xiaomimimo.com/v1"
$env:OPPORTUNITY_RADAR_LLM_MODEL="mimo-v2.5"

# MiniMax 配置示例
$env:OPPORTUNITY_RADAR_LLM_PROVIDER="minimax"
$env:OPPORTUNITY_RADAR_LLM_API_KEY="<your-key>"
$env:OPPORTUNITY_RADAR_LLM_BASE_URL="https://api.minimaxi.com/anthropic"
$env:OPPORTUNITY_RADAR_LLM_MODEL="MiniMax-M3"
```

### 配置文件

- `config/sources.json`: 信源适配器配置 (启用状态、列表地址、允许域名、请求间隔)
- `config/compliance_sources.json`: 信源资格与访问规则
- `config/analysis_prompts.json`: 分析提示词
- `config/business_industries.json`: 业务行业标签配置

## 测试说明

测试位于 `tests/` 目录，使用 pytest:

```powershell
# 运行全部测试
pytest -q

# 运行单个测试文件
pytest tests/test_pipeline.py -v

# 运行带标记的测试
pytest -m "slow"
```

测试夹具 (`tests/conftest.py`) 提供:
- `fixture_sources`: 本地模拟信源
- `fixture_retriever`: 模拟文档检索
- `fixture_analyzer`: 模拟分析器

## 开发注意事项

1. **新增信源适配器**: 在 `sources/` 目录创建新模块，继承 `GenericHtmlSource`，并在 `registry.py` 中注册

2. **浏览器采集调试**: 使用 `--browser always --headed` 显示浏览器窗口

3. **API Key 安全**: 不要将真实 API Key 写入 README、源码、配置文件或 Git 提交。已在公开渠道泄露的 Key 应立即作废

4. **增量采集**: 状态存储在 `data/state/radar.sqlite3`，避免重复采集相同内容

5. **数据目录**:
   - `data/raw/`: 原始网页、附件和元数据
   - `data/normalized/batches/`: 结构化公文批次
   - `data/state/`: 增量采集和分析状态
   - `data/industry/`: 行业分类词典
   - `outputs/`: Excel 和 JSON 分析结果
