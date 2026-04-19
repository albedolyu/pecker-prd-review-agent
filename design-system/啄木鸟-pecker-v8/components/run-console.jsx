// RunConsole · Phase 2 流式日志
// 深色局部卡（--surface-console）· 时间戳 · 来源 · 内容三列 · 流式光标

function RunConsole({ lines = [], live = true, height = 280, style = {} }) {
  return (
    <div style={{
      background:'var(--surface-console)',
      color:'var(--surface-console-fg)',
      borderRadius:'var(--r-4)',
      fontFamily:'var(--font-mono)',
      fontSize: 12, lineHeight: 1.55,
      overflow:'hidden',
      display:'flex', flexDirection:'column',
      ...style,
    }}>
      {/* header */}
      <div style={{
        display:'flex', alignItems:'center', justifyContent:'space-between',
        padding:'8px 14px',
        borderBottom:'1px solid rgba(255,255,255,.06)',
        fontSize: 11,
      }}>
        <div style={{display:'flex', alignItems:'center', gap:8}}>
          <span style={{display:'flex', gap:5}}>
            <span style={{width:8,height:8,borderRadius:'50%',background:'#ff5f57'}}/>
            <span style={{width:8,height:8,borderRadius:'50%',background:'#febc2e'}}/>
            <span style={{width:8,height:8,borderRadius:'50%',background:'#28c840'}}/>
          </span>
          <span style={{opacity:.6, letterSpacing:.3}}>run-console · harness-v8.2</span>
        </div>
        <div style={{display:'flex', alignItems:'center', gap:6, opacity:.75}}>
          {live && <>
            <span style={{
              width:6,height:6,borderRadius:'50%',background:'var(--accent-500)',
              animation:'dot-breathe 1.4s ease-out infinite',
            }}/>
            <span>LIVE</span>
          </>}
        </div>
      </div>

      {/* body */}
      <div style={{ flex:1, overflow:'auto', padding:'10px 14px' }}>
        {lines.map((l, i) => <ConsoleLine key={i} {...l}/>)}
        {live && (
          <div style={{display:'flex', alignItems:'center', marginTop: 4}}>
            <span style={{color:'rgba(255,255,255,.35)'}}>›</span>
            <span style={{
              display:'inline-block', width: 7, height: 14, marginLeft: 6,
              background:'var(--accent-500)',
              animation:'dot-breathe 1.1s linear infinite',
            }}/>
          </div>
        )}
      </div>
    </div>
  );
}

function ConsoleLine({ t, src, level = 'info', text }) {
  const levelColor = {
    info:   'rgba(255,255,255,.8)',
    warn:   '#e9b450',
    error:  '#ff8579',
    ok:     '#5ec784',
    accent: '#ff8c4a',
  }[level] || 'rgba(255,255,255,.8)';

  const srcColor = {
    1:'#ff8c4a', 2:'#7aabee', 3:'#5ec784', 4:'#ff8579', 5:'#b9a3ff',
  }[src?.bird] || 'rgba(255,255,255,.5)';

  return (
    <div style={{ display:'grid', gridTemplateColumns:'64px 96px 1fr', gap:10, padding:'1px 0' }}>
      <span style={{color:'rgba(255,255,255,.35)', fontVariantNumeric:'tabular-nums'}}>{t}</span>
      <span style={{ color: srcColor, fontWeight: 500 }}>
        {src?.name ? `[${src.name}]` : '[system]'}
      </span>
      <span style={{ color: levelColor, whiteSpace:'pre-wrap', wordBreak:'break-word' }}>
        {text}
      </span>
    </div>
  );
}

Object.assign(window, { RunConsole, ConsoleLine });
