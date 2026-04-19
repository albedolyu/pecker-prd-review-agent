// CommentThread · Phase 3 最高频组件
// 鸟头像 + 职能 + 苍鹰验证徽章 + 评审正文 + EvidenceBlock + mono 元数据 + 操作
// 规则：验证失败默认折叠 · confidence < 0.7 弱化

function CommentThread({
  birdId = 1,
  eagleMark = 'passed',    // passed | revoked | added | null
  dimension,
  title,
  body,
  evidence,                // {quote, source, verification}
  meta = {},               // {model, conf, tokens, rule}
  collapsedByDefault,
  selected = false,
  accepted,                // true | false | undefined
  style = {},
}) {
  const isFail = evidence?.verification === 'failed';
  const lowConf = meta.conf != null && meta.conf < 0.7;
  const shouldCollapse = collapsedByDefault ?? isFail;
  const [collapsed, setCollapsed] = React.useState(shouldCollapse);
  const fade = isFail || lowConf;

  return (
    <article style={{
      background: selected ? 'color-mix(in oklch, var(--accent-500) 6%, var(--surface-raised))' : 'var(--surface-raised)',
      border: `1px solid ${selected ? 'color-mix(in oklch, var(--accent-500) 35%, var(--border-default))' : 'var(--border-default)'}`,
      borderLeft: selected ? '2px solid var(--accent-500)' : undefined,
      borderRadius:'var(--r-4)',
      padding: '12px 14px',
      display:'flex', flexDirection:'column', gap: 10,
      opacity: accepted === false ? 0.55 : (fade && collapsed ? 0.7 : 1),
      ...style,
    }}>
      {/* top row */}
      <div style={{display:'flex', alignItems:'center', gap:10}}>
        <BirdAvatar id={birdId} size="md"/>
        <div style={{flex:1, minWidth:0}}>
          <div style={{display:'flex', alignItems:'center', gap:6, flexWrap:'wrap'}}>
            <span style={{fontSize:13, fontWeight:600, color:'var(--text-strong)'}}>
              {(BIRD_META[birdId]||{}).label}鸟
            </span>
            {dimension && <span style={{
              fontSize:11, padding:'1px 6px', borderRadius:'var(--r-2)',
              background:'var(--neutral-100)', color:'var(--text-muted)',
            }}>{dimension}</span>}
            {eagleMark && <EagleMark kind={eagleMark}/>}
            {accepted === true && <span style={acceptedChip}>已接受</span>}
            {accepted === false && <span style={rejectedChip}>已拒绝</span>}
          </div>
        </div>
        {fade && (
          <button onClick={() => setCollapsed(c=>!c)} style={linkBtn}>
            {collapsed ? '展开' : '折叠'}
          </button>
        )}
      </div>

      {/* title */}
      {title && (
        <div style={{
          fontSize: 14, fontWeight: 500, color: 'var(--text-strong)',
          lineHeight: 1.5, textWrap:'pretty',
        }}>{title}</div>
      )}

      {!collapsed && <>
        {/* body */}
        {body && (
          <div style={{
            fontSize: 13, color:'var(--text-default)', lineHeight: 1.6,
          }}>{body}</div>
        )}

        {/* evidence */}
        {evidence && <EvidenceBlock {...evidence}/>}

        {/* meta */}
        <div style={{
          display:'flex', flexWrap:'wrap', gap:'3px 12px',
          fontFamily:'var(--font-mono)', fontSize: 11,
          color:'var(--text-muted)', fontVariantNumeric:'tabular-nums',
        }}>
          {meta.model  && <MetaChip k="model" v={meta.model}/>}
          {meta.conf   != null && <MetaChip k="conf"  v={meta.conf.toFixed(2)} emph={lowConf}/>}
          {meta.tokens && <MetaChip k="tokens" v={meta.tokens}/>}
          {meta.rule   && <MetaChip k="rule"  v={meta.rule}/>}
        </div>

        {/* actions */}
        <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', gap:8, marginTop:2}}>
          <div style={{display:'flex', gap:6}}>
            <button style={btnAccept} disabled={accepted===true}>接受</button>
            <button style={btnReject} disabled={accepted===false}>拒绝</button>
            <button style={btnEdit}>编辑</button>
          </div>
          <div style={{display:'flex', gap:8, alignItems:'center'}}>
            <ShortcutHint keys={['y']} label="接受"/>
            <ShortcutHint keys={['n']} label="拒绝"/>
          </div>
        </div>
      </>}

      {collapsed && fade && (
        <div style={{
          fontSize: 11, color:'var(--text-muted)',
          padding:'2px 0',
        }}>
          {isFail ? '依据验证失败 · 需展开确认后才能接受' : '置信度偏低 · 已弱化'}
        </div>
      )}
    </article>
  );
}

function EagleMark({ kind }) {
  const map = {
    passed:  { icon:'✓', bg:'color-mix(in oklch, var(--bird-5) 10%, var(--surface-sunken))',
               fg:'var(--bird-5)', label:'苍鹰通过' },
    revoked: { icon:'⊖', bg:'var(--status-failed-bg)', fg:'var(--status-failed-fg)', label:'苍鹰撤回' },
    added:   { icon:'＋', bg:'color-mix(in oklch, var(--bird-5) 10%, var(--surface-sunken))',
               fg:'var(--bird-5)', label:'苍鹰补充' },
  }[kind];
  return (
    <span style={{
      display:'inline-flex', alignItems:'center', gap:4,
      padding:'1px 7px', borderRadius:'var(--r-pill)',
      background: map.bg, color: map.fg,
      fontSize: 11, fontWeight: 600,
    }}>
      <span style={{fontSize:10, lineHeight:1}}>{map.icon}</span>
      {map.label}
    </span>
  );
}

const linkBtn = {
  background:'transparent', border:0, color:'var(--text-link)',
  fontSize:11, cursor:'pointer', padding:0, fontFamily:'var(--font-sans)', fontWeight:500,
};
const btnAccept = {
  padding:'5px 12px', border:0, borderRadius:'var(--r-3)',
  background:'var(--accent-500)', color:'var(--accent-fg)',
  fontSize: 12, fontWeight: 600, cursor:'pointer', fontFamily:'var(--font-sans)',
};
const btnReject = {
  padding:'5px 12px', border:'1px solid var(--border-default)', borderRadius:'var(--r-3)',
  background:'var(--surface-raised)', color:'var(--text-default)',
  fontSize: 12, fontWeight: 500, cursor:'pointer', fontFamily:'var(--font-sans)',
};
const btnEdit = {
  ...btnReject, color:'var(--text-muted)',
};
const acceptedChip = {
  fontSize:10, padding:'1px 6px', borderRadius:'var(--r-2)',
  background:'var(--status-done-bg)', color:'var(--status-done-fg)', fontWeight:600,
};
const rejectedChip = {
  fontSize:10, padding:'1px 6px', borderRadius:'var(--r-2)',
  background:'var(--neutral-100)', color:'var(--text-muted)', fontWeight:600,
};

Object.assign(window, { CommentThread, EagleMark });
