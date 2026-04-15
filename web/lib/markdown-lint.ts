/**
 * markdown-lint — 渲染 LLM 生成的评审内容前的预检修复层
 *
 * 借鉴 chenglou/pretext 的 "validate-before-render" 思路:不信任 LLM 输出的
 * markdown 格式,在送给 renderer 之前先修一遍最常见的坏掉点:
 *
 *   1. 未闭合的代码块(```python 没有 closing ```) → 自动补上 closing
 *   2. 标题级别跳跃(H1 → H4) → 降级为连续的 H1 → H2
 *   3. 孤立的 [^footnote] 引用但无定义 → 从文本里移除
 *   4. 中文全角 / 半角标点混排 → 只发警告不自动改
 *   5. 尾部无换行 / 连续 3+ 空行 → 归一化
 *
 * 返回 { fixed, warnings },fixed 可以直接喂给 markdown renderer,
 * warnings 给 UI 展示一个折叠的"[格式已自动修正 N 处]"面板。
 *
 * 没用 remark / remark-lint 是因为这些用例 95% 是行级 regex 能搞定的,
 * 装 unified + remark + remark-parse + remark-lint + remark-stringify 会
 * 增加 ~3MB 的 bundle 而收益有限。如果以后要加复杂的 AST 转换(如修表格
 * 列数对齐),再迁移到 remark。
 */

export interface MarkdownLintResult {
  readonly fixed: string;
  readonly warnings: ReadonlyArray<string>;
}

/**
 * 主入口:把输入 markdown 跑过所有 fixer / warner,返回修好后的文本
 * 和所有检测到的警告。纯函数,不会改入参。
 */
export function lintMarkdown(input: string): MarkdownLintResult {
  const warnings: string[] = [];
  let text = input;

  // Fixer 1: 未闭合的代码块
  const fixed1 = fixUnclosedCodeBlocks(text);
  if (fixed1.changed) {
    warnings.push(`自动补上 ${fixed1.closedCount} 个未闭合的代码块`);
    text = fixed1.text;
  }

  // Fixer 2: 标题级别跳跃
  const fixed2 = normalizeHeadingLevels(text);
  if (fixed2.changed) {
    warnings.push(
      `标题级别连续化: ${fixed2.jumps} 处跳跃被降级为相邻层级`,
    );
    text = fixed2.text;
  }

  // Fixer 3: 孤立 footnote 引用
  const fixed3 = removeOrphanFootnotes(text);
  if (fixed3.changed) {
    warnings.push(`移除 ${fixed3.removed} 个无定义的 footnote 引用`);
    text = fixed3.text;
  }

  // Fixer 4: 归一化空行 + 尾部换行
  const fixed4 = normalizeWhitespace(text);
  if (fixed4.changed) {
    text = fixed4.text;
    // 这个是美化,不报 warning
  }

  // Warner 5: 中文全角 / 半角混排(不自动改)
  const punctuationCount = countMixedPunctuation(text);
  if (punctuationCount > 0) {
    warnings.push(
      `检测到 ${punctuationCount} 处中文全角 / 半角标点混排(未自动修正)`,
    );
  }

  return { fixed: text, warnings };
}

// ============================================================
// Fixer 1: 未闭合的代码块
// ============================================================

interface UnclosedCodeResult {
  readonly text: string;
  readonly changed: boolean;
  readonly closedCount: number;
}

function fixUnclosedCodeBlocks(input: string): UnclosedCodeResult {
  // 统计行首的 ```(可带语言标识)。奇数个说明有未闭合。
  const lines = input.split("\n");
  let fenceCount = 0;
  for (const line of lines) {
    if (/^```/.test(line.trim())) {
      fenceCount += 1;
    }
  }
  if (fenceCount % 2 === 0) {
    return { text: input, changed: false, closedCount: 0 };
  }
  // 末尾补一个 closing
  const appended = input.replace(/\n*$/, "\n```\n");
  return { text: appended, changed: true, closedCount: 1 };
}

// ============================================================
// Fixer 2: 标题级别跳跃 (H1 → H4 → 降级到连续层级)
// ============================================================

interface HeadingResult {
  readonly text: string;
  readonly changed: boolean;
  readonly jumps: number;
}

function normalizeHeadingLevels(input: string): HeadingResult {
  const lines = input.split("\n");
  const output: string[] = [];
  let jumps = 0;
  let inFence = false;
  let prevLevel = 0;

  for (const line of lines) {
    // 代码块内的 # 不是标题,保留原样
    if (/^```/.test(line.trim())) {
      inFence = !inFence;
      output.push(line);
      continue;
    }
    if (inFence) {
      output.push(line);
      continue;
    }

    const m = /^(#{1,6})(\s+.+)$/.exec(line);
    if (!m) {
      output.push(line);
      continue;
    }
    const rawLevel = m[1]!.length;
    let level = rawLevel;
    if (prevLevel > 0 && rawLevel > prevLevel + 1) {
      // 跳跃: 降级到 prev + 1
      level = prevLevel + 1;
      jumps += 1;
    }
    prevLevel = level;
    output.push("#".repeat(level) + m[2]!);
  }

  const text = output.join("\n");
  return { text, changed: jumps > 0, jumps };
}

// ============================================================
// Fixer 3: 孤立 footnote 引用
// ============================================================

interface FootnoteResult {
  readonly text: string;
  readonly changed: boolean;
  readonly removed: number;
}

function removeOrphanFootnotes(input: string): FootnoteResult {
  // 收集所有 footnote 定义: [^name]: ...
  const defs = new Set<string>();
  const defRe = /^\[\^([^\]]+)\]:/gm;
  let m;
  while ((m = defRe.exec(input)) !== null) {
    defs.add(m[1]!);
  }

  // 找所有引用: [^name] (不是定义那行)
  let removed = 0;
  const cleaned = input.replace(
    /\[\^([^\]]+)\](?!:)/g,
    (match, name: string) => {
      if (defs.has(name)) return match;
      removed += 1;
      return "";
    },
  );
  return { text: cleaned, changed: removed > 0, removed };
}

// ============================================================
// Fixer 4: 空行归一化 + 尾部换行
// ============================================================

interface WhitespaceResult {
  readonly text: string;
  readonly changed: boolean;
}

function normalizeWhitespace(input: string): WhitespaceResult {
  let text = input;
  // 3+ 连续空行压缩为 2
  text = text.replace(/\n{3,}/g, "\n\n");
  // 尾部恰好一个 \n
  text = text.replace(/\n*$/, "\n");
  return { text, changed: text !== input };
}

// ============================================================
// Warner 5: 中文全角 / 半角混排
// ============================================================

function countMixedPunctuation(input: string): number {
  // 粗糙启发式: 中文字符紧邻半角标点或空格后紧跟全角标点
  // 例如 "这是问题,a still needs" (中文 + 中文逗号 + 空格 + 英文)
  let count = 0;
  // 中文字后紧跟 `,`, `;`, `!`, `?`(半角) — 典型 LLM 混排
  const re = /[\u4e00-\u9fff][,;!?]/g;
  let m;
  while ((m = re.exec(input)) !== null) {
    count += 1;
  }
  return count;
}
