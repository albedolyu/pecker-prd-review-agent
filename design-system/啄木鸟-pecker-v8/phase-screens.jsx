// Phase 整屏稿 · 把 6 个 Phase 的 hi-fi layout 都铺在一个文件里
// 每个 screen 都是 1440 × 900 的固定尺寸，方便放入 design canvas 艺术板

function Phase0Upload() {
  return (
    <ScreenShell current={0} completed={[]}>
      <div style={{
        flex:1, display:'flex', alignItems:'center', justifyContent:'center',
        padding: '48px 24px',
      }}>
        <div style={{ width: 640, display:'flex', flexDirection:'column', gap: 20 }}>
          <div>
            <div style={{fontSize:20, fontWeight:600, color:'var(--text-strong)'}}>接入 PRD</div>
            <div style={{fontSize:13, color:'var(--text-muted)', marginTop:4}}>
              上传文档 · 10 只鸟并行评审 · 全流程 ~3 分钟
            </div>
          </div>
          <div style={{
            border:'1.5px dashed var(--border-strong)',
            borderRadius:'var(--r-4)',
            padding:'40px 24px',
            background:'var(--surface-sunken)',
            textAlign:'center',
          }}>
            <div style={{fontSize:13, color:'var(--text-default)', marginBottom: 4, fontWeight:500}}>
              拖入 PRD 文档
            </div>
            <div style={{fontSize:11, color:'var(--text-muted)', fontFamily:'var(--font-mono)'}}>
              .md · .docx · 飞书文档链接
            </div>
            <button style={{
              marginTop:16, padding:'8px 18px', border:0, borderRadius:'var(--r-3)',
              background:'var(--accent-500)', color:'var(--accent-fg)',
              fontSize:12, fontWeight:600, cursor:'pointer', fontFamily:'var(--font-sans)',
            }}>选择文件</button>
          </div>
          <FormRow label="Workspace">
            <select style={selectStyle}>
              <option>电商 · C 端 · workspace-alpha</option>
            </select>
          </FormRow>
          <FormRow label="评审模式">
            <div style={{display:'flex', gap:8}}>
              <ModeCard selected label="完整评审" meta="5 鸟 + 苍鹰 · ~3min"/>
              <ModeCard label="快速扫查" meta="2 鸟 · ~45s"/>
              <ModeCard label="自定义" meta="选鸟"/>
            </div>
          </FormRow>
        </div>
      </div>
    </ScreenShell>
  );
}

function FormRow({ label, children }) {
  return (
    <div>
      <div style={{fontSize:11, fontWeight:600, textTransform:'uppercase', letterSpacing:.6, color:'var(--text-muted)', marginBottom:6}}>{label}</div>
      {children}
    </div>
  );
}
const selectStyle = {
  width:'100%', padding:'8px 10px', fontSize:13,
  border:'1px solid var(--border-default)', borderRadius:'var(--r-3)',
  background:'var(--surface-raised)', color:'var(--text-default)', fontFamily:'var(--font-sans)',
};
function ModeCard({ selected, label, meta }) {
  return (
    <div style={{
      flex:1, padding:'10px 12px', borderRadius:'var(--r-3)',
      border: `1px solid ${selected ? 'var(--accent-500)' : 'var(--border-default)'}`,
      background: selected ? 'color-mix(in oklch, var(--accent-500) 6%, var(--surface-raised))' : 'var(--surface-raised)',
      cursor:'pointer',
    }}>
      <div style={{fontSize:12, fontWeight:600, color:'var(--text-strong)'}}>{label}</div>
      <div style={{fontSize:10, color:'var(--text-muted)', fontFamily:'var(--font-mono)', marginTop:3}}>{meta}</div>
    </div>
  );
}

// ───── Phase 1 · 盲区预检 ─────
function Phase1Blindspots() {
  return (
    <ScreenShell current={1} completed={[0]}>
      <div style={{flex:1, padding:'20px 24px', overflow:'hidden', display:'flex', flexDirection:'column', gap: 16}}>
        <div style={{
          display:'flex', alignItems:'center', gap:12,
          padding:'10px 14px',
          background:'var(--surface-sunken)',
          border:'1px solid var(--border-default)',
          borderRadius:'var(--r-4)',
          fontSize:12,
        }}>
          <span style={{fontWeight:600, color:'var(--text-strong)'}}>知识盲区预检 · 完成</span>
          <SummaryChip kind="strong" n={14}/>
          <SummaryChip kind="weak"   n={6}/>
          <SummaryChip kind="gap"    n={3}/>
          <span style={{marginLeft:'auto', fontSize:11, fontFamily:'var(--font-mono)', color:'var(--text-muted)'}}>
            1.2s · gpt-5
          </span>
          <button style={{...btnStyles.primary, fontSize:11, padding:'5px 12px'}}>继续 Phase 2 →</button>
        </div>

        <div style={{flex:1, minHeight:0}}>
          <DocumentView
            style={{height:'100%'}}
            title="PRD · 电商购物车支付优化 v2.3"
            subtitle="prd-0847 · 2026-04-16"
            summary={{strong:14, weak:6, gaps:3}}
            blocks={demoBlocks()}/>
        </div>
      </div>
    </ScreenShell>
  );
}

function demoBlocks() {
  return [
    { type:'h',  content:'1 · 背景' },
    { type:'p',  content:'当前购物车转化率为 62%，支付页跳失率 18%，需在 Q2 将综合转化率提升至 70%。',
      highlights:[{kind:'strong', start:8, end:14, anchor:'m1'}, {kind:'weak', start:24, end:29, anchor:'m2'}] },
    { type:'h',  content:'2 · 目标用户' },
    { type:'p',  content:'A. 高频购买用户（月 ≥ 3 单）· B. 跨设备购物用户 · C. 国际订单用户（新增）。',
      highlights:[{kind:'gap', start:28, end:38, anchor:'m3'}] },
    { type:'h',  content:'3 · 功能需求' },
    { type:'li', content:'支持 Apple Pay / Google Pay / 支付宝国际版 三种支付方式并行',
      highlights:[{kind:'strong', start:4, end:24, anchor:'m4'}] },
    { type:'li', content:'跨设备购物车同步（本地缓存 → 云端 → 多端），需要处理冲突合并逻辑',
      highlights:[{kind:'weak', start:0, end:14, anchor:'m5'}] },
    { type:'li', content:'支付失败后自动重试 3 次（无指数退避规则）· 但未定义失败日志如何落库',
      highlights:[{kind:'gap', start:14, end:24, anchor:'m6'}] },
    { type:'h',  content:'4 · 指标' },
    { type:'li', content:'北极星：综合转化率 62% → 70%（+8pp）' },
    { type:'li', content:'护栏：支付失败率 ≤ 2.5% · 页面 P95 ≤ 1.8s' },
  ];
}

// ───── Phase 1.5 · 运行质量检查 ─────
function Phase1_5() {
  return (
    <ScreenShell current={1.5} completed={[0,1,2]}>
      <div data-phase2 style={{flex:1, padding:'20px 24px', overflow:'auto', background:'var(--surface-canvas)'}}>
        <div style={{maxWidth: 1040, margin:'0 auto', display:'flex', flexDirection:'column', gap:16}}>
          <div>
            <div style={{fontSize:20, fontWeight:600, color:'var(--text-strong)'}}>运行质量检查</div>
            <div style={{fontSize:12, color:'var(--text-muted)', marginTop:4}}>
              不可跳过 · 避免在不完整结果上决策
            </div>
          </div>

          <RunHealthCheck
            sessionClass="partial_silent"
            consistency={0.68}
            failures={{
              quota_exhausted: 1, tool_call_failed: 0, json_parse_error: 1,
              empty_submission: 2, timeout: 0,
            }}
            birds={[
              { id:1, runs:3, fails:0, submissions:8 },
              { id:2, runs:3, fails:0, submissions:6 },
              { id:3, runs:3, fails:2, submissions:0 },   // 静默失败
              { id:4, runs:3, fails:1, submissions:2 },
              { id:5, runs:1, fails:0, submissions:4 },
            ]}
          />
        </div>
      </div>
    </ScreenShell>
  );
}

// ───── Phase 2 · 运行中 ─────
function Phase2Running() {
  return (
    <ScreenShell current={2} completed={[0,1]}>
      <div data-phase2 style={{flex:1, padding:'18px 24px', overflow:'hidden', display:'grid', gridTemplateRows:'auto auto 1fr', gap: 14, background:'var(--surface-canvas)'}}>
        <div style={{display:'flex', alignItems:'baseline', gap:10}}>
          <span style={{fontSize: 18, fontWeight:600, color:'var(--text-strong)'}}>10 鸟评审 · 运行中</span>
          <span style={{fontSize:11, fontFamily:'var(--font-mono)', color:'var(--text-muted)'}}>
            run-id · r-9a8k2f · started 00:01:14 ago
          </span>
        </div>

        {/* topology */}
        <div style={{position:'relative', height: 380}}>
          <svg viewBox="0 0 1200 380" preserveAspectRatio="none"
            style={{position:'absolute', inset:0, width:'100%', height:'100%', pointerEvents:'none'}}>
            {[150, 435, 720, 1005].map((x,i) => {
              const done = i === 2;
              return (
                <g key={i}>
                  <path d={`M${x} 180 C ${x} 250, 600 250, 600 295`}
                    fill="none"
                    stroke={done ? 'var(--accent-500)' : 'var(--neutral-300)'}
                    strokeWidth={done ? 1.8 : 1.2}
                    strokeDasharray={done ? '0' : '4 4'}/>
                  {done && <circle r="3" fill="var(--accent-500)">
                    <animateMotion dur="1.6s" repeatCount="indefinite"
                      path={`M${x} 180 C ${x} 250, 600 250, 600 295`}/>
                  </circle>}
                </g>
              );
            })}
          </svg>
          <div style={{position:'absolute', inset:'0 0 auto 0', display:'grid', gridTemplateColumns:'repeat(4, 1fr)', gap:12}}>
            <AgentStatusCard birdId={1} status="running" progress={48} tokens="1.4k" elapsed="9.1s" model="sonnet-4-6" note="分析中"/>
            <AgentStatusCard birdId={2} status="running" progress={72} tokens="2.3k" elapsed="11.8s" model="sonnet-4-6" note="分析中"/>
            <AgentStatusCard birdId={3} status="done"    tokens="3.8k" elapsed="28.1s" submissions={7} model="sonnet-4-6"/>
            <AgentStatusCard birdId={4} status="running" progress={22} tokens="0.8k" elapsed="5.4s" model="sonnet-4-6" note="分析中"/>
          </div>
          <div style={{position:'absolute', left:'50%', top: 290, transform:'translateX(-50%)', width: 560}}>
            <AgentStatusCard variant="meta" birdId={5} status="queued" note="等待 worker 完成 1/4" model="opus-4"/>
          </div>
        </div>

        {/* console */}
        <RunConsole
          style={{minHeight: 0}}
          lines={[
            { t:'00:00', src:{name:'system'}, text:'harness 启动 · 4 worker + 1 meta' },
            { t:'00:01', src:{name:'业务', bird:1}, level:'info', text:'analyzing: 3.功能需求 · 支付方式' },
            { t:'00:02', src:{name:'数据', bird:2}, level:'info', text:'extracting metric set · 综合转化率 支付失败率 P95' },
            { t:'00:04', src:{name:'体验', bird:3}, level:'info', text:'mapping user flow · onboarding → cart → pay' },
            { t:'00:08', src:{name:'风险', bird:4}, level:'info', text:'scanning dependencies · 国际支付合规' },
            { t:'00:12', src:{name:'体验', bird:3}, level:'ok',   text:'submitted 7 comments · 耗时 28.1s' },
            { t:'00:13', src:{name:'业务', bird:1}, level:'info', text:'rule R042 matched · "指标定义不完整"' },
            { t:'00:14', src:{name:'业务', bird:1}, level:'accent',text:'streaming comment draft ...' },
          ]}
        />
      </div>
    </ScreenShell>
  );
}

// ───── Phase 3 · 逐条确认 ─────
function Phase3Review() {
  const [sel, setSel] = React.useState('m3');
  return (
    <ScreenShell current={3} completed={[0,1,1.5,2]}>
      <div style={{flex:1, display:'grid', gridTemplateColumns:'1fr 480px', overflow:'hidden'}}>
        {/* LEFT · doc */}
        <div style={{borderRight:'1px solid var(--border-default)', display:'flex', flexDirection:'column', minHeight:0}}>
          <DocumentView
            style={{borderRadius:0, border:0, height:'100%'}}
            title="PRD · 电商购物车支付优化 v2.3"
            subtitle="prd-0847"
            summary={{strong:14, weak:6, gaps:3}}
            blocks={demoBlocks()}
            selectedAnchor={sel}
            onAnchorClick={setSel}
          />
        </div>

        {/* RIGHT · comments drawer */}
        <div style={{display:'flex', flexDirection:'column', background:'var(--surface-sunken)', minHeight:0}}>
          <div style={{
            padding:'12px 16px', borderBottom:'1px solid var(--border-default)',
            background:'var(--surface-raised)',
            display:'flex', alignItems:'center', gap:10,
          }}>
            <span style={{fontSize:13, fontWeight:600, color:'var(--text-strong)'}}>评审意见</span>
            <span style={{fontSize:11, fontFamily:'var(--font-mono)', color:'var(--text-muted)'}}>23 · 已接受 8 · 待处理 15</span>
            <span style={{marginLeft:'auto', display:'flex', gap:6}}>
              <button style={{...btnStyles.chip, ...btnStyles.chipActive}}>按鸟</button>
              <button style={btnStyles.chip}>按维度</button>
            </span>
          </div>

          <div style={{flex:1, overflow:'auto', padding:12, display:'flex', flexDirection:'column', gap:10}}>
            <CommentThread
              birdId={1} dimension="业务逻辑" eagleMark="passed"
              title="国际订单用户群体未定义入口路径"
              body="新增了 C 类用户，但 onboarding 流程没有区分国际订单入口，会导致首次进入 App 的国际用户仍走国内流程。"
              evidence={{
                quote:'C. 国际订单用户（新增）',
                source:'Line 4 · 2 · 目标用户',
                verification:'verified',
              }}
              meta={{model:'sonnet-4-6', conf:0.89, tokens:'1.2k', rule:'R042'}}
              selected={sel==='m3'}
            />

            <CommentThread
              birdId={4} dimension="风险" eagleMark="added"
              title="支付失败重试缺少指数退避 · 可能放大限流"
              body="3 次重试无退避容易在支付网关侧触发限流。苍鹰补充：国际支付网关的限流阈值比国内低 3 倍。"
              evidence={{
                quote:'支付失败后自动重试 3 次（无指数退避规则）',
                source:'Line 7 · 3 · 功能需求',
                verification:'verified',
              }}
              meta={{model:'sonnet-4-6', conf:0.91, tokens:'1.8k', rule:'R118'}}
            />

            <CommentThread
              birdId={2} dimension="数据" eagleMark={null}
              title="综合转化率口径未定义"
              body="『综合转化率 62% → 70%』未说明分子分母定义。建议补充：浏览→下单 / 下单→支付 / UV→GMV 三个口径。"
              evidence={{
                quote:'北极星：综合转化率 62% → 70%',
                source:'Line 9 · 4 · 指标',
                verification:'unverified',
              }}
              meta={{model:'sonnet-4-6', conf:0.64, tokens:'0.9k', rule:'R201'}}
            />

            <CommentThread
              birdId={3} dimension="体验" eagleMark="revoked"
              title="跨设备同步提示需要降噪"
              evidence={{
                quote:'跨设备购物车同步',
                source:'Line 6',
                verification:'failed',
              }}
              meta={{model:'sonnet-4-6', conf:0.51, tokens:'0.5k', rule:'R087'}}
            />

            <CommentThread
              birdId={1} dimension="业务逻辑"
              title="冲突合并策略未定义"
              body="多端同步必然产生冲突，但 PRD 没说合并策略（最后写入优先 / 本地优先 / 用户确认）。"
              evidence={{
                quote:'需要处理冲突合并逻辑',
                source:'Line 6',
                verification:'verified',
              }}
              meta={{model:'sonnet-4-6', conf:0.78, tokens:'1.1k', rule:'R133'}}
              accepted={true}
            />
          </div>

          <div style={{
            padding:'10px 14px', borderTop:'1px solid var(--border-default)',
            background:'var(--surface-raised)',
            display:'flex', alignItems:'center', gap:8,
          }}>
            <button style={btnStyles.primary}>批量接受高置信</button>
            <button style={btnStyles.secondary}>➕ 我发现一个他们漏掉的问题</button>
            <div style={{marginLeft:'auto', display:'flex', gap:12}}>
              <ShortcutHint keys={['j','k']} label="跳"/>
              <ShortcutHint keys={['y']} label="接受"/>
              <ShortcutHint keys={['n']} label="拒绝"/>
            </div>
          </div>
        </div>
      </div>
    </ScreenShell>
  );
}

// ───── Phase 4 · 报告 ─────
function Phase4Report() {
  return (
    <ScreenShell current={4} completed={[0,1,1.5,2,3]}>
      <div style={{flex:1, overflow:'auto', padding:'24px 32px', background:'var(--surface-canvas)'}}>
        <div style={{maxWidth: 920, margin:'0 auto', display:'flex', flexDirection:'column', gap: 20}}>
          <div>
            <div style={{fontSize:11, fontFamily:'var(--font-mono)', color:'var(--text-muted)', marginBottom:6}}>
              report · r-9a8k2f · 2026-04-16 14:22
            </div>
            <div style={{fontSize:24, fontWeight:600, color:'var(--text-strong)', marginBottom:4}}>
              PRD · 电商购物车支付优化 v2.3 · 评审报告
            </div>
            <div style={{fontSize:13, color:'var(--text-muted)'}}>
              5 鸟评审 + 苍鹰交叉校验 · 产出 23 条意见 · 接受 14
            </div>
          </div>

          {/* meta grid */}
          <div style={{
            display:'grid', gridTemplateColumns:'repeat(5, 1fr)', gap:12,
            padding:'14px 16px',
            background:'var(--surface-raised)',
            border:'1px solid var(--border-default)',
            borderRadius:'var(--r-4)',
          }}>
            {[
              ['耗时',       '3m 42s', 'mono'],
              ['tokens',     '21.3k'],
              ['接受率',     '60.9%'],
              ['session',    'productive', 'done'],
              ['规则触发',   '11 rules'],
            ].map(([k, v, flag]) => (
              <div key={k}>
                <div style={{fontSize:10, textTransform:'uppercase', letterSpacing:.6, color:'var(--text-muted)', fontWeight:600}}>{k}</div>
                <div style={{
                  marginTop:3,
                  fontFamily: flag === 'mono' ? 'var(--font-mono)' : 'var(--font-sans)',
                  fontSize: 18, fontWeight:600,
                  color: flag === 'done' ? 'var(--status-done-fg)' : 'var(--text-strong)',
                  fontVariantNumeric:'tabular-nums',
                }}>{v}</div>
              </div>
            ))}
          </div>

          {/* by dimension */}
          <div>
            <div style={{fontSize:14, fontWeight:600, color:'var(--text-strong)', marginBottom:8}}>按维度归类</div>
            <div style={{display:'flex', flexDirection:'column', gap:8}}>
              {[
                { id:1, d:'业务逻辑', n:7, acc:5 },
                { id:2, d:'数据字段', n:5, acc:3 },
                { id:3, d:'UX 流程',  n:4, acc:2 },
                { id:4, d:'风险合规', n:4, acc:3 },
                { id:5, d:'苍鹰补充', n:3, acc:1 },
              ].map(r => (
                <div key={r.id} style={{
                  display:'flex', alignItems:'center', gap:14,
                  padding:'10px 14px',
                  background:'var(--surface-raised)',
                  border:'1px solid var(--border-default)',
                  borderRadius:'var(--r-3)',
                }}>
                  <BirdAvatar id={r.id} size="md"/>
                  <span style={{flex:1, fontSize:13, color:'var(--text-strong)', fontWeight:500}}>{r.d}</span>
                  <span style={{fontFamily:'var(--font-mono)', fontSize:12, color:'var(--text-muted)'}}>
                    {r.acc}/{r.n} 接受
                  </span>
                  <div style={{width:140, height:6, background:'var(--neutral-100)', borderRadius:3, overflow:'hidden'}}>
                    <div style={{
                      width:`${r.acc/r.n*100}%`, height:'100%',
                      background:`var(--bird-${r.id})`,
                    }}/>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* feedback echo */}
          <div style={{
            padding:'14px 16px',
            background:'color-mix(in oklch, var(--accent-500) 7%, var(--surface-raised))',
            border:'1px solid color-mix(in oklch, var(--accent-500) 20%, var(--border-default))',
            borderRadius:'var(--r-4)',
            display:'flex', alignItems:'center', gap:14,
          }}>
            <div style={{flex:1}}>
              <div style={{fontSize:13, color:'var(--text-strong)', fontWeight:500}}>
                你的反馈本周影响了 <span style={{color:'var(--accent-600)', fontWeight:700, fontFamily:'var(--font-mono)'}}>7</span> 条规则权重
              </div>
              <div style={{fontSize:11, color:'var(--text-muted)', marginTop:3}}>
                R042 · R118 · R201 · R133 +4 · 下次相似 PRD 的评审更贴近你
              </div>
            </div>
            <button style={btnStyles.link}>查看详情 →</button>
          </div>

          {/* export */}
          <div style={{display:'flex', gap:8}}>
            <button style={btnStyles.primary}>导出 md</button>
            <button style={btnStyles.secondary}>导出到飞书</button>
            <button style={btnStyles.secondary}>PDF</button>
          </div>
        </div>
      </div>
    </ScreenShell>
  );
}

// ─── shell ─────────────────────────────────────────────
function ScreenShell({ current, completed, children }) {
  return (
    <div style={{display:'flex', flexDirection:'column', height:'100%', background:'var(--surface-canvas)'}}>
      <TopBar/>
      <PhaseNav current={current} completed={completed}/>
      {children}
    </div>
  );
}
function TopBar() {
  return (
    <div style={{
      height: 40, display:'flex', alignItems:'center', gap:12,
      padding:'0 16px', background:'var(--surface-raised)',
      borderBottom:'1px solid var(--border-default)',
      fontSize:12,
    }}>
      <span style={{
        display:'inline-flex', alignItems:'center', gap:6,
        fontWeight:600, color:'var(--text-strong)',
      }}>
        <span style={{
          width:14, height:14, borderRadius:3,
          background:'var(--accent-500)', color:'var(--accent-fg)',
          display:'inline-flex', alignItems:'center', justifyContent:'center',
          fontSize:10, fontWeight:700, fontFamily:'var(--font-mono)',
        }}>啄</span>
        pecker
      </span>
      <span style={{color:'var(--text-faint)'}}>/</span>
      <span style={{color:'var(--text-muted)'}}>workspace-alpha</span>
      <span style={{color:'var(--text-faint)'}}>/</span>
      <span style={{color:'var(--text-default)', fontWeight:500}}>prd-0847</span>
      <span style={{marginLeft:'auto', color:'var(--text-muted)', fontFamily:'var(--font-mono)', fontSize:11}}>
        ⌘K
      </span>
    </div>
  );
}

const btnStyles = {
  primary: {
    padding:'6px 12px', border:0, borderRadius:'var(--r-3)',
    background:'var(--accent-500)', color:'var(--accent-fg)',
    fontSize: 12, fontWeight: 600, cursor:'pointer', fontFamily:'var(--font-sans)',
  },
  secondary: {
    padding:'6px 12px', border:'1px solid var(--border-default)', borderRadius:'var(--r-3)',
    background:'var(--surface-raised)', color:'var(--text-default)',
    fontSize: 12, fontWeight: 500, cursor:'pointer', fontFamily:'var(--font-sans)',
  },
  link: {
    background:'transparent', border:0, color:'var(--text-link)',
    fontSize:12, fontWeight:600, cursor:'pointer', fontFamily:'var(--font-sans)',
  },
  chip: {
    padding:'3px 10px', fontSize:11, fontWeight:500,
    border:'1px solid var(--border-default)', borderRadius:'var(--r-pill)',
    background:'var(--surface-raised)', color:'var(--text-muted)',
    cursor:'pointer', fontFamily:'var(--font-sans)',
  },
  chipActive: {
    background:'var(--neutral-800)', color:'var(--neutral-0)',
    borderColor:'var(--neutral-800)',
  },
};

Object.assign(window, {
  Phase0Upload, Phase1Blindspots, Phase1_5, Phase2Running, Phase3Review, Phase4Report,
});
