# 前端 UI v8 · 交付报告

> 2026-04-18 · 从 v7 "编辑部散文"切到 v8 "Agent 工作台"气质 · 4 个 Sprint 一次性交付

---

## 背景

### 为什么重做

v7 方向("线稿 · sage 绿 · 编辑部散文")虽然视觉上克制了 v1 内刊印刷感和 v4 水彩手作感,但**定位错了**——把产品做成了"一本可读的杂志",而 PM 打开它是**带任务进来工作**的。两个核心病因:

1. **气质错位** · Fraunces serif italic + sage 绿半透纸卡 + 10 鸟大 hero 插画 + 非 4 倍数"手工感"间距 → 唤起阅读状态而非工作状态
2. **状态反馈弱** · Phase 2"4 worker 并行 + 苍鹰终审"这个核心戏份 UI 几乎没讲;更严重是 `partial_silent` 类 run(worker 空提交)完全不告警,PM 会在不完整的结果上做决策

### v8 方向

**"Agent 工作台 + 工作文档"**,保留 10 只鸟但从"插画作者"变成"工作成员"。

- 日常主产品(Phase 0 / 1 / 3 / 4)参考系:**飞书文档 + GitHub PR review + Notion AI 侧边栏**
- Phase 2 运行中参考系:**Linear + LangSmith trace + Vercel Build Output** · `data-phase2` 局部色温下降
- UI 同时承担 **harness 系统的可观测层 + 反馈信号收集层**

### 双版本共存

- `/review` · **默认 v8**
- `/review?v=7` · legacy 回退入口(保留一个版本的回滚路径)
- v7 代码 100% 保留,`@deprecated-v7` 标记,`globals.css` 内 token/utility 归档但可引用

---

## Sprint 产出

### Sprint 1 · 基础层

| 产出 | 路径 |
|---|---|
| design tokens v8 | `web/app/globals.css` |
| 移除 Fraunces / watercolor / grain | `web/app/layout.tsx` |
| BirdAvatar | `web/components/birds/BirdAvatar.tsx` · 3 尺寸 × 10 只 + 状态灯 + placeholder 态 |
| BirdBadge | `web/components/birds/BirdBadge.tsx` · 职能徽章 + meta 标识 |
| PhaseNav | `web/components/nav/PhaseNav.tsx` · 6 步(含 Phase 1.5 警示三角 + "必经"黄标)+ 回跳 |
| 预览页 | `web/app/v8-preview/page.tsx` |
| v7 @deprecated 标注 | `PhaseHead.tsx` / `primitives.tsx` / `BirdArt.tsx` |

### Sprint 2A · 文档气质主线

| 产出 | 路径 |
|---|---|
| ShortcutHint / KeymapBar | `web/components/misc/ShortcutHint.tsx` · 11px kbd pill |
| EvidenceBlock | `web/components/review/EvidenceBlock.tsx` · 依据引用 + **3 态验证徽章** |
| CommentThread | `web/components/review/CommentThread.tsx` · harness 失败/低置信自动折叠 + 苍鹰三态徽章 + mono meta |
| DocumentView | `web/components/doc/DocumentView.tsx` · PRD 原文 + 3 色高亮 + 锚点联动 |

### Sprint 2B-1 · Phase 0 + 4

| 产出 | 关键视觉 |
|---|---|
| Phase0UploadV8 | 单列 680px 工作表单 · 去 TreeScene / 刊头 / 编号字段 · 保留草稿恢复 + 拖拽 + 粘贴 + mode card |
| Phase4ReportV8 | 元信息卡(workspace/reviewer/mode/run no.)+ 5 栏 stats + 维度分组评审摘要 + **反馈回声 banner**(harness P1-④)+ 3 导出按钮 |
| review 路由切换 | `?v=8` 启用 v8(此时还没合并为默认) |

### Sprint 2B-2 · Phase 1 + 3

| 产出 | 关键视觉 |
|---|---|
| Phase1PrecheckV8 | 3 列汇总卡(strong 绿 / weak 黄 / gap 红)· 自动触发预检 · 0.8s 自动跳 Phase 2 |
| Phase3ConfirmV8 | PM 最高频场景 · 全键盘(**j/k/y/n/e**)· 焦点 accent 左粗边 + 平滑 scroll · 每条 ItemCardV8 带 severity/苍鹰徽章/依据/conf tag/accept/reject/edit · 底部常驻 **KeymapBar** |

### Sprint 3 · Phase 2 调度中心(核心战场)

| 产出 | 关键视觉 |
|---|---|
| AgentStatusCard | worker / meta 两 variant · 4 态 · 进度条 · mono 元数据(model/tokens/t/subs)· 失败 recovery 按钮 · 依赖锚点(底部/顶部) |
| RunConsole | 深色 console · macOS 风格头 · LIVE 呼吸灯 · 时间戳/来源/内容 三列 · 鸟名彩色 |
| RunHealthCheck | **Phase 1.5 必经节点** · session 分类徽章(productive/partial_silent/quota_exhausted/degraded)· consistency 环(SVG)· 5 色失败矩阵 · 5 鸟健康度 · CTA 二选一 |
| Phase2RunningV8 | **`data-phase2` 局部 overlay** · 上层 4 worker 并行 + 下层苍鹰 + **SVG 依赖边 dash-flow 动画** · 底部 RunConsole 合成 · done 后**不自动跳 Phase 3**,切 RunHealthCheck,PM 主动点继续 |

### Sprint 4 · harness 增量

| 产出 | 功能 |
|---|---|
| MissingReportButton | **"我发现一个他们漏掉的问题"**(harness P1-⑦)· modal · 问题/位置/归哪只鸟 · localStorage 草稿 · 提交写 console.log 占位(后端归因库接口待 Sprint 5) |
| Phase3/4 集成 | MissingReportButton 挂在 Phase 3 条目列表底部 + Phase 4 反馈回声 banner 右侧 |
| RunDiff | **baseline vs shadow** 对比组件(harness P1-⑥)· 指标 delta 绿红色 · diff 4 桶(只 A / 只 B / conf 变化 / 一致) |
| /runs/diff 路由 | Run 对比管理页壳 · sample 数据 · 待接 `scripts/shadow_run.py` 产出 |

### 收尾(Sprint 4 后)

- `/review` **默认切 v8**,`?v=7` 为回退入口
- **TopBanner v8 化** · 移除 Fraunces + "2026 春"+ 对话式"你好" · 改 mono 元数据 + reviewer/today/readonly pill + 加 Runs 入口
- v7 设计文件**归档**
  - `design-handoff.md` → `design-handoff-v7.archived.md`
  - `design-system/啄木鸟-pecker/` → `design-system/啄木鸟-pecker-v7.archived/`
  - 两个归档文件顶部加显式 **"已归档"** 声明
- CHANGELOG.md 加 v8 条目

---

## harness 视角增量落地清单

> 这是 v8 相对 v7 最核心的差异 · 不只是"让 PM 用得顺" · 更是 **UI 作为 harness 系统的可观测层 + 反馈信号收集层**

| 级别 | 增量 | 视觉承载 |
|---|---|---|
| **P0①** | 苍鹰是"交叉校验层"不是"第 5 只并列鸟" | Phase 2 上层 4 worker + 下层 1 苍鹰 + SVG dash-flow 依赖边 |
| **P0②** | 依据验证状态显式化 | EvidenceBlock 3 态徽章 `已验证✓ / 验证失败✗ / 未验证⊖` |
| **P0②** | 失败默认折叠 | CommentThread / ItemCardV8 `evidence.verification === failed` 或 `conf < 0.7` 自动折叠,PM 需主动展开才能 accept |
| **P0③** | Session 健康度告警 | **Phase 1.5 必经节点** · productive / partial_silent / quota_exhausted 分类 + 5 色失败矩阵 |
| **P1④** | 反馈闭环的轻量曝光 | Phase 4 "反馈回声"banner(占位文案 · 接 EMA dashboard 留位) |
| **P1⑤** | confidence + model tag | CommentThread / ItemCardV8 mono `conf=0.xx` · 低于 0.7 warn 色强调 |
| **P1⑥** | Run 对比 diff 视图 | `/runs/diff` 管理页 · 左右分栏 · conf 变化 delta 绿红色 |
| **P1⑦** | "为什么没报"反向查询入口 | MissingReportButton modal · localStorage 草稿 |

---

## 盲测建议

### Linear vs Kinfolk 测试

随机截 v8 任一屏给不懂这个项目的朋友,问:"这像 Linear 还是像 Kinfolk?"
- ✅ **必须答:Linear**
- ❌ 如果答 Kinfolk / 杂志 / 博客 → v8 失败

### 产品类型盲测

让非项目内的朋友猜"这是什么产品",应该猜:
- ✅ AI 工具 / 开发者工具 / 协作工具 / 企业工具
- ❌ 博客 / 杂志 / 艺术网站 / 文学刊物

### harness 可读性测

- **Phase 2 截图** 给朋友看,**3 秒内**能说出:"哪只鸟在跑 / 哪只已完成 / 谁失败"
- **Phase 3 截图** 给朋友看,**5 秒内**能说出:"哪条评审意见的依据经过验证 / 哪条未验证"

### 真实流程测

1. 登录 → `/review`(默认 v8)
2. Phase 0 上传 PRD · 拖拽 OK · mode 卡选"精审"
3. Phase 1 预检自动触发 · 3 列汇总
4. Phase 2 调度中心 · 看 4 worker 并行跑 + 依赖边 dash-flow + RunConsole 实时日志
5. Phase 2 结束 · **不直接跳 Phase 3**,进 RunHealthCheck 看 session 分类 + 5 鸟健康 · 主动点"继续"
6. Phase 3 逐条确认 · **完全不用鼠标**完成一次 review(j/k/y/n/e)· 试一下漏报按钮
7. Phase 4 报告 · 下载 md · 保存 wiki · 推飞书 · "反馈回声"banner 应显示

### 降级回退测试

- 访问 `/review?v=7` → 老 v7 UI 应完整工作(不是报错)
- 顶部应有黄色"legacy v7"警示条

---

## 未做 · Sprint 5(v2 预留)

plan 里明确标注"本版预留不实现",留给下一版:

- **Audit trail / replay** · 每次 run 完整审计链可回放(`RunConsole` 给它留了组件路径)
- **"系统健康" tab** · eval 回归 + 历史 run consistency 趋势图 + rule 权重演化(`/runs/diff` 是它的局部)
- **Prompt / Rule 透明度** · 让 PM 看每只鸟当前的 rule 集 + 临时覆盖权重做实验

---

## 核心文件索引

### 设计规范
- `design-system/啄木鸟-pecker-v8/MASTER.md` · v8 设计规范
- `design-handoff-v8.md` · 给 claudedesign 的 briefing
- `design-system/啄木鸟-pecker-v7.archived/` · v7 归档
- `C:\Users\20834\.claude\plans\ui-velvet-koala.md` · 原始 plan

### 代码入口
- `web/app/review/page.tsx` · 双版本切换
- `web/app/runs/diff/page.tsx` · Run 对比
- `web/app/v8-preview/page.tsx` · 组件 gallery
- `web/components/` · 所有 v8 组件
- `web/app/globals.css` · v8 design tokens + v7 @deprecated 归档

### 文档
- `CHANGELOG.md` · v8 版本条目
- `docs/ui-v8-delivery.md` · 本文件
