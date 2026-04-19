// RunDiff · 管理页 Run 对比
// 左右分栏：run A vs run B，同一 PRD 的两次 run 结果对比
// 顶栏显示两个 run 的元信息；每个评审项按 anchor 对齐，展示 added / removed / unchanged / changed

function RunDiff({
  runA = {},   // {id, time, session, commentCount, acceptRate}
  runB = {},
  rows = [],   // [{anchor, dimension, birdId, a, b, change}]
  style = {},
}) {
  const counts = rows.reduce((acc, r) => { acc[r.change] = (acc[r.change]||0)+1; return acc; }, {});
  return (
    <div style={{
      background:'var(--surface-raised)',
      border:'1px solid var(--border-default)',
      borderRadius:'var(--r-4)',
      display:'flex', flexDirection:'column',
      overflow:'hidden',
      ...style,
    }}>
      {/* header */}
      <div style={{
        display:'grid', gridTemplateColumns:'1fr 1fr',
        borderBottom:'1px solid var(--border-default)',
      }}>
        <RunHeader run={runA} side="A"/>
        <RunHeader run={runB} side="B" rightBorder/>
      </div>

      {/* summary */}
      <div style={{
        display:'flex', gap:12, padding:'10px 16px',
        background:'var(--surface-sunken)',
        borderBottom:'1px solid var(--border-default)',
        fontSize: 12,
      }}>
        <DiffCountChip kind="added"     n={counts.added||0}/>
        <DiffCountChip kind="removed"   n={counts.removed||0}/>
        <DiffCountChip kind="changed"   n={counts.changed||0}/>
        <DiffCountChip kind="unchanged" n={counts.unchanged||0}/>
        <span style={{marginLeft:'auto', fontFamily:'var(--font-mono)', fontSize:11, color:'var(--text-muted)'}}>
          {rows.length} rows
        </span>
      </div>

      {/* body */}
      <div style={{ flex:1, overflow:'auto' }}>
        {rows.map((r, i) => <DiffRow key={i} row={r}/>)}
      </div>
    </div>
  );
}

function RunHeader({ run, side, rightBorder }) {
  return (
    <div style={{
      padding:'12px 16px',
      borderRight: rightBorder ? undefined : '1px solid var(--border-default)',
      display:'flex', flexDirection:'column', gap:4,
    }}>
      <div style={{display:'flex', alignItems:'center', gap:8}}>
        <span style={{
          display:'inline-flex', alignItems:'center', justifyContent:'center',
          width:20, height:20, borderRadius:'var(--r-2)',
          background: side === 'A' ? 'var(--neutral-800)' : 'var(--accent-500)',
          color: side === 'A' ? 'var(--neutral-0)' : 'var(--accent-fg)',
          fontFamily:'var(--font-mono)', fontSize: 11, fontWeight:700,
        }}>{side}</span>
        <span style={{fontFamily:'var(--font-mono)', fontSize:12, color:'var(--text-strong)', fontWeight:600}}>
          {run.id}
        </span>
        {run.session && (
          <span style={{
            fontSize:10, padding:'1px 6px', borderRadius:'var(--r-2)',
            background: run.session === 'productive' ? 'var(--status-done-bg)' : 'var(--status-warn-bg)',
            color:     run.session === 'productive' ? 'var(--status-done-fg)' : 'var(--status-warn-fg)',
            fontWeight:600, fontFamily:'var(--font-mono)',
          }}>{run.session}</span>
        )}
      </div>
      <div style={{
        fontSize:11, fontFamily:'var(--font-mono)', color:'var(--text-muted)',
        display:'flex', gap:14,
      }}>
        <span>{run.time}</span>
        <span>{run.commentCount} comments</span>
        <span>{run.acceptRate}% accept</span>
      </div>
    </div>
  );
}

function DiffCountChip({ kind, n }) {
  const map = {
    added:     { bg:'var(--status-done-bg)',   fg:'var(--status-done-fg)',   sign:'+', label:'added' },
    removed:   { bg:'var(--status-failed-bg)', fg:'var(--status-failed-fg)', sign:'−', label:'removed' },
    changed:   { bg:'var(--status-warn-bg)',   fg:'var(--status-warn-fg)',   sign:'≠', label:'changed' },
    unchanged: { bg:'var(--neutral-100)',      fg:'var(--text-muted)',       sign:'=', label:'unchanged' },
  }[kind];
  return (
    <span style={{
      display:'inline-flex', alignItems:'center', gap:5,
      padding:'3px 9px', borderRadius:'var(--r-pill)',
      background: map.bg, color: map.fg,
      fontSize: 11, fontWeight: 600,
    }}>
      <span style={{fontFamily:'var(--font-mono)', fontSize:10}}>{map.sign}</span>
      <span style={{fontFamily:'var(--font-mono)', fontVariantNumeric:'tabular-nums'}}>{n}</span>
      {map.label}
    </span>
  );
}

function DiffRow({ row }) {
  const { anchor, dimension, birdId, a, b, change } = row;
  const bg = {
    added:     'color-mix(in oklch, var(--status-done-dot) 6%, transparent)',
    removed:   'color-mix(in oklch, var(--status-failed-dot) 6%, transparent)',
    changed:   'color-mix(in oklch, var(--status-warn-dot) 6%, transparent)',
    unchanged: 'transparent',
  }[change];
  const sign = { added:'+', removed:'−', changed:'≠', unchanged:' ' }[change];
  const signColor = {
    added:'var(--status-done-fg)', removed:'var(--status-failed-fg)',
    changed:'var(--status-warn-fg)', unchanged:'var(--text-faint)',
  }[change];

  return (
    <div style={{
      display:'grid', gridTemplateColumns:'32px 1fr 1fr',
      borderBottom:'1px solid var(--border-subtle)',
      background: bg,
      fontSize: 12,
    }}>
      <div style={{
        padding:'10px 0', textAlign:'center',
        fontFamily:'var(--font-mono)', fontWeight:700,
        color: signColor,
        borderRight:'1px solid var(--border-subtle)',
      }}>{sign}</div>
      <DiffCell data={change === 'added' ? null : a} birdId={birdId} dimension={dimension} anchor={anchor} faded={change === 'removed'}/>
      <DiffCell data={change === 'removed' ? null : b} birdId={birdId} dimension={dimension} anchor={anchor} emph={change !== 'unchanged'} rightBorder/>
    </div>
  );
}

function DiffCell({ data, birdId, dimension, anchor, faded, emph, rightBorder }) {
  if (!data) {
    return (
      <div style={{
        padding:'10px 14px',
        borderRight: rightBorder ? undefined : '1px solid var(--border-subtle)',
        color:'var(--text-faint)', fontStyle:'italic', fontSize: 12,
      }}>—</div>
    );
  }
  return (
    <div style={{
      padding:'10px 14px',
      borderRight: rightBorder ? undefined : '1px solid var(--border-subtle)',
      opacity: faded ? 0.55 : 1,
    }}>
      <div style={{display:'flex', alignItems:'center', gap:8, marginBottom:4}}>
        <BirdAvatar id={birdId} size="sm"/>
        <span style={{fontSize:11, color:'var(--text-muted)', fontWeight:500}}>
          {(BIRD_META[birdId]||{}).label}鸟 · {dimension}
        </span>
        <span style={{
          marginLeft:'auto', fontFamily:'var(--font-mono)', fontSize:10, color:'var(--text-faint)',
        }}>{anchor}</span>
      </div>
      <div style={{
        fontSize: 13, color:'var(--text-default)', lineHeight:1.5,
        fontWeight: emph ? 500 : 400,
      }}>{data.title}</div>
      <div style={{
        marginTop:4, display:'flex', gap:10,
        fontFamily:'var(--font-mono)', fontSize:10, color:'var(--text-muted)',
      }}>
        {data.conf != null && <span><span style={{opacity:.6}}>conf</span> {data.conf.toFixed(2)}</span>}
        {data.rule && <span><span style={{opacity:.6}}>rule</span> {data.rule}</span>}
        {data.accepted != null && <span style={{color: data.accepted ? 'var(--status-done-fg)' : 'var(--text-muted)'}}>
          {data.accepted ? '✓ 已接受' : '○ 未接受'}
        </span>}
      </div>
    </div>
  );
}

Object.assign(window, { RunDiff, DiffRow, DiffCountChip });
