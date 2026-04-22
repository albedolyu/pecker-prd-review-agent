// 啄木鸟 PRD 评审 Agent 演示 PPT 生成器
// 15 分钟会议版 · Midnight Executive 配色

const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.3 x 7.5
pres.author = "PM";
pres.title = "啄木鸟 PRD 评审 Agent";

// ===== 色板 =====
const C = {
  navy: "1E2761",
  navyDeep: "0F1840",
  ice: "CADCFC",
  gold: "F4B942",
  white: "FFFFFF",
  muted: "64748B",
  line: "E2E8F0",
  dark: "0B1424",
  success: "10B981",
  warn: "F59E0B",
};

// ===== 字体 =====
const F = {
  title: "微软雅黑",
  body: "微软雅黑",
  num: "Arial Black",
};

// ===== 通用工具 =====
function addPageNum(slide, n, total) {
  slide.addText(`${n} / ${total}`, {
    x: 12.5, y: 7.1, w: 0.8, h: 0.3,
    fontSize: 9, fontFace: F.body, color: C.muted, align: "right", margin: 0,
  });
}

function addSideBar(slide) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.15, h: 7.5, fill: { color: C.gold }, line: { type: "none" },
  });
}

function addFooter(slide, text) {
  slide.addText(text, {
    x: 0.5, y: 7.1, w: 10, h: 0.3,
    fontSize: 9, fontFace: F.body, color: C.muted, align: "left", margin: 0,
  });
}

const TOTAL = 10;

// ===================== Slide 1: 封面 =====================
{
  const s = pres.addSlide();
  s.background = { color: C.navyDeep };

  // 左侧金色竖条
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.15, h: 7.5, fill: { color: C.gold }, line: { type: "none" },
  });

  // 左上角小标签
  s.addText("HARNESS ENGINEERING · DEMO 2026-04-22", {
    x: 0.8, y: 0.6, w: 10, h: 0.4,
    fontSize: 11, fontFace: F.body, color: C.gold, bold: true, charSpacing: 4, margin: 0,
  });

  // 主标题
  s.addText("啄木鸟", {
    x: 0.8, y: 1.8, w: 12, h: 1.5,
    fontSize: 96, fontFace: F.title, color: C.white, bold: true, margin: 0,
  });

  // 副标题
  s.addText("PRD 评审 Agent", {
    x: 0.8, y: 3.3, w: 12, h: 0.8,
    fontSize: 36, fontFace: F.title, color: C.ice, margin: 0,
  });

  // 分隔线
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 4.4, w: 0.8, h: 0.05, fill: { color: C.gold }, line: { type: "none" },
  });

  // 定位句
  s.addText("不是一个 LLM 应用。是一个 Harness。", {
    x: 0.8, y: 4.7, w: 12, h: 0.6,
    fontSize: 22, fontFace: F.body, color: C.white, italic: true, margin: 0,
  });

  // 底部元信息
  s.addText([
    { text: "汇报对象  ", options: { color: C.muted, fontSize: 12 } },
    { text: "+1 · AI 基建组\n", options: { color: C.ice, fontSize: 12, bold: true } },
    { text: "时长  ", options: { color: C.muted, fontSize: 12 } },
    { text: "15 min demo + Q&A\n", options: { color: C.ice, fontSize: 12, bold: true } },
    { text: "状态  ", options: { color: C.muted, fontSize: 12 } },
    { text: "内测中 · 73 commits · eval 通道已建", options: { color: C.ice, fontSize: 12, bold: true } },
  ], { x: 0.8, y: 6.1, w: 12, h: 1.2, fontFace: F.body, margin: 0, paraSpaceAfter: 4 });
}

// ===================== Slide 2: 一句话定位 =====================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addSideBar(s);

  s.addText("核心主张", {
    x: 0.6, y: 0.5, w: 12, h: 0.4,
    fontSize: 12, fontFace: F.body, color: C.gold, bold: true, charSpacing: 4, margin: 0,
  });

  // 大字主张
  s.addText([
    { text: "别人做的是 ", options: { color: C.muted, fontSize: 32 } },
    { text: "Prompt + LLM 直出", options: { color: C.navy, fontSize: 32, bold: true, breakLine: true } },
    { text: "我做的是 ", options: { color: C.muted, fontSize: 32 } },
    { text: "Harness", options: { color: C.gold, fontSize: 32, bold: true } },
    { text: "：系统级的约束与反馈", options: { color: C.navy, fontSize: 32, bold: true } },
  ], {
    x: 0.6, y: 1.2, w: 12.2, h: 2.2, fontFace: F.title, margin: 0, paraSpaceAfter: 8,
  });

  // 三列对比
  const cols = [
    { t: "拓扑约束", d: "Orchestrator → 4 Worker → 苍鹰 meta-reviewer\n禁止 Worker 互调 · 依据必须可验证" },
    { t: "反馈闭环", d: "session 日志 → EMA 规则权重更新\n高噪规则自动标记 · 不靠人工维护 prompt" },
    { t: "Eval 量化", d: "多维度评分 + 预埋回归集\n一致性 / 完整性 / 依据可靠度 四维打分" },
  ];
  const colW = 4.1, gap = 0.1;
  cols.forEach((col, i) => {
    const x = 0.6 + i * (colW + gap);
    const y = 4.0;
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: colW, h: 2.6, fill: { color: C.ice, transparency: 70 }, line: { type: "none" },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 0.08, h: 2.6, fill: { color: C.navy }, line: { type: "none" },
    });
    s.addText(col.t, {
      x: x + 0.3, y: y + 0.25, w: colW - 0.4, h: 0.5,
      fontSize: 18, fontFace: F.title, color: C.navy, bold: true, margin: 0,
    });
    s.addText(col.d, {
      x: x + 0.3, y: y + 0.85, w: colW - 0.4, h: 1.6,
      fontSize: 12, fontFace: F.body, color: C.dark, margin: 0, paraSpaceAfter: 4,
    });
  });

  addFooter(s, "Harness ≠ Prompt Engineering · 系统设计先于提示词调优");
  addPageNum(s, 2, TOTAL);
}

// ===================== Slide 3: 架构图 =====================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addSideBar(s);

  s.addText("系统拓扑", {
    x: 0.6, y: 0.5, w: 12, h: 0.4,
    fontSize: 12, fontFace: F.body, color: C.gold, bold: true, charSpacing: 4, margin: 0,
  });
  s.addText("单向派发 · 4 鸟并行 · 苍鹰交叉校验", {
    x: 0.6, y: 0.95, w: 12, h: 0.5,
    fontSize: 24, fontFace: F.title, color: C.navy, bold: true, margin: 0,
  });

  // Orchestrator (顶层中央)
  const orchX = 5.65, orchY = 1.9, orchW = 2, orchH = 0.75;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: orchX, y: orchY, w: orchW, h: orchH,
    fill: { color: C.navy }, line: { type: "none" }, rectRadius: 0.08,
  });
  s.addText("Orchestrator", {
    x: orchX, y: orchY, w: orchW, h: orchH,
    fontSize: 14, fontFace: F.title, color: C.white, bold: true, align: "center", valign: "middle", margin: 0,
  });

  // 4 个 Worker
  const workers = [
    { name: "织布鸟", role: "结构" },
    { name: "猫头鹰", role: "质量" },
    { name: "渡鸦", role: "AI Coding" },
    { name: "鸬鹚", role: "数据" },
  ];
  const wY = 3.5, wH = 1.1, wW = 2.4, gapW = 0.35;
  const totalW = 4 * wW + 3 * gapW;
  const startX = (13.3 - totalW) / 2;

  workers.forEach((w, i) => {
    const x = startX + i * (wW + gapW);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x, y: wY, w: wW, h: wH,
      fill: { color: C.white }, line: { color: C.navy, width: 1.5 }, rectRadius: 0.06,
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x, y: wY, w: wW, h: 0.08, fill: { color: C.gold }, line: { type: "none" },
    });
    s.addText(w.name, {
      x: x + 0.15, y: wY + 0.18, w: wW - 0.3, h: 0.4,
      fontSize: 18, fontFace: F.title, color: C.navy, bold: true, margin: 0,
    });
    s.addText(w.role, {
      x: x + 0.15, y: wY + 0.55, w: wW - 0.3, h: 0.3,
      fontSize: 11, fontFace: F.body, color: C.muted, margin: 0,
    });
    s.addText("Worker", {
      x: x + 0.15, y: wY + 0.82, w: wW - 0.3, h: 0.25,
      fontSize: 9, fontFace: F.body, color: C.muted, italic: true, margin: 0,
    });

    // Orchestrator → Worker 连线
    const lineStartX = orchX + orchW / 2;
    const lineStartY = orchY + orchH;
    const lineEndX = x + wW / 2;
    const lineEndY = wY;
    s.addShape(pres.shapes.LINE, {
      x: Math.min(lineStartX, lineEndX),
      y: lineStartY,
      w: Math.abs(lineEndX - lineStartX),
      h: lineEndY - lineStartY,
      line: { color: C.ice, width: 1.5, beginArrowType: "none", endArrowType: "triangle" },
      flipH: lineEndX < lineStartX,
    });
  });

  // 苍鹰 meta-reviewer（底部横条）
  const gY = 5.0, gH = 0.85;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: startX, y: gY, w: totalW, h: gH,
    fill: { color: C.dark }, line: { type: "none" }, rectRadius: 0.08,
  });
  s.addText([
    { text: "苍鹰  ", options: { color: C.gold, fontSize: 18, bold: true } },
    { text: "Meta-Reviewer · 交叉校验 4 份结论 · 只审核不重写", options: { color: C.white, fontSize: 13 } },
  ], {
    x: startX + 0.3, y: gY, w: totalW - 0.6, h: gH,
    fontFace: F.title, align: "left", valign: "middle", margin: 0,
  });

  // Side Query 标签
  s.addText("每条结论挂可验证依据 · 编造即撤回", {
    x: 0.6, y: 6.3, w: 12, h: 0.3,
    fontSize: 12, fontFace: F.body, color: C.muted, italic: true, align: "center", margin: 0,
  });

  addFooter(s, "R1 单向拓扑 · 聚合只在 Orchestrator 或 Meta");
  addPageNum(s, 3, TOTAL);
}

// ===================== Slide 4: 设计哲学 =====================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addSideBar(s);

  s.addText("设计哲学", {
    x: 0.6, y: 0.5, w: 12, h: 0.4,
    fontSize: 12, fontFace: F.body, color: C.gold, bold: true, charSpacing: 4, margin: 0,
  });
  s.addText("HARNESS_RULES Top 3", {
    x: 0.6, y: 0.95, w: 12, h: 0.5,
    fontSize: 24, fontFace: F.title, color: C.navy, bold: true, margin: 0,
  });

  const rules = [
    {
      tag: "M1", title: "看真实数据 > 猜",
      body: "自评文档漂移是常态。Session jsonl 和 STATUS 才是真相源。\n修复前必须 grep 代码 + git log 验证，不信文档结论。",
    },
    {
      tag: "M2", title: "Harness ≠ Prompt 问题",
      body: "80% \"模型效果差\" 是系统设计问题：静默吞异常 / 反馈未回流 / 边界未约束。\n先查 harness，再调 prompt。",
    },
    {
      tag: "R1", title: "单向拓扑",
      body: "Orchestrator → Worker 单向派发，禁止 Worker 互调。\n聚合只在 Orchestrator 或 Meta-Reviewer，避免抢戏与责任扩散。",
    },
  ];

  const rowY = 1.75, rowH = 1.55, rowGap = 0.12;
  rules.forEach((r, i) => {
    const y = rowY + i * (rowH + rowGap);

    // 左侧 tag 块
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.6, y, w: 1.2, h: rowH,
      fill: { color: C.navy }, line: { type: "none" },
    });
    s.addText(r.tag, {
      x: 0.6, y, w: 1.2, h: rowH,
      fontSize: 40, fontFace: F.num, color: C.gold, bold: true,
      align: "center", valign: "middle", margin: 0,
    });

    // 右侧内容
    s.addShape(pres.shapes.RECTANGLE, {
      x: 1.8, y, w: 11, h: rowH,
      fill: { color: C.ice, transparency: 80 }, line: { type: "none" },
    });
    s.addText(r.title, {
      x: 2.1, y: y + 0.2, w: 10.5, h: 0.5,
      fontSize: 18, fontFace: F.title, color: C.navy, bold: true, margin: 0,
    });
    s.addText(r.body, {
      x: 2.1, y: y + 0.75, w: 10.5, h: rowH - 0.8,
      fontSize: 13, fontFace: F.body, color: C.dark, margin: 0, paraSpaceAfter: 2,
    });
  });

  addFooter(s, "完整 30+ 条规则见 docs/HARNESS_RULES.md");
  addPageNum(s, 4, TOTAL);
}

// ===================== Slide 5: 产出示例 =====================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addSideBar(s);

  s.addText("产出示例", {
    x: 0.6, y: 0.5, w: 12, h: 0.4,
    fontSize: 12, fontFace: F.body, color: C.gold, bold: true, charSpacing: 4, margin: 0,
  });
  s.addText("29 条改进项 · 4 维度 · 每条挂依据", {
    x: 0.6, y: 0.95, w: 12, h: 0.5,
    fontSize: 24, fontFace: F.title, color: C.navy, bold: true, margin: 0,
  });

  // 左侧：维度饼状视觉（用色块表示）
  const dims = [
    { name: "结构层", count: 8, color: C.navy },
    { name: "质量层", count: 9, color: C.gold },
    { name: "编码层", count: 6, color: "7B8FAD" },
    { name: "数据层", count: 6, color: "4A6FA5" },
  ];
  s.addText("维度分布", {
    x: 0.6, y: 1.85, w: 5, h: 0.3,
    fontSize: 12, fontFace: F.body, color: C.muted, bold: true, margin: 0,
  });
  dims.forEach((d, i) => {
    const y = 2.3 + i * 0.65;
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.6, y, w: 0.5, h: 0.5, fill: { color: d.color }, line: { type: "none" },
    });
    s.addText(d.name, {
      x: 1.25, y, w: 2, h: 0.5,
      fontSize: 14, fontFace: F.body, color: C.dark, bold: true, valign: "middle", margin: 0,
    });
    // 数量条
    const barW = d.count * 0.3;
    s.addShape(pres.shapes.RECTANGLE, {
      x: 3.3, y: y + 0.1, w: barW, h: 0.3, fill: { color: d.color, transparency: 40 }, line: { type: "none" },
    });
    s.addText(`${d.count}`, {
      x: 3.3 + barW + 0.1, y, w: 0.5, h: 0.5,
      fontSize: 14, fontFace: F.num, color: d.color, bold: true, valign: "middle", margin: 0,
    });
  });

  // 右侧：单条评审项卡片
  const cardX = 7.0, cardY = 1.85, cardW = 5.8, cardH = 4.7;
  s.addShape(pres.shapes.RECTANGLE, {
    x: cardX, y: cardY, w: cardW, h: cardH,
    fill: { color: C.dark }, line: { type: "none" },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: cardX, y: cardY, w: cardW, h: 0.08, fill: { color: C.gold }, line: { type: "none" },
  });

  s.addText("单条评审项结构", {
    x: cardX + 0.3, y: cardY + 0.25, w: cardW - 0.6, h: 0.4,
    fontSize: 12, fontFace: F.body, color: C.gold, bold: true, charSpacing: 3, margin: 0,
  });
  s.addText("#R-013 · 严重度 HIGH", {
    x: cardX + 0.3, y: cardY + 0.7, w: cardW - 0.6, h: 0.4,
    fontSize: 14, fontFace: F.num, color: C.white, bold: true, margin: 0,
  });

  const fields = [
    { k: "位置", v: "3.2 节 · 风险告警数据埋点" },
    { k: "问题", v: "埋点口径未定义，无法回溯告警触达率" },
    { k: "建议", v: "补充「告警推送成功率 / 点击率 / 转化率」三级指标" },
    { k: "依据", v: "知识库 §埋点规范 4.1 + 历史 PRD sample-2 同类缺陷" },
  ];
  fields.forEach((f, i) => {
    const y = cardY + 1.3 + i * 0.8;
    s.addText(f.k, {
      x: cardX + 0.3, y, w: 0.8, h: 0.3,
      fontSize: 10, fontFace: F.body, color: C.gold, bold: true, charSpacing: 2, margin: 0,
    });
    s.addText(f.v, {
      x: cardX + 0.3, y: y + 0.3, w: cardW - 0.6, h: 0.4,
      fontSize: 12, fontFace: F.body, color: C.white, margin: 0,
    });
  });

  addFooter(s, "依据可被 Side Query 反查 · 编造自动撤回");
  addPageNum(s, 5, TOTAL);
}

// ===================== Slide 6: Live Demo =====================
{
  const s = pres.addSlide();
  s.background = { color: C.navyDeep };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.15, h: 7.5, fill: { color: C.gold }, line: { type: "none" },
  });

  s.addText("现场演示", {
    x: 0.8, y: 0.8, w: 12, h: 0.4,
    fontSize: 12, fontFace: F.body, color: C.gold, bold: true, charSpacing: 4, margin: 0,
  });

  s.addText("LIVE DEMO", {
    x: 0.8, y: 1.5, w: 12, h: 1.5,
    fontSize: 90, fontFace: F.title, color: C.white, bold: true, charSpacing: 8, margin: 0,
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 3.2, w: 1.2, h: 0.05, fill: { color: C.gold }, line: { type: "none" },
  });

  // 命令行代码框
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 3.7, w: 11.7, h: 0.9,
    fill: { color: "000000" }, line: { color: C.gold, width: 1 },
  });
  s.addText([
    { text: "$ ", options: { color: C.gold, fontSize: 18, fontFace: "Consolas", bold: true } },
    { text: "python run_session.py sample-1-favorites --parallel", options: { color: C.ice, fontSize: 18, fontFace: "Consolas" } },
  ], {
    x: 1.1, y: 3.7, w: 11.3, h: 0.9, align: "left", valign: "middle", margin: 0,
  });

  // 演示观察点
  const points = [
    { k: "10s", v: "4 worker 并行派出 · 日志实时打印分工" },
    { k: "2min", v: "切预跑成品 · 展示 29 条改进项 + 引用依据" },
    { k: "回看", v: "苍鹰交叉校验 · 只审核不重写的边界约束" },
  ];
  points.forEach((p, i) => {
    const y = 5.1 + i * 0.65;
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.8, y, w: 1, h: 0.5, fill: { color: C.gold }, line: { type: "none" },
    });
    s.addText(p.k, {
      x: 0.8, y, w: 1, h: 0.5,
      fontSize: 14, fontFace: F.num, color: C.navyDeep, bold: true,
      align: "center", valign: "middle", margin: 0,
    });
    s.addText(p.v, {
      x: 2.1, y, w: 10.5, h: 0.5,
      fontSize: 14, fontFace: F.body, color: C.white, valign: "middle", margin: 0,
    });
  });

  s.addText("沙箱已预热 · 兜底预跑结果已就位", {
    x: 0.8, y: 7.1, w: 12, h: 0.3,
    fontSize: 10, fontFace: F.body, color: C.muted, italic: true, margin: 0,
  });
}

// ===================== Slide 7: Eval 数据 =====================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addSideBar(s);

  s.addText("Eval 数据", {
    x: 0.6, y: 0.5, w: 12, h: 0.4,
    fontSize: 12, fontFace: F.body, color: C.gold, bold: true, charSpacing: 4, margin: 0,
  });
  s.addText("不靠感觉 · 用量化说话", {
    x: 0.6, y: 0.95, w: 12, h: 0.5,
    fontSize: 24, fontFace: F.title, color: C.navy, bold: true, margin: 0,
  });

  // 三大数字
  const stats = [
    { num: "80%", label: "有效一致性", sub: "productive session · 剔除 ops 噪声", color: C.navy },
    { num: "0%", label: "Worker 静默率", sub: "P0 修复后 4 worker 无挂机", color: C.success },
    { num: "$0.66", label: "单次成本", sub: "29 条改进项 · 8 分钟 · 4 worker 并行", color: C.gold },
  ];

  const statW = 4.0, statGap = 0.15;
  const totalStatW = 3 * statW + 2 * statGap;
  const statStart = (13.3 - totalStatW) / 2;
  stats.forEach((st, i) => {
    const x = statStart + i * (statW + statGap);
    const y = 1.9;
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: statW, h: 2.6,
      fill: { color: C.white }, line: { color: C.line, width: 1 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: statW, h: 0.1, fill: { color: st.color }, line: { type: "none" },
    });
    s.addText(st.num, {
      x, y: y + 0.35, w: statW, h: 1.2,
      fontSize: 64, fontFace: F.num, color: st.color, bold: true,
      align: "center", valign: "middle", margin: 0,
    });
    s.addText(st.label, {
      x, y: y + 1.6, w: statW, h: 0.4,
      fontSize: 16, fontFace: F.title, color: C.navy, bold: true, align: "center", margin: 0,
    });
    s.addText(st.sub, {
      x: x + 0.2, y: y + 2.05, w: statW - 0.4, h: 0.5,
      fontSize: 10, fontFace: F.body, color: C.muted, align: "center", margin: 0,
    });
  });

  // 下方：基线对比条
  s.addText("基线 → 当前演进", {
    x: 0.6, y: 5.0, w: 12, h: 0.3,
    fontSize: 12, fontFace: F.body, color: C.muted, bold: true, charSpacing: 2, margin: 0,
  });

  // 进度条式对比
  const barY = 5.5, barH = 0.55;
  // Before
  s.addText("4 月初", {
    x: 0.6, y: barY, w: 1.2, h: barH,
    fontSize: 12, fontFace: F.body, color: C.muted, valign: "middle", margin: 0,
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 1.9, y: barY + 0.1, w: 1.8, h: 0.35,
    fill: { color: C.warn, transparency: 30 }, line: { type: "none" },
  });
  s.addText("17%", {
    x: 1.9, y: barY + 0.1, w: 1.8, h: 0.35,
    fontSize: 14, fontFace: F.num, color: C.white, bold: true,
    align: "center", valign: "middle", margin: 0,
  });
  s.addText("consistency 基线 · 3 个 worker 常静默", {
    x: 3.9, y: barY, w: 8, h: barH,
    fontSize: 12, fontFace: F.body, color: C.muted, valign: "middle", margin: 0,
  });

  // After
  const barY2 = 6.2;
  s.addText("4 月 22", {
    x: 0.6, y: barY2, w: 1.2, h: barH,
    fontSize: 12, fontFace: F.body, color: C.navy, bold: true, valign: "middle", margin: 0,
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 1.9, y: barY2 + 0.1, w: 8, h: 0.35,
    fill: { color: C.success }, line: { type: "none" },
  });
  s.addText("80%", {
    x: 1.9, y: barY2 + 0.1, w: 8, h: 0.35,
    fontSize: 14, fontFace: F.num, color: C.white, bold: true,
    align: "center", valign: "middle", margin: 0,
  });
  s.addText("两轮 P0/P1 系统性修复后 · 248 单测绿", {
    x: 10.1, y: barY2, w: 3, h: barH,
    fontSize: 12, fontFace: F.body, color: C.navy, valign: "middle", margin: 0,
  });

  addFooter(s, "数据源：STATUS.md · eval/results/ · 73 commits 迭代");
  addPageNum(s, 7, TOTAL);
}

// ===================== Slide 8: 还在路上 =====================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addSideBar(s);

  s.addText("诚实的现状", {
    x: 0.6, y: 0.5, w: 12, h: 0.4,
    fontSize: 12, fontFace: F.body, color: C.gold, bold: true, charSpacing: 4, margin: 0,
  });
  s.addText("还在路上 · 已识别未解决", {
    x: 0.6, y: 0.95, w: 12, h: 0.5,
    fontSize: 24, fontFace: F.title, color: C.navy, bold: true, margin: 0,
  });

  const issues = [
    {
      tag: "稳定性", level: "P1",
      title: "Consistency overlap 37.98%",
      desc: "3 次 run 结论重合度仍偏低。worker prompt 温度 + 检索分桶导致的随机性尚未完全驯化。",
      plan: "引入 self-consistency 投票 + 检索结果固定 seed",
    },
    {
      tag: "流程", level: "P1",
      title: "Flow 完成率 40%",
      desc: "review_completed 状态达成率偏低。主要卡在 meta-reviewer 的 tool schema 异常重试。",
      plan: "已落地 empty_submission retry，下一轮观察数据",
    },
    {
      tag: "工程", level: "P2",
      title: "Windows + 多进程 OAuth 挤占",
      desc: "shadow_run 并发时 Claude Code token 竞争导致 401，演示需单进程。",
      plan: "迁移到正式 API key 后自动解决",
    },
  ];

  issues.forEach((it, i) => {
    const y = 1.75 + i * 1.55;
    // 左侧等级块
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.6, y, w: 1, h: 1.4,
      fill: { color: C.warn }, line: { type: "none" },
    });
    s.addText(it.level, {
      x: 0.6, y, w: 1, h: 0.5,
      fontSize: 14, fontFace: F.num, color: C.white, bold: true,
      align: "center", valign: "middle", margin: 0,
    });
    s.addText(it.tag, {
      x: 0.6, y: y + 0.5, w: 1, h: 0.9,
      fontSize: 11, fontFace: F.body, color: C.white,
      align: "center", valign: "middle", margin: 0,
    });

    // 右侧内容
    s.addShape(pres.shapes.RECTANGLE, {
      x: 1.6, y, w: 11.3, h: 1.4,
      fill: { color: C.ice, transparency: 85 }, line: { type: "none" },
    });
    s.addText(it.title, {
      x: 1.9, y: y + 0.15, w: 10.8, h: 0.4,
      fontSize: 16, fontFace: F.title, color: C.navy, bold: true, margin: 0,
    });
    s.addText(it.desc, {
      x: 1.9, y: y + 0.55, w: 10.8, h: 0.4,
      fontSize: 12, fontFace: F.body, color: C.dark, margin: 0,
    });
    s.addText([
      { text: "缓解计划  ", options: { color: C.gold, fontSize: 11, bold: true } },
      { text: it.plan, options: { color: C.muted, fontSize: 11 } },
    ], {
      x: 1.9, y: y + 0.98, w: 10.8, h: 0.4, fontFace: F.body, margin: 0,
    });
  });

  addFooter(s, "已知 · 已归因 · 有缓解路径 — 不是未知未知");
  addPageNum(s, 8, TOTAL);
}

// ===================== Slide 9: 支持需求 =====================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addSideBar(s);

  s.addText("会议 ASK", {
    x: 0.6, y: 0.5, w: 12, h: 0.4,
    fontSize: 12, fontFace: F.body, color: C.gold, bold: true, charSpacing: 4, margin: 0,
  });
  s.addText("需要的支持", {
    x: 0.6, y: 0.95, w: 12, h: 0.5,
    fontSize: 24, fontFace: F.title, color: C.navy, bold: true, margin: 0,
  });

  const asks = [
    {
      pri: "P0", who: "AI 基建组",
      title: "Claude 正式 API 额度 / CC 账号组权限",
      why: "现状靠个人 Claude Code 登录态，不可持续 · 多进程并发时 OAuth 挤占",
      ask: "申请团队级 API key 或进入账号组白名单",
    },
    {
      pri: "P1", who: "PM 团队",
      title: "20–50 份 PRD 标注人力",
      why: "eval 回归基准目前只有 1 份 ground_truth · 样本量不足以支撑模型迭代",
      ask: "借 2–3 名 PM 同学 × 1 周 · 标注产出即归入知识库",
    },
    {
      pri: "P2", who: "基建组",
      title: "内网稳定部署通道",
      why: "Cloudflare Tunnel 只适合个人内测 · 扩大试用需稳定入口",
      ask: "接入公司内网域名 + HTTPS · Docker compose 已就绪",
    },
  ];

  asks.forEach((a, i) => {
    const y = 1.75 + i * 1.55;
    // 优先级
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.6, y, w: 0.9, h: 1.4,
      fill: { color: i === 0 ? C.gold : i === 1 ? C.navy : C.muted }, line: { type: "none" },
    });
    s.addText(a.pri, {
      x: 0.6, y, w: 0.9, h: 1.4,
      fontSize: 28, fontFace: F.num, color: C.white, bold: true,
      align: "center", valign: "middle", margin: 0,
    });

    // 责任方
    s.addShape(pres.shapes.RECTANGLE, {
      x: 1.5, y, w: 2, h: 1.4,
      fill: { color: C.dark }, line: { type: "none" },
    });
    s.addText("责任方", {
      x: 1.5, y: y + 0.2, w: 2, h: 0.3,
      fontSize: 9, fontFace: F.body, color: C.gold, charSpacing: 2,
      align: "center", margin: 0,
    });
    s.addText(a.who, {
      x: 1.5, y: y + 0.5, w: 2, h: 0.7,
      fontSize: 13, fontFace: F.title, color: C.white, bold: true,
      align: "center", valign: "middle", margin: 0,
    });

    // 主体
    s.addShape(pres.shapes.RECTANGLE, {
      x: 3.5, y, w: 9.4, h: 1.4,
      fill: { color: C.ice, transparency: 80 }, line: { type: "none" },
    });
    s.addText(a.title, {
      x: 3.75, y: y + 0.15, w: 9, h: 0.4,
      fontSize: 15, fontFace: F.title, color: C.navy, bold: true, margin: 0,
    });
    s.addText([
      { text: "痛点  ", options: { color: C.gold, fontSize: 10, bold: true } },
      { text: a.why, options: { color: C.dark, fontSize: 11, breakLine: true } },
      { text: "诉求  ", options: { color: C.gold, fontSize: 10, bold: true } },
      { text: a.ask, options: { color: C.dark, fontSize: 11 } },
    ], {
      x: 3.75, y: y + 0.55, w: 9, h: 0.85, fontFace: F.body, margin: 0, paraSpaceAfter: 2,
    });
  });

  addFooter(s, "不求今天定方案 · 希望会后对齐哪几件基建组能接");
  addPageNum(s, 9, TOTAL);
}

// ===================== Slide 10: 结束页 =====================
{
  const s = pres.addSlide();
  s.background = { color: C.navyDeep };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.15, h: 7.5, fill: { color: C.gold }, line: { type: "none" },
  });

  s.addText("Q & A", {
    x: 0.8, y: 1.0, w: 12, h: 1.8,
    fontSize: 110, fontFace: F.title, color: C.white, bold: true, charSpacing: 10, margin: 0,
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 3.2, w: 1.2, h: 0.05, fill: { color: C.gold }, line: { type: "none" },
  });

  s.addText("Harness is the product.", {
    x: 0.8, y: 3.5, w: 12, h: 0.8,
    fontSize: 32, fontFace: F.title, color: C.ice, italic: true, margin: 0,
  });

  s.addText("我不是在训模型，我是在训 harness。\n模型是可替换的，harness 才是积累。", {
    x: 0.8, y: 4.5, w: 12, h: 1.2,
    fontSize: 16, fontFace: F.body, color: C.white, margin: 0, paraSpaceAfter: 4,
  });

  // 底部资源链接
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 6.3, w: 12, h: 0.04, fill: { color: C.muted }, line: { type: "none" },
  });

  s.addText([
    { text: "代码  ", options: { color: C.muted, fontSize: 11 } },
    { text: "agent/prd-review    ", options: { color: C.ice, fontSize: 11, bold: true } },
    { text: "规则  ", options: { color: C.muted, fontSize: 11 } },
    { text: "docs/HARNESS_RULES.md    ", options: { color: C.ice, fontSize: 11, bold: true } },
    { text: "Eval  ", options: { color: C.muted, fontSize: 11 } },
    { text: "STATUS.md", options: { color: C.ice, fontSize: 11, bold: true } },
  ], {
    x: 0.8, y: 6.5, w: 12, h: 0.4, fontFace: F.body, margin: 0,
  });
}

// ===== 输出 =====
pres.writeFile({ fileName: "啄木鸟_演示_2026-04-22.pptx" }).then((fn) => {
  console.log("PPT 生成成功：", fn);
});
