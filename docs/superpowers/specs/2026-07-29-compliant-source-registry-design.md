# 第一批合规来源登记设计

## 1. 目的和范围

为 AI 商机雷达建立第一批政策数据来源的合规登记机制。首批登记对象为：

1. 国务院政策文件库；
2. 浙江·数据开放；
3. 江苏优化营商环境惠企政策服务专区。

本设计只登记来源、核验其使用前提并约束运行行为；不新增任何绕过访问控制的采集逻辑，也不把候选来源直接接入自动运行任务。

## 2. 强制控制规则

- 每个新登记来源初始状态必须为 `candidate`，且 `enabled=false`。
- 任一未确认事项（开放条款、注册、认证、限频、数据集范围、字段许可）均禁止自动采集。
- 仅当来源状态为 `verified`、`enabled=true`，且登记了授权证据和明确限频规则时，运行时才可选中该来源。
- 获取注册资格、API Key、数据集授权或书面许可前，候选来源不得由 CLI 默认来源集合或显式 `--sources` 运行。
- 不得用模拟浏览器指纹、验证码绕过、代理轮换、登录规避或其他方式克服来源限制。

## 3. 登记数据模型

新增机器可读的合规来源清单。每条来源至少包含：

| 字段 | 含义 |
|---|---|
| `source_id` | 稳定来源标识 |
| `display_name` | 官方名称 |
| `phase` | `candidate`、`verified` 或 `retired` |
| `enabled` | 是否允许运行时自动访问 |
| `official_urls` | 官方入口与文档链接 |
| `data_access_mode` | `public_web`、`open_dataset_api`、`restricted_dataset_api` 或 `manual_import` |
| `terms` | 开放范围、用途限制、署名/留痕要求 |
| `registration` | `not_required`、`per_dataset`、`required`、`unknown` |
| `authorization` | `none`、`api_key`、`agreement`、`written_permission`、`unknown` |
| `rate_limit` | 官方限频；未公开时为 `unknown`，不能启用 |
| `available_fields` | 已公开且允许使用的字段清单 |
| `evidence_url` | 支撑本条登记结论的官方链接 |
| `verified_at` | 最近核验日期；候选来源为空 |
| `owner` | 业务或运营责任人；初始为 `unassigned` |
| `review_due_at` | 下次复核日期；候选来源不可为空 |
| `verification_notes` | 未决事项及取得授权所需动作 |

清单不得保存账号密码、Cookie、API Key 或其他凭据；凭据仅由本地环境变量或受控密钥系统保存。

## 4. 首批候选来源登记基线

| 来源 | 初始访问模式 | 开放/授权基线 | 注册与认证 | 限频 | 可用字段 | 启用前条件 |
|---|---|---|---|---|---|---|
| 国务院政策文件库 | `public_web` | 库收录已公开发布的行政法规、规章和行政规范性文件；未确认面向批量自动化的公开 API 条款 | 网页检索未见注册要求；自动化用途待确认 | `unknown` | 标题、发布机构、文号、发布日期、分类、主题、正文、原文链接 | 取得或核验自动化访问许可及限频规则 |
| 浙江·数据开放 | `open_dataset_api` / `restricted_dataset_api` | 平台区分公开与受限数据；受限开放数据按协议使用 | `per_dataset`；接口权限、AppKey 与认证方式待按数据集核验 | `unknown` | 数据集元数据、字段说明、下载/API 地址；业务字段以选定数据集为准 | 选定数据集、完成注册/协议/API 授权并记录限频 |
| 江苏优化营商环境惠企政策服务专区 | `public_web` / `manual_import` | 专区集中发布惠企政策措施；未发现公开批量 API 或自动化使用条款 | 浏览政策页未见注册要求；接口授权待确认 | `unknown` | 标题、发布日期、发布机关、正文、附件、原文链接及页面披露的申报信息 | 取得自动化访问许可与限频；否则仅允许人工导入官方链接/PDF |

官方证据：

- 国务院政策文件库：https://sousuo.www.gov.cn/zcwjk/
- 浙江·数据开放：https://data.zjzwfw.gov.cn/dopServer/
- 浙江受限开放利用协议：https://data.zjzwfw.gov.cn/dopServer/static/agreement/%E6%B5%99%E6%B1%9F%E7%9C%81%E6%95%B0%E6%8D%AE%E5%BC%80%E6%94%BE%E5%B9%B3%E5%8F%B0%E5%8F%97%E9%99%90%E5%BC%80%E6%94%BE%E5%8D%8F%E8%AE%AE.pdf
- 江苏优化营商环境惠企政策服务专区：https://www.jiangsu.gov.cn/col/col87049/index.html

## 5. 运行时判定

来源选择顺序如下：

1. 读取合规来源清单；
2. 拒绝不存在、`candidate`、`retired` 或 `enabled=false` 的来源；
3. 检查 `verified_at`、`review_due_at`、`evidence_url`、`rate_limit`、`authorization` 和 `owner`；
4. 任一必需项缺失、已到复核日期或授权过期时，拒绝运行并写入原因；
5. 仅将通过检查的来源传给既有来源适配器。

人工导入不受网页自动采集限制，但每份输入必须保留原始官方链接或文件、导入人、导入时间和来源说明；仍须通过既有解析、行业校验、质量门禁与 Excel 导出流程。

## 6. 运维与审计

- 运营责任人每次申请平台注册、接口权限或书面授权后更新对应登记项和证据链接。
- 每个 `verified` 来源至少每 90 天复核一次；平台条款、接口或限频变化时应立即降回 `candidate`。
- 运行报告记录参与运行的 `source_id`、核验日期、证据链接与适配器版本。
- 403、401、429、验证码、登录要求、条款不明确或接口权限失效时，来源立即停止，不重试规避。

## 7. 验收标准

1. 三个来源均存在于合规来源清单，且初始均为 `candidate`、`enabled=false`。
2. 默认运行不会访问这三个候选来源。
3. 用户显式指定候选来源时，CLI 给出“未核验/未启用”的明确错误，且不发送网络请求。
4. 登记表中可查到开放/授权、注册、限频、可用字段、证据、负责人和复核日期；未公开事项显式标注 `unknown`。
5. 只有完整填写核验信息并将状态改为 `verified`、`enabled=true` 后，来源才可进入自动采集流程。
