// BirdBadge · 职能徽章（pill 形 · <dot>名称）
// 与 BirdAvatar 的 data-bird 色同源

const BIRD_META = {
  1:  { code:'biz',    label:'业务',   type:'worker' },
  2:  { code:'data',   label:'数据',   type:'worker' },
  3:  { code:'ux',     label:'体验',   type:'worker' },
  4:  { code:'risk',   label:'风险',   type:'worker' },
  5:  { code:'eagle',  label:'苍鹰',   type:'meta' },
  6:  { code:'bird-06',label:'bird-06',type:'placeholder' },
  7:  { code:'bird-07',label:'bird-07',type:'placeholder' },
  8:  { code:'bird-08',label:'bird-08',type:'placeholder' },
  9:  { code:'bird-09',label:'bird-09',type:'placeholder' },
  10: { code:'bird-10',label:'bird-10',type:'placeholder' },
};

function BirdBadge({ id = 1, size = 'md', style = {} }) {
  const meta = BIRD_META[id] || BIRD_META[1];
  const color = `var(--bird-${id})`;
  const compact = size === 'sm';
  return (
    <span style={{
      display: 'inline-flex', alignItems:'center', gap: compact ? 4 : 6,
      padding: compact ? '2px 8px' : '3px 10px',
      borderRadius: 'var(--r-pill)',
      background: `color-mix(in oklch, ${color} 12%, var(--surface-sunken))`,
      border: `1px solid color-mix(in oklch, ${color} 22%, var(--border-subtle))`,
      color: `color-mix(in oklch, ${color} 75%, var(--text-strong))`,
      fontSize: compact ? 11 : 12,
      fontWeight: 500,
      lineHeight: 1,
      whiteSpace: 'nowrap',
      fontVariantNumeric: 'tabular-nums',
      ...style,
    }}>
      <span style={{
        width: compact ? 5 : 6, height: compact ? 5 : 6,
        borderRadius: '50%', background: color, flexShrink:0,
      }}/>
      {meta.label}鸟
      {meta.type === 'meta' && <span style={{
        fontSize: 10, fontFamily:'var(--font-mono)', opacity:.7, marginLeft:2,
      }}>meta</span>}
    </span>
  );
}

Object.assign(window, { BirdBadge, BIRD_META });
