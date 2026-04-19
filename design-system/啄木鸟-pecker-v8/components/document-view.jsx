// DocumentView · PRD 原文渲染
// 行号 + 锚点 inline 高亮 + 顶部汇总条（strong/weak/gaps 计数） + 评论联动
// 高亮类型：strong（实）· weak（虚）· gap（警告）· anchored（锚点选中）

function DocumentView({
  title = 'PRD',
  subtitle,
  summary,                 // {strong:n, weak:n, gaps:n}
  blocks = [],             // [{type:'h'|'p'|'li', content, id, highlights:[{kind, start, end, anchor}]}]
  selectedAnchor,
  onAnchorClick,
  style = {},
}) {
  return (
    <div style={{
      background:'var(--surface-raised)',
      border:'1px solid var(--border-default)',
      borderRadius:'var(--r-4)',
      overflow:'hidden',
      display:'flex', flexDirection:'column',
      ...style,
    }}>
      {/* header */}
      <div style={{
        padding:'14px 20px',
        borderBottom:'1px solid var(--border-default)',
        display:'flex', alignItems:'center', justifyContent:'space-between',
      }}>
        <div>
          <div style={{fontSize:14, fontWeight:600, color:'var(--text-strong)'}}>{title}</div>
          {subtitle && <div style={{fontSize:11, color:'var(--text-muted)', marginTop:2, fontFamily:'var(--font-mono)'}}>{subtitle}</div>}
        </div>
        {summary && (
          <div style={{display:'flex', gap:6}}>
            <SummaryChip kind="strong" n={summary.strong}/>
            <SummaryChip kind="weak"   n={summary.weak}/>
            <SummaryChip kind="gap"    n={summary.gaps}/>
          </div>
        )}
      </div>

      {/* body */}
      <div style={{
        flex:1, overflow:'auto',
        padding:'14px 0',
        fontSize: 14, lineHeight: 1.7, color:'var(--text-default)',
      }}>
        {blocks.map((b, i) => (
          <DocBlock key={i} line={i+1} block={b}
            selectedAnchor={selectedAnchor}
            onAnchorClick={onAnchorClick}/>
        ))}
      </div>
    </div>
  );
}

function SummaryChip({ kind, n }) {
  const map = {
    strong: { fg:'var(--status-done-fg)',   bg:'var(--status-done-bg)',   label:'已覆盖' },
    weak:   { fg:'var(--status-warn-fg)',   bg:'var(--status-warn-bg)',   label:'薄弱' },
    gap:    { fg:'var(--status-failed-fg)', bg:'var(--status-failed-bg)', label:'盲区' },
  }[kind];
  return (
    <span style={{
      display:'inline-flex', alignItems:'center', gap:5,
      padding:'3px 9px', borderRadius:'var(--r-pill)',
      background: map.bg, color: map.fg,
      fontSize: 11, fontWeight: 600,
    }}>
      <span style={{fontFamily:'var(--font-mono)', fontVariantNumeric:'tabular-nums'}}>{n}</span>
      {map.label}
    </span>
  );
}

function DocBlock({ line, block, selectedAnchor, onAnchorClick }) {
  const Tag = block.type === 'h' ? 'h3' : block.type === 'h2' ? 'h4' : 'p';
  const style = {
    h:  { fontSize: 17, fontWeight: 600, color:'var(--text-strong)', margin:'14px 0 6px' },
    h2: { fontSize: 14, fontWeight: 600, color:'var(--text-strong)', margin:'10px 0 4px' },
    p:  { margin:'4px 0' },
    li: { margin:'2px 0', paddingLeft: 18, position:'relative' },
  }[block.type] || {};

  const content = renderHighlights(block.content, block.highlights || [], { selectedAnchor, onAnchorClick });

  return (
    <div style={{display:'grid', gridTemplateColumns:'48px 1fr', gap:16, padding:'0 20px'}}>
      <span style={{
        fontFamily:'var(--font-mono)', fontSize:10,
        color:'var(--text-faint)', textAlign:'right', paddingTop: 6, userSelect:'none',
      }}>{line}</span>
      <Tag style={style}>
        {block.type === 'li' && <span style={{position:'absolute', left:0, color:'var(--text-muted)'}}>·</span>}
        {content}
      </Tag>
    </div>
  );
}

function renderHighlights(text, highlights, { selectedAnchor, onAnchorClick }) {
  if (!highlights.length) return text;
  const sorted = [...highlights].sort((a,b) => a.start - b.start);
  const out = [];
  let cursor = 0;
  sorted.forEach((h, i) => {
    if (h.start > cursor) out.push(text.slice(cursor, h.start));
    const inner = text.slice(h.start, h.end);
    const selected = selectedAnchor && h.anchor === selectedAnchor;
    out.push(<HL key={i} kind={h.kind} anchor={h.anchor} selected={selected} onClick={() => onAnchorClick?.(h.anchor)}>{inner}</HL>);
    cursor = h.end;
  });
  if (cursor < text.length) out.push(text.slice(cursor));
  return out;
}

function HL({ kind, anchor, selected, onClick, children }) {
  const map = {
    strong: { bg:'color-mix(in oklch, var(--status-done-dot) 18%, transparent)',
              u:'var(--status-done-dot)' },
    weak:   { bg:'color-mix(in oklch, var(--status-warn-dot) 18%, transparent)',
              u:'var(--status-warn-dot)' },
    gap:    { bg:'color-mix(in oklch, var(--status-failed-dot) 18%, transparent)',
              u:'var(--status-failed-dot)' },
  }[kind] || {};
  return (
    <mark onClick={onClick} style={{
      background: selected ? `color-mix(in oklch, var(--accent-500) 28%, transparent)` : map.bg,
      borderBottom: `2px solid ${selected ? 'var(--accent-500)' : map.u}`,
      padding:'0 1px', cursor: anchor ? 'pointer' : 'default',
      color:'inherit',
      transition: 'background var(--dur-fast) var(--ease-out)',
    }}>
      {children}
    </mark>
  );
}

Object.assign(window, { DocumentView, SummaryChip });
