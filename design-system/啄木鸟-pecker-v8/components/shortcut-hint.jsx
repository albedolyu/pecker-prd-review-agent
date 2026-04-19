// ShortcutHint · 11px pill · 键盘快捷键提示
// 贴在可操作元素右侧 / 底部常驻 keymap 条

function ShortcutHint({ keys = ['j'], label, variant = 'inline', style = {} }) {
  // variant: inline | dark
  const isDark = variant === 'dark';
  return (
    <span style={{
      display:'inline-flex', alignItems:'center', gap:4,
      fontSize: 11, color: isDark ? 'var(--neutral-400)' : 'var(--text-muted)',
      ...style,
    }}>
      {keys.map((k,i) => (
        <React.Fragment key={i}>
          <kbd style={{
            display:'inline-flex', alignItems:'center', justifyContent:'center',
            minWidth: 18, height: 18,
            padding:'0 4px',
            background: isDark ? 'var(--neutral-100)' : 'var(--neutral-50)',
            border: `1px solid ${isDark ? 'var(--neutral-200)' : 'var(--border-default)'}`,
            borderBottomWidth: 2,
            borderRadius: 'var(--r-2)',
            fontFamily:'var(--font-mono)', fontSize: 10, fontWeight: 600,
            color: isDark ? 'var(--neutral-700)' : 'var(--text-strong)',
            lineHeight: 1,
          }}>{k}</kbd>
          {i < keys.length -1 && <span style={{opacity:.4}}>/</span>}
        </React.Fragment>
      ))}
      {label && <span style={{marginLeft: 2}}>{label}</span>}
    </span>
  );
}

function KeymapBar({ items = [], style = {} }) {
  return (
    <div style={{
      display:'inline-flex', alignItems:'center', gap: 16,
      padding:'8px 14px',
      background:'var(--surface-raised)',
      border:'1px solid var(--border-default)',
      borderRadius:'var(--r-4)',
      boxShadow:'var(--shadow-sm)',
      fontFamily:'var(--font-sans)',
      ...style,
    }}>
      {items.map((it, i) => (
        <ShortcutHint key={i} keys={it.keys} label={it.label}/>
      ))}
    </div>
  );
}

Object.assign(window, { ShortcutHint, KeymapBar });
