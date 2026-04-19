// BirdAvatar · 3 sizes × 10 birds × 4 status
// PLACEHOLDER 线稿：等 BirdArt-v2.tsx 到位后替换 <BirdGlyph/> 内部 SVG
// 视觉规则：单色描边线稿 + data-bird={1..10} 切色；状态灯右下角小点（不压轮廓）

const BIRD_SIZES = { lg: 32, md: 24, sm: 16 };

// 极简线稿鸟（10 个轮廓变体；占位。BirdArt-v2 上线后替换）
// 所有 path 只用 stroke，不填充，方便 currentColor 着色
function BirdGlyph({ id = 1 }) {
  // 10 个轮廓：头姿/尾巴/冠羽略不同，共享同一笔触规范
  const paths = {
    1: <g><path d="M7 20c0-5 4-9 9-9 3 0 5 1 7 3l4-1-2 3c1 1 1 3 1 5 0 5-4 9-9 9-5 0-10-4-10-10z"/><circle cx="20" cy="17" r="1" fill="currentColor" stroke="none"/><path d="M10 24l-3 5"/></g>,
    2: <g><path d="M8 22c-1-6 3-11 9-11 4 0 7 2 8 5l4 0-3 3c0 4-3 8-8 8-5 0-9-2-10-5z"/><circle cx="21" cy="18" r="1" fill="currentColor" stroke="none"/><path d="M9 26l-2 4"/><path d="M14 11l2-3"/></g>,
    3: <g><path d="M6 19c2-5 7-8 12-7 4 1 6 4 7 7l3 1-2 3c0 4-4 7-9 7-6 0-11-4-11-11z"/><circle cx="20" cy="16" r="1" fill="currentColor" stroke="none"/><path d="M12 25l-3 5"/><path d="M18 25l1 5"/></g>,
    4: <g><path d="M8 18c0-4 4-8 9-8 4 0 7 2 8 5h4l-2 4c0 4-3 9-9 9-6 0-10-4-10-10z"/><path d="M10 10l2-3 2 2"/><circle cx="20" cy="15" r="1" fill="currentColor" stroke="none"/><path d="M11 23l-3 6"/></g>,
    5: <g><path d="M5 18c0-5 5-10 11-10 5 0 8 2 10 6l4 1-3 3c0 5-5 10-11 10-7 0-11-4-11-10z"/><path d="M9 9l3-3 2 3"/><path d="M13 6l2-2 2 2"/><circle cx="22" cy="16" r="1.2" fill="currentColor" stroke="none"/><path d="M11 24l-4 7"/><path d="M18 26l-1 5"/></g>,
    6: <g><path d="M7 20c0-5 5-10 11-10 4 0 8 2 9 6h3l-2 4c-1 4-5 8-10 8-7 0-11-4-11-8z"/><circle cx="20" cy="17" r="1" fill="currentColor" stroke="none"/></g>,
    7: <g><path d="M8 20c0-5 4-10 10-10 5 0 8 2 9 5l4 1-3 3c0 5-4 9-10 9-6 0-10-3-10-8z"/><circle cx="20" cy="17" r="1" fill="currentColor" stroke="none"/></g>,
    8: <g><path d="M6 20c1-5 6-10 12-10 4 0 7 2 8 5l4 1-3 3c0 5-4 9-9 9-7 0-12-3-12-8z"/><circle cx="21" cy="17" r="1" fill="currentColor" stroke="none"/></g>,
    9: <g><path d="M7 19c2-5 6-9 11-9 4 0 8 2 9 5l3 0-1 4c-1 5-5 9-10 9-6 0-12-4-12-9z"/><circle cx="20" cy="16" r="1" fill="currentColor" stroke="none"/></g>,
    10:<g><path d="M8 20c0-5 5-10 11-10 5 0 8 2 10 5h3l-2 4c0 5-5 9-11 9-6 0-11-3-11-8z"/><circle cx="21" cy="17" r="1" fill="currentColor" stroke="none"/></g>,
  };
  return (
    <svg viewBox="0 0 36 36" fill="none" stroke="currentColor" strokeWidth="1.5"
         strokeLinecap="round" strokeLinejoin="round" style={{ width:'100%', height:'100%' }}>
      {paths[id] || paths[1]}
    </svg>
  );
}

function BirdAvatar({ id = 1, size = 'md', status, placeholder = false, style = {} }) {
  const px = BIRD_SIZES[size] || BIRD_SIZES.md;
  const color = `var(--bird-${id})`;
  const dotSize = size === 'sm' ? 6 : size === 'md' ? 8 : 10;
  return (
    <span style={{
      position: 'relative',
      display: 'inline-flex',
      width: px, height: px,
      flexShrink: 0,
      ...style,
    }}>
      <span style={{
        width: '100%', height: '100%',
        borderRadius: 'var(--r-pill)',
        background: `color-mix(in oklch, ${color} 10%, var(--surface-raised))`,
        border: `1px solid color-mix(in oklch, ${color} 28%, var(--border-default))`,
        color: color,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: size === 'sm' ? 1 : 2,
        opacity: placeholder ? 0.5 : 1,
      }}>
        {placeholder ? (
          <svg viewBox="0 0 36 36" style={{width:'100%',height:'100%'}}>
            <circle cx="18" cy="18" r="10" fill="none" stroke="currentColor" strokeWidth="1.2" strokeDasharray="2 2"/>
          </svg>
        ) : <BirdGlyph id={id} />}
      </span>
      {status && (
        <StatusDot status={status} size={dotSize} style={{
          position:'absolute', right:-2, bottom:-2,
          boxShadow:'0 0 0 2px var(--surface-raised)',
        }}/>
      )}
    </span>
  );
}

// 状态灯 · 四态
function StatusDot({ status='queued', size=8, style={} }) {
  const tokens = {
    queued:  { bg:'var(--status-queued-dot)',  anim:'none' },
    running: { bg:'var(--status-running-dot)', anim:'dot-breathe 1.4s var(--ease-out) infinite' },
    done:    { bg:'var(--status-done-dot)',    anim:'none' },
    failed:  { bg:'var(--status-failed-dot)',  anim:'none' },
    warn:    { bg:'var(--status-warn-dot)',    anim:'none' },
  }[status] || {};
  return (
    <span aria-label={status} style={{
      display:'inline-block',
      width:size, height:size, borderRadius:'50%',
      background: tokens.bg,
      animation: tokens.anim,
      ...style,
    }}/>
  );
}

Object.assign(window, { BirdAvatar, BirdGlyph, StatusDot, BIRD_SIZES });
