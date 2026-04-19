// RunHealthCheck · Phase 1.5 核心
// session 分类大徽章 + effective_consistency 环形 + 5 色失败矩阵 + CTA
// partial_silent 场景强制二选一

function RunHealthCheck({
  sessionClass = 'productive',   // productive | partial_silent | quota_exhausted | degraded
  consistency = 0.92,            // 0-1
  failures = {},                 // {quota_exhausted: n, tool_call_failed, json_parse_error, empty_submission, timeout}
  birds = [],                    // [{id, runs, fails, submissions}]
  onContinue, onRetry,
  style = {},
}) {
  const classInfo = {
    productive:       { fg:'var(--status-done-fg)',   bg:'var(--status-done-bg)',   label:'productive',     desc:'run 质量健康，可进入 Phase 3' },
    partial_silent:   { fg:'var(--status-warn-fg)',   bg:'var(--status-warn-bg)',   label:'partial_silent', desc:'存在静默失败。在不完整结果上做决策风险很高，建议重跑' },
    quota_exhausted:  { fg:'var(--status-failed-fg)', bg:'var(--status-failed-bg)', label:'quota_exhausted',desc:'配额打满导致提前终止' },
    degraded:         { fg:'var(--status-warn-fg)',   bg:'var(--status-warn-bg)',   label:'degraded',       desc:'部分失败但结果仍可用' },
  }[sessionClass];

  const isWarn = sessionClass !== 'productive';

  return (
    <div style={{
      background:'var(--surface-raised)',
      border:`1px solid ${isWarn ? 'color-mix(in oklch, var(--status-warn-dot) 30%, var(--border-default))' : 'var(--border-default)'}`,
      borderRadius:'var(--r-4)',
      overflow:'hidden',
      ...style,
    }}>
      {/* top banner */}
      <div style={{
        display:'flex', alignItems:'center', gap:14,
        padding:'14px 18px',
        background: classInfo.bg,
        borderBottom:`1px solid ${classInfo.fg}22`,
      }}>
        {isWarn && (
          <svg width="22" height="22" viewBox="0 0 22 22" style={{color: classInfo.fg}}>
            <path d="M11 3 L20 18 L2 18 Z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/>
            <rect x="10.2" y="8" width="1.6" height="5" fill="currentColor"/>
            <circle cx="11" cy="15" r="1" fill="currentColor"/>
          </svg>
        )}
        <div style={{flex:1}}>
          <div style={{display:'flex', alignItems:'center', gap:8}}>
            <span style={{
              fontFamily:'var(--font-mono)', fontSize:13, fontWeight:600,
              padding:'2px 8px', borderRadius:'var(--r-2)',
              background:classInfo.fg, color:'var(--neutral-0)',
            }}>{classInfo.label}</span>
            <span style={{fontSize:13, color:classInfo.fg, fontWeight:500}}>{classInfo.desc}</span>
          </div>
        </div>
      </div>

      {/* body */}
      <div style={{padding:'18px 20px', display:'grid', gridTemplateColumns:'200px 1fr', gap: 28}}>
        {/* consistency ring */}
        <div style={{display:'flex', flexDirection:'column', alignItems:'center', gap:8}}>
          <ConsistencyRing value={consistency}/>
          <div style={{fontSize:11, color:'var(--text-muted)', textAlign:'center'}}>
            effective<br/>consistency
          </div>
        </div>

        <div style={{display:'flex', flexDirection:'column', gap:16}}>
          {/* 5 色失败矩阵 */}
          <div>
            <div style={{fontSize:11, textTransform:'uppercase', letterSpacing:.8, color:'var(--text-muted)', fontWeight:600, marginBottom:8}}>
              失败分类 · 5 色
            </div>
            <div style={{display:'grid', gridTemplateColumns:'repeat(5, 1fr)', gap:10}}>
              {[
                ['quota_exhausted',  '--fail-quota',   '配额'],
                ['tool_call_failed', '--fail-tool',    '工具'],
                ['json_parse_error', '--fail-json',    'JSON'],
                ['empty_submission', '--fail-empty',   '空提交'],
                ['timeout',          '--fail-timeout', '超时'],
              ].map(([code, tok, label]) => {
                const n = failures[code] || 0;
                return (
                  <div key={code} style={{
                    padding:'10px 12px',
                    background:`color-mix(in oklch, var(${tok}) 10%, var(--surface-sunken))`,
                    border:`1px solid color-mix(in oklch, var(${tok}) 24%, var(--border-subtle))`,
                    borderRadius:'var(--r-3)',
                  }}>
                    <div style={{
                      fontSize:22, fontWeight:600, color:`var(${tok})`,
                      fontVariantNumeric:'tabular-nums', lineHeight:1,
                    }}>{n}</div>
                    <div style={{fontSize:11, color:'var(--text-default)', marginTop:4}}>{label}</div>
                    <div style={{fontSize:10, fontFamily:'var(--font-mono)', color:'var(--text-faint)', marginTop:2}}>{code}</div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 5 鸟健康度矩阵 */}
          <div>
            <div style={{fontSize:11, textTransform:'uppercase', letterSpacing:.8, color:'var(--text-muted)', fontWeight:600, marginBottom:8}}>
              5 鸟健康度
            </div>
            <div style={{display:'grid', gridTemplateColumns:'repeat(5, 1fr)', gap:10}}>
              {birds.map((b) => <BirdHealth key={b.id} {...b}/>)}
            </div>
          </div>
        </div>
      </div>

      {/* CTA */}
      <div style={{
        display:'flex', alignItems:'center', justifyContent:'space-between', gap:12,
        padding:'12px 18px',
        borderTop:'1px solid var(--border-default)',
        background:'var(--surface-sunken)',
      }}>
        <div style={{fontSize:12, color:'var(--text-muted)'}}>
          {sessionClass === 'partial_silent'
            ? '⚠ 必须二选一：继续会在不完整结果上决策，建议重跑失败 worker'
            : '两项操作可选，继续不会再次触发预检'}
        </div>
        <div style={{display:'flex', gap:8}}>
          <button onClick={onRetry} style={btnSecondary}>重跑失败 worker</button>
          <button onClick={onContinue} style={{
            ...btnPrimary,
            opacity: sessionClass === 'partial_silent' ? 0.85 : 1,
          }}>继续 Phase 3 →</button>
        </div>
      </div>
    </div>
  );
}

function ConsistencyRing({ value }) {
  const pct = Math.round(value * 100);
  const R = 54, C = 2 * Math.PI * R;
  const offset = C * (1 - value);
  const color = value >= 0.9 ? 'var(--status-done-dot)'
              : value >= 0.7 ? 'var(--status-warn-dot)'
              : 'var(--status-failed-dot)';
  return (
    <svg width="130" height="130" viewBox="0 0 130 130">
      <circle cx="65" cy="65" r={R} fill="none" stroke="var(--neutral-150)" strokeWidth="8"/>
      <circle cx="65" cy="65" r={R} fill="none" stroke={color} strokeWidth="8"
        strokeDasharray={C} strokeDashoffset={offset} strokeLinecap="round"
        transform="rotate(-90 65 65)"/>
      <text x="65" y="68" textAnchor="middle" fontSize="26" fontWeight="600"
        fill="var(--text-strong)" fontFamily="var(--font-mono)">
        {pct}<tspan fontSize="14" fill="var(--text-muted)">%</tspan>
      </text>
    </svg>
  );
}

function BirdHealth({ id, runs = 0, fails = 0, submissions = 0 }) {
  const healthy = fails === 0;
  return (
    <div style={{
      display:'flex', flexDirection:'column', gap:6,
      padding:'10px 12px',
      background:'var(--surface-sunken)',
      border:`1px solid ${healthy ? 'var(--border-subtle)' : 'color-mix(in oklch, var(--status-failed-dot) 24%, var(--border-subtle))'}`,
      borderRadius:'var(--r-3)',
    }}>
      <div style={{display:'flex', alignItems:'center', gap:8}}>
        <BirdAvatar id={id} size="md" status={healthy ? 'done' : 'failed'}/>
        <span style={{fontSize:12, fontWeight:600, color:'var(--text-strong)'}}>{(BIRD_META[id]||{}).label}鸟</span>
      </div>
      <div style={{
        display:'flex', gap:10, fontFamily:'var(--font-mono)', fontSize:10,
        color:'var(--text-muted)', fontVariantNumeric:'tabular-nums',
      }}>
        <span><span style={{opacity:.6}}>runs</span> {runs}</span>
        <span style={{color: fails ? 'var(--status-failed-fg)' : 'inherit'}}>
          <span style={{opacity:.6}}>fails</span> {fails}
        </span>
        <span><span style={{opacity:.6}}>subs</span> {submissions}</span>
      </div>
    </div>
  );
}

const btnPrimary = {
  padding:'7px 14px', border:0, borderRadius:'var(--r-3)',
  background:'var(--accent-500)', color:'var(--accent-fg)',
  fontSize: 12, fontWeight: 600, cursor:'pointer',
  fontFamily:'var(--font-sans)',
};
const btnSecondary = {
  padding:'7px 14px', border:'1px solid var(--border-default)', borderRadius:'var(--r-3)',
  background:'var(--surface-raised)', color:'var(--text-default)',
  fontSize: 12, fontWeight: 500, cursor:'pointer',
  fontFamily:'var(--font-sans)',
};

Object.assign(window, { RunHealthCheck, ConsistencyRing, BirdHealth });
