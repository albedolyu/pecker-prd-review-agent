// AgentStatusCard · Phase 2 核心
// 头像 + BirdBadge + 状态灯 + 进度条 + mono 元数据 + 失败 recovery action
// 四态：queued / running / done / failed；meta 卡支持额外的 waiting / crossing / supplementing 子态

function AgentStatusCard({
  birdId = 1,
  status = 'queued',
  progress = 0,            // 0-100
  tokens,                  // e.g. "2.1k"
  elapsed,                 // e.g. "12.4s"
  model = 'sonnet-4-6',
  submissions,             // e.g. 3
  note,                    // 子状态文案（苍鹰用：等待 worker 完成 / 交叉校验中 / 漏报补充 3/5）
  failReason,              // quota_exhausted | tool_call_failed | json_parse_error | empty_submission | timeout
  variant = 'worker',      // worker | meta
  onRetry,
  style = {},
}) {
  const meta = BIRD_META[birdId];
  const isMeta = variant === 'meta';
  const showProgress = status === 'running';
  const isFailed = status === 'failed';

  return (
    <div style={{
      position: 'relative',
      background: 'var(--surface-raised)',
      border: `1px solid ${isFailed ? 'color-mix(in oklch, var(--status-failed-dot) 30%, var(--border-default))' : 'var(--border-default)'}`,
      borderRadius: 'var(--r-4)',
      padding: '14px 16px',
      minWidth: isMeta ? 520 : 220,
      width: '100%',
      boxShadow: status === 'running' ? 'var(--shadow-sm)' : 'none',
      display: 'flex', flexDirection: 'column', gap: 10,
      ...style,
    }}>
      {/* 顶行：头像 + 名 + 状态 */}
      <div style={{ display:'flex', alignItems:'center', gap: 10 }}>
        <BirdAvatar id={birdId} size="lg" status={statusForDot(status)} />
        <div style={{ display:'flex', flexDirection:'column', minWidth:0, flex:1 }}>
          <div style={{ display:'flex', alignItems:'center', gap:6 }}>
            <span style={{ fontSize:14, fontWeight:600, color:'var(--text-strong)' }}>{meta.label}鸟</span>
            {isMeta && <MetaTag/>}
          </div>
          <span style={{ fontSize:12, color:'var(--text-muted)', marginTop:1 }}>
            {functionOf(birdId)}
          </span>
        </div>
        <StatusPill status={status} note={note}/>
      </div>

      {/* 进度条（仅 running） */}
      {showProgress && (
        <div style={{
          height: 4, background:'var(--neutral-100)',
          borderRadius: 'var(--r-2)', overflow:'hidden', position:'relative',
        }}>
          <div style={{
            width: `${progress}%`, height:'100%',
            background:'var(--accent-500)',
            transition: 'width var(--dur-slow) var(--ease-out)',
          }}/>
          <div style={{
            position:'absolute', top:0, left:`${progress}%`, height:'100%',
            width:40, marginLeft:-40,
            background:'linear-gradient(90deg, transparent, color-mix(in oklch, var(--accent-500) 60%, transparent))',
          }}/>
        </div>
      )}

      {/* 元数据行（mono） */}
      <div style={{
        display:'flex', flexWrap:'wrap', gap: '4px 12px',
        fontFamily:'var(--font-mono)', fontSize: 11,
        color:'var(--text-muted)',
        fontVariantNumeric:'tabular-nums',
      }}>
        <MetaChip k="model" v={model} />
        {tokens &&      <MetaChip k="tokens" v={tokens}/>}
        {elapsed &&     <MetaChip k="t" v={elapsed}/>}
        {submissions != null && <MetaChip k="subs" v={submissions}/>}
        {isFailed && failReason && <MetaChip k="err" v={failReason} emph />}
      </div>

      {/* 失败恢复 */}
      {isFailed && (
        <div style={{
          display:'flex', alignItems:'center', justifyContent:'space-between',
          padding:'8px 10px',
          background:'var(--status-failed-bg)',
          borderRadius:'var(--r-3)',
          border:'1px solid color-mix(in oklch, var(--status-failed-dot) 20%, transparent)',
          fontSize:12, color:'var(--status-failed-fg)',
        }}>
          <span>
            {failMessage(failReason)}
          </span>
          <button onClick={onRetry} style={{
            padding:'4px 10px', border:0, borderRadius:'var(--r-3)',
            background:'var(--status-failed-fg)', color:'var(--neutral-0)',
            fontSize:11, fontWeight:600, cursor:'pointer',
            fontFamily:'inherit',
          }}>重跑</button>
        </div>
      )}

      {/* 依赖锚点 · worker 底部 · meta 顶部 */}
      {!isMeta && (
        <span className="worker-anchor" style={{
          position:'absolute', left:'50%', bottom:-5, transform:'translateX(-50%)',
          width:8, height:8, borderRadius:'50%',
          background: status === 'done' ? 'var(--status-done-dot)' : 'var(--neutral-300)',
          border:'2px solid var(--surface-canvas)',
        }}/>
      )}
      {isMeta && (
        <span className="meta-anchor" style={{
          position:'absolute', left:'50%', top:-6, transform:'translateX(-50%) rotate(45deg)',
          width:10, height:10,
          background: status === 'queued' ? 'var(--neutral-200)' : 'var(--bird-5)',
          border:'2px solid var(--surface-canvas)',
        }}/>
      )}
    </div>
  );
}

// ── helpers ─────────────────────────────────────────────
function statusForDot(s) {
  return s === 'done' ? 'done'
       : s === 'failed' ? 'failed'
       : s === 'running' ? 'running'
       : 'queued';
}
function functionOf(id) {
  return ({
    1:'业务逻辑完整性', 2:'数据字段 / 指标', 3:'UX 流程 / 交互', 4:'风险 / 合规 / 依赖',
    5:'交叉校验 + 漏报补充',
  })[id] || '未上线';
}
function failMessage(r) {
  return ({
    quota_exhausted:  '配额已打满',
    tool_call_failed: '工具调用失败',
    json_parse_error: '输出 JSON 解析错误',
    empty_submission: '空提交（静默失败）',
    timeout:          '调用超时',
  })[r] || '失败';
}

function MetaTag() {
  return <span style={{
    fontFamily:'var(--font-mono)', fontSize:10, fontWeight:500,
    padding:'1px 5px', borderRadius:'var(--r-2)',
    background:'color-mix(in oklch, var(--bird-5) 15%, transparent)',
    color:'var(--bird-5)', letterSpacing: 0.3,
  }}>META</span>;
}

function MetaChip({ k, v, emph }) {
  return (
    <span style={{ display:'inline-flex', gap:4 }}>
      <span style={{ opacity:.55 }}>{k}</span>
      <span style={{ color: emph ? 'var(--status-failed-fg)' : 'var(--text-default)', fontWeight: emph ? 600 : 500 }}>{v}</span>
    </span>
  );
}

function StatusPill({ status, note }) {
  const map = {
    queued:  { bg:'var(--status-queued-bg)',  fg:'var(--status-queued-fg)',  label: note || '排队中' },
    running: { bg:'var(--status-running-bg)', fg:'var(--status-running-fg)', label: note || '运行中' },
    done:    { bg:'var(--status-done-bg)',    fg:'var(--status-done-fg)',    label: note || '完成' },
    failed:  { bg:'var(--status-failed-bg)',  fg:'var(--status-failed-fg)',  label: note || '失败' },
  }[status] || {};
  return (
    <span style={{
      display:'inline-flex', alignItems:'center', gap:6,
      padding:'3px 9px', borderRadius:'var(--r-pill)',
      background: map.bg, color: map.fg,
      fontSize: 11, fontWeight: 600, whiteSpace:'nowrap',
    }}>
      <StatusDot status={status} size={6}/>
      {map.label}
    </span>
  );
}

Object.assign(window, { AgentStatusCard, StatusPill, MetaChip });
