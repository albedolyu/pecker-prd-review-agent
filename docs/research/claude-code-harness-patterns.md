# Claude Code 源码逆向研究报告

> 目标：从 Claude Code v2.1.107 的 bundled 源码中提取 harness engineering 模式，
> 指导啄木鸟 PRD 评审系统的架构加固。
>
> 源码位置：`C:\Users\20834\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\cli.js`（17466 行，minified bundle）

---

## 1. API 层分级重试 + 指数退避

**源码位置**：`makeRequest` / `retryRequest` / `shouldRetry` 方法链

**机制**：
- 默认 `maxRetries = 2`，每次请求构建时传入 `retryCount`
- 连接失败（ECONNRESET、timeout）和 HTTP 可重试错误（429、5xx）分开判断
- `shouldRetry(response)` 检查状态码决定是否值得重试，非可重试错误直接抛出
- 每次重试生成独立 `requestLogID`，通过 `retryOfRequestLogID` 建立链式追踪
- timeout 走 `AbortController`，连接超时和响应超时用不同信号区分

**关键代码模式**：
```
if (X instanceof globalThis.Error) {
  let Z = Si(X) || /timed? ?out/i.test(String(X) + ...);
  if (K) return this.retryRequest(z, K, _ ?? $);  // 递减计数
  if (Z) throw new dg;   // TimeoutError
  throw new cZ({cause: X}); // ConnectionError
}
```

**对啄木鸟的启发**：
啄木鸟的 Worker 调 Claude API 目前是单次调用失败即报错。应该实现分层重试：
- **L1（传输层）**：网络/超时/429 自动重试 2 次，指数退避（500ms base, 2x factor, 30s cap）
- **L2（语义层）**：结构化输出 JSON 解析失败时，不重试 API，而是催促 + 文本兜底解析
- 每次重试带 `retryOf` 链，方便 Eval 追踪"第几次重试才成功"的质量指标

---

## 2. 工具调用的 Permission Gate 多层决策链

**源码位置**：`QB1` 函数（核心权限判定）、`checkPermissions` 接口、`decisionReason` 类型

**机制**：
权限判定是一条**有序优先级链**，每层返回 `{allowed, decisionReason}` 或 `passthrough`：

```
1. deny 规则匹配 → 直接拒绝 {type: "rule", rule: matchedRule}
2. allow 规则匹配（写操作）→ 直接放行
3. safetyCheck 安全分类器 → 不安全则拒绝 {type: "safetyCheck", classifierApprovable}
4. 路径白名单检查 → 工作目录内放行
5. sandbox write allowlist → 沙盒内放行
6. allow 规则匹配（通用）→ 放行
7. 以上全未命中 → 默认拒绝
```

`decisionReason` 的 type 枚举：`rule | safetyCheck | mode | classifier | hook | other | sandboxOverride | workingDir`

**关键设计**：`classifierApprovable` 字段允许安全分类器拒绝后，仍然可以通过用户确认解锁。这是"硬拒绝"和"软拒绝"的区分。

**对啄木鸟的启发**：
啄木鸟的苍鹰（meta-reviewer）审核 Worker 结论时，应该实现类似的多层 gate：
- **L1 结构校验**：输出是否符合 schema（等同 deny rule）
- **L2 置信度门控**：Worker confidence < 阈值 → 强制交叉验证（等同 safetyCheck）
- **L3 依据验证**：Side Query 验证引用真实性（等同 classifier）
- **L4 人工兜底**：上述全过但 meta-reviewer 仍存疑 → 标记人工审核（等同 classifierApprovable）
- 每个 gate 返回统一的 `{pass, reason: {type, detail}}`，便于 Eval 追踪

---

## 3. Sub-Agent 拓扑约束 + 工具隔离

**源码位置**：`disallowedTools` 配置、`isSubAgent` 判定、`Y36` 集合（子agent禁用工具名集）

**机制**：
Claude Code 有明确的 agent 类型分层：
- **Explore agent**：`model: "haiku"`, `disallowedTools: [R4, Rk, G4, yK, yP]`（禁用编辑、写入、Agent 嵌套等），`omitClaudeMd: true`
- **Plan agent**：`model: "inherit"`（继承主线程模型），同样禁用编辑/写入工具
- **statusline-setup agent**：`model: "sonnet"`, `tools: ["Read", "Edit"]`（只给 2 个工具）

子 agent 调用被禁用工具时的错误消息：
```
`${toolName} is not available inside subagents. Complete the task 
with the tools provided and return findings to the orchestrator.`
```

**关键约束**：
- `allowedTools` 正向白名单 + `disallowedTools` 负向黑名单双向控制
- 子 agent 不能嵌套调用 Agent 工具（防止递归爆炸）
- `maxTurns` 限制每个 agent 的 API 调用轮次上限

**对啄木鸟的启发**：
直接验证了你的架构原则"禁止 worker 之间直接调用"。可以借鉴的更细粒度设计：
- **正向工具白名单**：`search_agent` 只给 `[search_api, entity_extract]`，`risk_agent` 只给 `[risk_scoring, severity_classify]`
- **负向工具黑名单**：所有 Worker 级别的 agent 禁用 `invoke_agent`（防止 worker 互调）
- **模型分级匹配工具权限**：高价值工具（改写 PRD 建议）只在 Opus worker 可用，Haiku worker 只能做分类标注
- 工具调用失败时的错误消息明确引导回 orchestrator："请把发现返回给协调者"

---

## 4. Prompt Cache 差异检测 + 精细化失效

**源码位置**：`qG4` 函数（cache tracking），`cacheSafeParams` 参数体系

**机制**：
Claude Code 不是简单地缓存/不缓存，而是维护一个 **cache 状态机**：

```javascript
// 缓存状态追踪的字段
{
  systemHash,          // system prompt 的 hash
  toolsHash,           // 工具 schema 的 hash
  cacheControlHash,    // cache_control 指令的 hash
  toolNames,           // 工具名列表
  model,               // 当前模型
  fastMode,            // 是否快速模式
  messageHashes,       // 每条消息的 hash 数组
  perToolHashes,       // 每个工具 schema 的独立 hash
  perBlockHashes,      // system prompt 每个 block 的独立 hash
  perBlockLengths,     // 每个 block 的长度
  callCount,           // API 调用计数
  pendingChanges,      // 待处理的变更集
}
```

变更检测粒度极细，追踪 14 种变更类型：
```
systemPromptChanged, toolSchemasChanged, modelChanged, fastModeChanged,
cacheControlChanged, globalCacheStrategyChanged, betasChanged, autoModeChanged,
overageChanged, cachedMCChanged, effortChanged, extraBodyChanged,
messagesHistoryChanged, firstChangedMessageIndex
```

`sZ4` 函数在需要时剥离 `cache_control` 标记，`cacheSafeParams` 体系确保 fork 出的子请求能正确继承缓存上下文。

**对啄木鸟的启发**：
啄木鸟在批量评审 PRD 时，多个 Worker 共享大量相同的 system prompt + 规则集。可以实现：
- **prompt 指纹缓存**：对 system prompt + 工具集计算 hash，hash 不变时复用 Anthropic 的 prompt caching（`cache_control: {type: "ephemeral"}`）
- **增量失效**：当规则库更新时，只失效 `systemHash` 相关的缓存，工具 schema 缓存保持有效
- **消息级追踪**：`messageHashes` 数组 + `firstChangedMessageIndex` 的设计非常巧妙。在多轮评审中，只有新增的消息需要重新处理

---

## 5. MCP 工具调用的 Elicitation 重试循环

**源码位置**：`XMz` 函数（MCP tool call with retry）

**机制**：
MCP 工具调用有一个独特的重试模式——不是简单重试，而是**交互式重试**：

```javascript
async function XMz({client, tool, args, signal, ...}) {
  for (let M = 0; ; M++) {
    try {
      return await callToolFn({client, tool, args, ...});
    } catch (P) {
      if (!(P instanceof NK) || P.code !== f5.UrlElicitationRequired) throw P;
      if (M >= 3) throw P;  // 最多 3 次 elicitation
      
      // 从错误中提取 elicitation 请求
      let elicitations = P.data.elicitations.filter(valid);
      
      // 尝试 hook 自动处理
      let hookResult = await hookHandler(elicitation, signal);
      if (hookResult?.action !== "accept") {
        // hook 拒绝 → 交给用户
        let userResult = await userPrompt(elicitation, signal);
        if (userResult.action !== "accept") 
          return {content: `elicitation was ${action}ed by the user`};
      }
      // 用户/hook 确认后，循环重试工具调用
    }
  }
}
```

**关键设计**：
- 错误码 `-32042` 专门用于"需要用户干预"的场景
- hook 优先处理（自动化），hook 无法处理才升级到用户交互
- 最多 3 次 elicitation 循环，防止无限弹窗
- AbortSignal 贯穿全链路，用户随时可取消

**对啄木鸟的启发**：
啄木鸟的 Side Query 验证链路可以借鉴这个 "escalation 模式"：
- **L1 自动验证**：Side Query 自动检索并校验依据（等同 hook）
- **L2 规则兜底**：自动验证失败但置信度 > 0.6 → 用预设规则判定（等同 elicitation + hook）
- **L3 人工升级**：连规则都无法判定 → 标记待人工审核，但不阻塞其他 Worker
- 设置 `maxEscalations = 3`，防止单条依据的验证陷入死循环
- 全链路 AbortSignal，orchestrator 可以随时终止某个 Worker 的验证

---

## 6. Agent Fork 机制 + 上下文隔离

**源码位置**：`forkLabel`、`forkContextMessages`、`BP` 函数（fork 执行器）

**机制**：
Claude Code 的子任务不是通过"启动新 agent"实现，而是通过 **fork 主对话上下文** 实现：

```javascript
// 典型 fork 调用
await BP({
  promptMessages: [userMessage],
  cacheSafeParams: {
    ...parentParams,
    forkContextMessages: CQ1(RS8(parentMessages))  // 压缩后的父上下文
  },
  canUseTool: restrictedToolChecker,  // 工具权限可以按 fork 级别限制
  querySource: "compact",             // 标记来源便于计费/追踪
  forkLabel: "reactive-compact",      // fork 标识
  maxTurns: 1,                        // 单轮限制
  maxOutputTokens: Math.min(limit, modelLimit),
  skipTranscript: true,               // 不写入主对话历史
  skipCacheWrite: true                // 不污染缓存
});
```

**关键设计**：
- `forkContextMessages` = 压缩后的父上下文，不是完整历史
- `skipTranscript: true` 确保 fork 的输出不污染主对话
- `maxTurns: 1` 限制 fork 只做单轮推理，不允许多轮自主行动
- `canUseTool` 按 fork 级别定制，away_summary fork 直接 deny 所有工具
- `querySource` 标记便于成本归因（哪个 fork 花了多少 token）

**对啄木鸟的启发**：
啄木鸟的 Worker 可以用类似 fork 模式而非独立 agent 模式：
- **上下文继承**：Worker 继承 orchestrator 的 PRD 上下文（压缩后），而非每次重新输入完整 PRD
- **输出隔离**：Worker 的中间推理不回写到 orchestrator 的上下文，只返回结构化结论
- **单轮约束**：评审 Worker 设 `maxTurns: 1`，强制一次出结果，不允许自主多轮探索
- **成本归因**：通过 `querySource` 标记区分"哪个维度的评审花了多少 token"，为模型分工优化提供数据

---

## 7. Hook 生命周期系统

**源码位置**：`FV` 数组（hook 事件枚举）、`runHooks`、`PreToolUse`/`PostToolUse`

**机制**：
Claude Code 定义了完整的 hook 生命周期事件（28 种）：

```
PreToolUse, PostToolUse, PostToolUseFailure, 
Notification, UserPromptSubmit, 
SessionStart, SessionEnd, Stop, StopFailure, 
SubagentStart, SubagentStop, 
PreCompact, PostCompact, 
PermissionRequest, PermissionDenied, 
Setup, TeammateIdle, 
TaskCreated, TaskCompleted, 
Elicitation, ElicitationResult, 
ConfigChange, WorktreeCreate, WorktreeRemove, 
InstructionsLoaded, CwdChanged, FileChanged
```

Hook 的执行模式：
- Hook 匹配器是字符串：工具名（"Bash"）、管道分隔列表（"Edit|Write"）、或空串匹配全部
- Hook 返回 `permissionRequestResult`，可以 `allow`（放行并修改输入）或 `deny`（拒绝并中断）
- `PreToolUse` hook 失败 = 工具调用被阻止 + agent 收到错误提示
- `PreCompact` hook 可以阻止上下文压缩

**对啄木鸟的启发**：
啄木鸟可以建立类似的 hook 体系来实现"反馈闭环"：
- **PreWorkerInvoke**：Worker 被调用前检查输入质量（PRD 片段是否足够完整）
- **PostWorkerOutput**：Worker 输出后立即做结构校验 + 置信度检查
- **PostVerification**：Side Query 验证后更新规则权重（EMA 算法）
- **OnConflict**：多个 Worker 结论冲突时触发 meta-reviewer 介入
- Hook 的返回值设计 `{action: "allow" | "deny" | "modify", data}` 可以直接复用

---

## 8. 模型分级 + 成本归因体系

**源码位置**：agent 配置中的 `model` 字段、`modelUsage` 统计、`total_cost_usd`

**机制**：
Claude Code 的内置 agent 有明确的模型分级：
- **Explore agent**：`model: "haiku"` — 搜索/探索用最便宜模型
- **Plan agent**：`model: "inherit"` — 继承主线程模型（用户选的）
- **statusline-setup agent**：`model: "sonnet"` — 配置工具用中档模型
- **用户自定义 agent**：可以指定任意模型

成本追踪粒度：
```javascript
modelUsage: {
  [modelName]: {
    inputTokens,
    outputTokens,
    cacheReadInputTokens,
    cacheCreationInputTokens,
    webSearchRequests,
    costUSD,
    contextWindow,
    maxOutputTokens
  }
}
```

还有 token 使用预警机制（`tokenUsage` 组件），当上下文接近窗口限制时弹出警告。

**对啄木鸟的启发**：
直接验证了你的模型分工原则。具体落地：
- **搜索/打标 Worker**：Haiku（低价高频）— 意图识别、实体抽取、关键词匹配
- **主力评审 Worker**：Sonnet（性价比）— 5 个维度的 PRD 评审
- **Meta-reviewer / 深度推理**：Opus（高价低频）— 交叉校验、冲突裁决
- **成本归因**：每个 Worker 返回 `{tokens_used, cost_usd, model_id}`，orchestrator 汇总后输出成本报告
- **预算门控**：设置单次评审的总 token 预算上限，接近时降级模型或跳过低价值校验

---

## 总结：可直接迁移到啄木鸟的 7 个设计模式

| # | 模式 | Claude Code 实现 | 啄木鸟迁移方案 |
|---|------|------------------|----------------|
| 1 | 分层重试 | L1 传输重试 + L2 语义兜底 | API 重试 + JSON 解析兜底 + 催促重试 |
| 2 | Permission Gate 链 | 7 层优先级链 + decisionReason | 结构校验 → 置信度门控 → 依据验证 → 人工兜底 |
| 3 | 工具隔离 | allowedTools + disallowedTools | Worker 白名单工具 + 禁止互调 |
| 4 | 精细缓存失效 | 14 种变更类型 + 增量失效 | prompt 指纹 + 消息级追踪 |
| 5 | Escalation 重试 | hook → 用户确认 → 上限 3 次 | 自动验证 → 规则兜底 → 人工升级（上限 3 次） |
| 6 | Fork 上下文隔离 | 压缩父上下文 + skipTranscript | Worker 继承压缩 PRD + 输出不回写 |
| 7 | 模型分级成本归因 | haiku/sonnet/inherit + modelUsage | Haiku 打标 / Sonnet 评审 / Opus 裁决 + token 预算 |

---

*生成日期：2026-04-15 | 源码版本：@anthropic-ai/claude-code v2.1.107*
