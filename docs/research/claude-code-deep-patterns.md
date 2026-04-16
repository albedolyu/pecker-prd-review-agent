# Claude Code Deep Patterns (Round 3)

> 源码: cli.js v2.1.107 (17466 行)
> 前两轮已覆盖 16 个模式，本轮继续深挖**架构级**新模式

---

## Pattern 17: Deferred Tool Loading (工具懒加载)

### CC 实现

CC 不会在 session 启动时把所有工具的完整 JSON Schema 都塞进 system prompt。它把工具分为两类：

1. **Always-load 工具** — `alwaysLoad: true` 的核心工具（Read, Edit, Bash, Grep 等），schema 始终在 prompt 顶部
2. **Deferred 工具** — MCP 工具、非核心内置工具，只在 prompt 中显示名称，**不包含参数 schema**

关键函数 `isDeferredTool()`:
```
if (q.alwaysLoad === true) return false;   // 核心工具永不延迟
if (q.isMcp === true) return true;          // MCP 工具一律延迟
if (q.name === XJ) return false;            // ToolSearch 工具本身不延迟
return q.shouldDefer === true;              // 其余看 shouldDefer 标记
```

当模型需要调用某个 deferred tool 时，它先调用一个特殊的 `ToolSearch` 工具：
- `"select:Read,Edit,Grep"` — 精确按名字拉取
- `"notebook jupyter"` — 关键词模糊搜索
- `"+slack send"` — 名称必须含 "slack"，其余关键词做排序

ToolSearch 返回完整 `<functions>` 块，之后该工具就可以正常调用。

### 迁移价值: **高**

啄木鸟 PRD 评审系统有 4 个 Worker + 多个工具。初始 prompt 塞了全部工具 schema 会浪费大量 cache_creation_input tokens。

### 迁移建议

```python
# 啄木鸟工具分层策略
ALWAYS_LOAD = {
    "submit_review",      # 每个 Worker 必用
    "read_prd_section",   # 核心读取
    "search_prd",         # 核心搜索
}

DEFERRED = {
    "fetch_competitor_data",   # 只有竞品分析 Worker 用
    "calculate_metrics",       # 只有量化评估 Worker 用
    "generate_diagram",        # 极少用
}

def get_tools_for_worker(worker_type: str, requested_tools: list[str]):
    """Worker 初始只拿 ALWAYS_LOAD，按需通过 tool_search 拉取 DEFERRED"""
    base = [t for t in ALL_TOOLS if t.name in ALWAYS_LOAD]
    on_demand = [t for t in ALL_TOOLS if t.name in requested_tools]
    return base + on_demand
```

---

## Pattern 18: Prompt Cache Break Detection (缓存失效溯源)

### CC 实现

CC 内建了一套精密的 **prompt cache break 诊断系统**，核心是 `qG4()` 和 `KG4()` 两个函数。

**运作机制：**

1. **每次 API 调用前** (`qG4`)：对 system prompt、tools schema、model、betas、effort 等做 hash 快照
2. **每次 API 响应后** (`KG4`)：比较本次 `cache_read_input_tokens` 与上次的值
3. **如果 cache read 下降超过 2000 tokens** → 触发 break 分析

**诊断维度（pendingChanges 对象）：**
- `systemPromptChanged` — system prompt 内容变了
- `toolSchemasChanged` — 工具 schema 变了（具体到哪个工具变了、新增了、删除了）
- `modelChanged` — 模型切换
- `fastModeChanged` — fast mode 开关
- `effortChanged` — effort level 变了
- `betasChanged` — beta features 变了
- `messagesHistoryChanged` — 消息历史被修改（compact 操作）
- `cacheControlChanged` — cache_control 头变了
- `overageChanged` — 超额使用状态变了（TTL 翻转）

**TTL 过期检测：**
```
Jqz = 300000   // 5分钟
ce6 = 3600000  // 1小时

if (timeSinceLastAssistant > 1h) → "possible 1h TTL expiry"
if (timeSinceLastAssistant > 5min) → "possible 5min TTL expiry"
else → "likely server-side"
```

**Diff 生成：** 当检测到 break 时，CC 会生成一个 unified diff 文件保存到 `.claude/cache-break-xxxx.diff`，方便事后分析。

### 迁移价值: **高**

啄木鸟每次评审消耗大量 token，prompt cache 命中率直接影响成本。如果某次修改意外打破了 cache（比如动态注入了不同的 system-reminder），不诊断根本不知道。

### 迁移建议

```python
class PromptCacheMonitor:
    def __init__(self):
        self.prev_cache_read = None
        self.prev_system_hash = None
        self.prev_tools_hash = None

    def on_api_call(self, system: list, tools: list, model: str):
        """调用前快照"""
        self.pending = {
            "system_hash": hash(str(system)),
            "tools_hash": hash(str(tools)),
            "model": model,
        }

    def on_api_response(self, usage: dict):
        """响应后比对"""
        cache_read = usage.get("cache_read_input_tokens", 0)
        if self.prev_cache_read and (self.prev_cache_read - cache_read) > 2000:
            self._diagnose_break(cache_read)
        self.prev_cache_read = cache_read

    def _diagnose_break(self, current_read):
        reasons = []
        if self.pending["system_hash"] != self.prev_system_hash:
            reasons.append("system_prompt_changed")
        if self.pending["tools_hash"] != self.prev_tools_hash:
            reasons.append("tools_schema_changed")
        logger.warning(f"[CACHE BREAK] {', '.join(reasons)}")
```

---

## Pattern 19: Cron Jitter Coordination (调度抖动协调)

### CC 实现

CC 的定时任务系统（scheduled tasks + loop wakeup）内建了**抖动算法**，防止多个 agent 同时触发 API 调用造成 rate limit 拥堵。

**核心配置（`ZF` 对象）：**
```javascript
ZF = {
    recurringFrac: 0.5,        // 重复任务最大抖动比例：间隔的 50%
    recurringCapMs: 1800000,   // 重复任务抖动上限：30 分钟
    oneShotMaxMs: 90000,       // 一次性任务最大提前量：90 秒
    oneShotFloorMs: 0,         // 一次性任务最小提前量
    oneShotMinuteMod: 30,      // 整 30 分钟的一次性任务才抖动
    recurringMaxAgeMs: 604800000,  // 重复任务最大存活：7 天
    cacheLeadMs: 15000,        // Cache 预热窗口：15 秒
}
```

**抖动计算 `TU1()`：**
```
对于重复任务：
  jitter = CZ4(taskId) * recurringFrac * interval
  jitter = min(jitter, recurringCapMs)
  return scheduledTime + jitter

CZ4(taskId) 是确定性的：取 taskId 前 8 字节 hex 转 [0,1) 浮点数
→ 同一个 task 每次抖动量一致，不同 task 自然散开
```

**Cache 预热：** 如果抖动后的时间恰好在 Anthropic prompt cache 5 分钟窗口边界，CC 会把执行时间**提前到 cache 有效期内**，避免 cache miss：
```
if (cacheLeadMs > 0 && interval >= 5min)
    while (target - now > interval - cacheLeadMs)
        target -= 60s   // 往前挪一分钟，直到落在 cache 窗口内
```

### 迁移价值: **中**

啄木鸟目前是单 session 串行，但未来如果做批量评审（多篇 PRD 并行）或定时巡检，需要这个。

### 迁移建议

```python
import hashlib

def deterministic_jitter(task_id: str, interval_ms: int, max_frac=0.5, cap_ms=1800000):
    """确定性抖动：同一 task 每次抖动一致，不同 task 自然散开"""
    h = int(hashlib.md5(task_id.encode()).hexdigest()[:8], 16)
    frac = h / 0xFFFFFFFF
    jitter = frac * max_frac * interval_ms
    return min(jitter, cap_ms)
```

---

## Pattern 20: Effort-Aware Prompt Adaptation (推理力度自适应)

### CC 实现

CC 不是简单地区分 opus/sonnet/haiku，而是有一个 **effort level** 机制。在 prompt cache 监控中可以看到：

```javascript
effortValue: X === void 0 ? "" : String(X)  // effort 作为 cache key 的一部分
```

**Effort 变化会导致 cache break：**
```javascript
if (J.effortChanged)
    M.push(`effort changed (${J.prevEffortValue || "default"} → ${J.newEffortValue || "default"})`);
```

**Overage 状态感知：**
CC 检测用户是否处于超额使用状态（`isUsingOverage`），并据此调整 cache TTL 策略：
```javascript
if (J.overageChanged)
    M.push("overage state changed (TTL flip expected)");
```

超额状态下 CC 可能切换 cache 策略（从长 TTL 切到短 TTL），这也解释了为什么有的用户在接近配额时感觉响应变慢。

**与模型无关的 fast mode：**
CC 还有一个 `fastMode` 开关，独立于模型选择。fast mode 开/关会改变 prompt 结构，影响 cache。

### 迁移价值: **中**

啄木鸟可以为不同阶段的 Worker 设置不同 effort level——初筛 Worker 用低 effort（快速过滤），深度分析 Worker 用高 effort。

### 迁移建议

```python
EFFORT_CONFIG = {
    "triage_worker": {"effort": "low", "model": "haiku"},       # 初筛：快
    "analysis_worker": {"effort": "medium", "model": "sonnet"},  # 分析：平衡
    "meta_reviewer": {"effort": "high", "model": "opus"},        # 审核：深
}

def get_api_params(worker_type: str) -> dict:
    config = EFFORT_CONFIG[worker_type]
    params = {"model": config["model"]}
    if config["effort"] == "low":
        params["max_tokens"] = 2048
    elif config["effort"] == "high":
        params["max_tokens"] = 16000
        # 未来 API 支持 effort 参数时直接传
    return params
```

---

## Pattern 21: Session Event Sourcing (会话事件溯源)

### CC 实现

CC 的 session 持久化不是简单的 "保存最终状态"，而是**事件溯源（Event Sourcing）**模式：

**写入路径：**
```javascript
async appendEventsToFile(q, K) {
    if (K.length === 0) return;
    await O74(Aa6(), { recursive: true });  // 确保目录存在
    let _ = K.map((z) => g6(z)).join('\n') + '\n';
    await lV_(q, _, "utf8");  // append 追加写入
}
```

每条事件是一个 JSON 行（JSONL 格式），追加到会话文件。关键点：
- **追加写入**（append），不是覆写 → 防 crash 数据丢失
- 每个事件带**时间戳**和**类型**
- 目录结构：`.claude/projects/<project_hash>/sessions/`

**恢复机制：**
CC 支持 `--resume`/`--continue` 从历史 session 继续。恢复时：
1. 读取 JSONL 事件文件
2. 重放事件重建对话状态
3. 注入 compact summary（如果有的话）

**Compact 集成：**
Context 超限时，CC 执行 compact → 生成 summary → 作为新 session 的起点，同时保留**原始完整 transcript 的引用路径**：
```
If you need specific details from before compaction,
read the full transcript at: ${_}
```

### 迁移价值: **高**

啄木鸟评审一篇大 PRD 可能耗时很长。如果中途 crash（网络断、进程被杀），事件溯源可以恢复到最后一个成功步骤，而不是从头重来。

### 迁移建议

```python
import json
from pathlib import Path

class EventStore:
    def __init__(self, session_id: str):
        self.path = Path(f".woodpecker/sessions/{session_id}.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event_type: str, data: dict):
        event = {
            "ts": datetime.now().isoformat(),
            "type": event_type,
            **data
        }
        with open(self.path, "a") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def replay(self) -> list[dict]:
        """重放事件恢复状态"""
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text().strip().split("\n"):
            if line:
                events.append(json.loads(line))
        return events

    def get_last_checkpoint(self) -> dict | None:
        """找最后一个 checkpoint 事件，用于 crash recovery"""
        events = self.replay()
        for e in reversed(events):
            if e["type"] == "checkpoint":
                return e
        return None
```

---

## Pattern 22: Conversation Compact with Transcript Preservation (对话压缩 + 原文保留)

### CC 实现

Round 2 提到了 AutoCompact，但 Round 3 发现了一个更深层的机制——**Compact 后保留原始 transcript 引用**。

CC 的 compact 不是简单地 "丢掉旧消息"，而是：

1. **生成 structured summary**（用独立的 LLM 调用）
2. **将完整 transcript 写入磁盘**（事件文件）
3. **在 summary 中嵌入 transcript 路径**：
```
If you need specific details from before compaction
(like exact code snippets, error messages, or content you generated),
read the full transcript at: ${transcriptPath}
```
4. **保留最近 N 条消息原文**（`Recent messages are preserved verbatim`）

**Summary 生成 prompt 的结构化要求：**
```
1. Analyze the recent messages chronologically:
   - The user's explicit requests and intents
   - Your approach to addressing the user's requests
   - Key decisions, technical concepts and code patterns
   - Specific details like:
     - file names
     - full code snippets
     - function signatures
     - file edits
```

**Resume 时的行为约束：**
```
Continue the conversation from where it left off without asking any further questions.
Resume directly — do not acknowledge the summary, do not recap what was happening,
do not preface with "I'll continue" or similar.
Pick up the last task as if the break never happened.
```

### 迁移价值: **高**

啄木鸟评审大型 PRD 时 context 必然超限。但评审结论需要引用 PRD 原文作为依据，不能丢。

### 迁移建议

```python
class CompactManager:
    def compact(self, messages: list, session_id: str) -> dict:
        # 1. 保存完整 transcript
        transcript_path = f".woodpecker/transcripts/{session_id}.jsonl"
        self._save_transcript(messages, transcript_path)

        # 2. 生成 summary（用 haiku 降本）
        summary = self._generate_summary(messages)

        # 3. 保留最近 3 条消息原文
        recent = messages[-3:]

        return {
            "summary": summary,
            "transcript_ref": transcript_path,
            "recent_messages": recent,
            "resume_instruction": (
                "继续评审，从上次中断处接续。"
                f"如需查看之前的详细内容，读取: {transcript_path}"
            )
        }
```

---

## Pattern 23: Pinned Edit State (编辑状态钉选)

### CC 实现

CC 有一个 `pinnedEdits` 机制，用于在 context compact 时保留**关键的文件编辑操作**。

```javascript
function wG4() {
    if (!qL6) return [];
    return qL6.pinnedEdits;
}

function $G4(q, K) {
    if (qL6)
        qL6.pinnedEdits.push({ userMessageIndex: q, block: K });
}
```

当 compact 发生时：
1. 普通的 tool_result 会被 summary 替代
2. **但 pinnedEdits 中的编辑操作会被完整保留**
3. 每个 pinned edit 记录了 `userMessageIndex`（关联到用户的第几条消息）和完整的 `block`

这确保了模型在 compact 后仍然知道**哪些文件做了什么修改**，不会重复编辑或遗漏后续修改。

还有一个 `sd()` (reset) 函数在 compact 完成后清理 pinned state：
```javascript
function sd() {
    if (qL6 && AG4) AG4.resetCachedMCState(qL6);
    IU1 = null;
}
```

**Core tool set（不走 deferred 的工具）：**
```javascript
uWw = new Set([Bq, ...aj6, t5, z_, bh, JH, G4, yK])
// 即: Read, PowerShell/Shell, Grep, Glob, Edit, WebFetch, Write, ...
```

### 迁移价值: **中**

啄木鸟不做文件编辑，但有类似需求：评审过程中的**关键发现**（如严重缺陷）应该被 pin 住，compact 后不丢失。

### 迁移建议

```python
class PinnedFindings:
    """评审过程中的关键发现，compact 时保留"""
    def __init__(self):
        self.pinned = []

    def pin(self, finding: dict, worker_step: int):
        self.pinned.append({
            "step": worker_step,
            "severity": finding["severity"],
            "content": finding["content"],
        })

    def get_for_compact(self) -> list:
        """只保留 HIGH 和 CRITICAL 的发现"""
        return [f for f in self.pinned if f["severity"] in ("high", "critical")]

    def reset(self):
        self.pinned = []
```

---

## Pattern 24: Collapsed Content Format Modes (内容折叠格式模式)

### CC 实现

CC 的对话内容有多种**展示/传输格式**，关键发现是 `collapsed_read_search` 模式：

```javascript
case "collapsed_read_search":
    return q.messages.flatMap((K) =>
        K.type === "user" ? [ld1(K)] :
        K.type === "grouped_tool_use" ? K.results.map(ld1) : []
    ).filter(Boolean).join('\n\n');
```

这个模式会：
1. **只提取 tool_result 的文本内容**
2. **忽略 tool_use 的输入参数**（用户不需要看模型发了什么 tool 调用）
3. **把多个 grouped_tool_use 的结果拍平合并**

辅助函数 `ld1` 做了 content 提取：
```javascript
function ld1(q) {
    let K = q.message.content[0];
    if (K?.type !== "tool_result") return "";
    let _ = K.content;
    if (typeof _ === "string") return _;
    if (!_) return "";
    return _.flatMap((z) => z.type === "text" ? [z.text] : []).join('\n');
}
```

**配合 output truncation：**
CC 还有一个 `vV4` 函数做"上半部分展示 + 折叠行计数"：
- 只显示前 N 行（`gL6 = 3` 行）
- 超出部分显示 `... +X lines`
- 可选提示 "按快捷键展开"

### 迁移价值: **中**

啄木鸟的 meta-reviewer 需要审阅 4 个 Worker 的输出。如果原样传递，token 太多。用 collapsed 模式只传结论部分，大幅省 token。

### 迁移建议

```python
def collapse_worker_output(worker_result: dict) -> str:
    """折叠 Worker 输出，只保留关键结论"""
    findings = worker_result.get("findings", [])
    collapsed = []
    for f in findings:
        # 只保留 severity + 一行摘要，不要完整 evidence
        collapsed.append(f"[{f['severity']}] {f['title']}: {f['summary'][:200]}")
    return "\n".join(collapsed)

def prepare_for_meta_reviewer(all_worker_results: list[dict]) -> str:
    """Meta-reviewer 只看折叠版本"""
    sections = []
    for wr in all_worker_results:
        sections.append(f"## {wr['worker_type']}\n{collapse_worker_output(wr)}")
    return "\n\n".join(sections)
```

---

## 模式总览与优先级

| # | 模式 | 迁移价值 | 实现复杂度 | 推荐阶段 |
|---|------|----------|-----------|---------|
| 17 | Deferred Tool Loading | 高 | 低 | Phase 1 |
| 18 | Prompt Cache Break Detection | 高 | 中 | Phase 1 |
| 19 | Cron Jitter Coordination | 中 | 低 | Phase 3 |
| 20 | Effort-Aware Prompt Adaptation | 中 | 低 | Phase 2 |
| 21 | Session Event Sourcing | 高 | 中 | Phase 1 |
| 22 | Compact + Transcript Preservation | 高 | 中 | Phase 1 |
| 23 | Pinned Edit State | 中 | 低 | Phase 2 |
| 24 | Collapsed Content Format | 中 | 低 | Phase 2 |

**Phase 1 优先做** (17, 18, 21, 22)：直接影响成本和可靠性
- Deferred Tool Loading → 减少 cache_creation tokens
- Cache Break Detection → 发现意外 cache miss
- Event Sourcing → crash recovery
- Compact + Transcript → 长评审不丢上下文

**Phase 2 次优先** (20, 23, 24)：提升效率
- Effort Adaptation → 不同 Worker 用不同"力度"
- Pinned Findings → compact 保留关键发现
- Collapsed Content → meta-reviewer 省 token

**Phase 3 最后** (19)：多实例并行时才需要
- Cron Jitter → 批量评审时防 rate limit

---

## 与前两轮的关联

| Round 3 新模式 | 与 Round 1/2 已有模式的关系 |
|---------------|--------------------------|
| Deferred Tool Loading | 补充 R1 Sub-Agent 工具隔离：不只是隔离，还要懒加载 |
| Cache Break Detection | 深化 R1 Prompt Cache 差异检测：从"检测变化"升级到"诊断原因" |
| Cron Jitter | 独立新模式：R2 Circuit Breaker 管单 agent，这个管跨 agent 调度 |
| Effort Adaptation | 深化 R1 模型分级成本归因：不只是模型分级，还有 effort 分级 |
| Event Sourcing | 深化 R2 Agent Memory：Memory 是知识持久化，这是操作持久化 |
| Compact + Transcript | 深化 R2 Context AutoCompact：从"触发压缩"到"压缩后怎么保留引用" |
| Pinned Edit State | 补充 R2 Context AutoCompact：compact 时的选择性保留机制 |
| Collapsed Content | 补充 R2 Tool Result 截断：不是截断，是按格式模式做智能折叠 |
