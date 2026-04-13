# Changelog

所有重要变更记录。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [1.1.0] - 2026-04-13

### Web 版（app.py, 950 行）
- Streamlit 网页界面，同事无需安装 CLI，浏览器打开即可评审
- 5 阶段完整交互：上传 → 预检 → 评审 → 确认 → 报告
- Wiki 知识库集成：扫描/读取/写入/锁/索引重建
- 苍鹰交叉校验（标准模式）
- 伯劳简易门禁（4 关检查）
- 依据类型标识（A🟢/B🔵/C🟡）
- 鸟类台词 + 维度吐槽
- Workers 分维度进度展示
- 3 份文档导出（改动报告/交互记录/差异报告）
- 一键保存评审记录到 Wiki

### 安全修复
- [P0] Bash 命令注入：拦截单个 `&`（Windows cmd.exe 分隔符）
- [P1] .env 文件可通过 read_file 读取：新增敏感文件黑名单
- [P1] Session 恢复后重复写入：增量保存计数器从源头同步
- [P2] check_file_permission 尾斜杠 UnboundLocalError
- [P2] 模块导入副作用：load_dotenv/validate_config 移入 _init_config()
- [P2] PRD 只读第一个 .md：改为读取全部并拼接

### 工程优化
- cuckoo_eval.py 拆分为 cuckoo_parser + cuckoo_scorer + cuckoo_eval（995→550 行）
- Phase 2.5 苍鹰代码抽为 run_goshawk_review() 函数
- 彩蛋成就检测从硬编码 if/else 改为数据驱动 lambda
- asyncio Windows 兼容（WindowsSelectorEventLoopPolicy）
- 移除死代码 VALID_PHASES
- 测试增至 73 个（+14）

## [1.0.0] - 2026-04-12

### 鸟类家族
- 啄木鸟（主控）— Phase 0-4 全流程评审协调
- 织布鸟（结构层 Worker）— BMAD V-02~V-06 格式规范性检查
- 猫头鹰（质量层 Worker）— BMAD V-07~V-12 逻辑一致性检查
- 渡鸦（AI Coding 友好度 Worker）— RC-004~RC-008 技术约定检查
- 鸬鹚（数据质量 Worker）— RC-009~RC-010 字段映射检查
- 苍鹰（Advisor）— 交叉校验：误报检测 + 漏报补充 + 冲突调解
- 信鸽（反馈闭环）— 从下游代码采集 4 类信号反哺规则权重
- 杜鹃（Eval）— 对抗性评审质量验证，6 维度加权评分
- 鸮鹦（Wiki Dream）— 知识库健康检查 + 自动修复 + 索引重建
- 伯劳（质量门禁）— 5 关静态检查：报告完整性/编号一致性/Wiki质量/安全扫描/格式规范

### 核心功能
- Phase 0-4 全流程 PRD 评审（知识预检 → 入库 → 并行评审 → 交叉校验 → 交互确认 → 报告）
- 4 Workers 真并行评审（asyncio.gather）
- 依据分类体系（A=内部知识 / B=评审规则 / C=外部参考）
- 知识库持续累积（Obsidian 格式，双向链接）
- Session 断点恢复（JSONL 增量存储 + 重建）
- Prompt Caching + Microcompact 上下文管理
- 飞书通知集成

### 安全
- 文件权限围栏（raw/prd 只读，wiki/output 可写）
- Bash 命令白名单 + 危险操作拦截
- 路径穿越防护（os.sep 边界检查）
- Wiki 并发写入锁（原子文件锁 + 过期清理）
- 安全扫描（API Key / 内网 IP / 明文密码检测）

### 工程
- 59 个测试（51 单元 + 8 集成），GitHub Actions CI
- 统一 API 适配层（全链路重试，零裸调 SDK）
- Token 用量追踪（按模型/按 session 累积统计）
- 结构化日志（logging 模块替代 print）
- 数据类型定义（dataclass，17 个核心类型）
- Python 包结构（pyproject.toml + CLI 入口点）
- Docker 支持（Dockerfile + docker-compose.yml）

### 评测结果
- 杜鹃 Eval: 92.3% PASS（召回 100%，依据 100%，严重度 100%）
- 伯劳门禁: 5/5 PASS
- 信鸽采集: 3,224 条信号（真实代码库验证）
- 4 份 PRD 并行评审: 全部完成，共发现 63 条改进项
