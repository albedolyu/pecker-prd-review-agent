# UI 视觉回归语料库

> 借鉴 chenglou/pretext 的 corpora/benchmarks 思路:把几份代表性 PRD 固化成 fixture,每次 UI 改版后跑 Playwright 截图对比,防止视觉回归。

## 目录结构

```
ui-corpus/
├── README.md                        本文件
├── prd/                             5 个代表性 PRD(纯文本,喂给 fixture 后端)
│   ├── short.md                     ~500 字简短需求,单一功能点
│   ├── long.md                      ~8000 字大型需求,多模块
│   ├── with-tables.md               含字段映射表、需求矩阵的 PRD
│   ├── with-code.md                 含伪代码 / SQL / JSON schema 的 PRD
│   └── with-images.md               含 ![](./xx.png) 相对路径图片引用的 PRD
└── baselines/                       基准截图(Playwright 跑出来的,入 git)
    ├── phase0-upload.png            拖拽上传页 + workspace 已选
    ├── phase2-running-40.png        评审中,进度 40%(2 个 worker 完成)
    ├── phase2-running-80.png        评审中,进度 80%(终审进行中)
    ├── phase3-confirm.png           逐条确认页,已决 50%
    └── phase4-report.png            报告页,预览展开
```

## 运行

```bash
# 生成当前版本的截图并覆盖 baseline(仅在人工确认 UI 改动后跑)
cd web
pnpm exec playwright test --update-snapshots

# 对比 baseline 和当前,像素差异 >5% 失败
pnpm exec playwright test
```

## 触发条件

- 每次 Phase 2/3/4 的组件结构或样式改动后必跑
- 每次 `globals.css` 主题 token 改动后必跑
- 上线前一次、UAT 前一次

## 更新 baseline 的规则

截图和 baseline 不一致时,**先人工确认新版是否更好**:

1. Playwright 会把 diff 图片放到 `test-results/`,打开看看差哪里
2. 如果是改进 → `--update-snapshots` 更新,commit baseline 改动
3. 如果是回归 → 回滚代码

**绝对不要**盲目 `--update-snapshots`,这就是回归测试的反模式。

## 当前状态

- [ ] `prd/short.md` — 已有骨架,需要填入真实 PRD 片段
- [ ] `prd/long.md` — 待填
- [ ] `prd/with-tables.md` — 待填
- [ ] `prd/with-code.md` — 待填
- [ ] `prd/with-images.md` — 待填
- [ ] `baselines/phase0-upload.png` — 需后端跑起来后首次生成
- [ ] `baselines/phase2-running-40.png` — 同上
- [ ] `baselines/phase2-running-80.png` — 同上
- [ ] `baselines/phase3-confirm.png` — 同上
- [ ] `baselines/phase4-report.png` — 同上

> Phase E commit 只建结构 + 1 个 short.md 样本,其余 fixture 和 baseline 需要有真实后端跑一次后才能产出。详细流程见 `web/tests/e2e/` 下的 Playwright 测试文件。
