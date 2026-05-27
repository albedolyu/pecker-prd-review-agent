# Scene Illustrations · 场景插画池

5 张手绘 hero/scene 插画,跟 `public/birds/` 里的头像同源(同一只手画的),
但**用途不同**:

- `public/birds/` = avatar / micro-interaction(头像、Phase 0 拖拽小鸟、404 困惑鸟)
- `public/illustrations/` = scene / hero(完整场景叙事,横向构图,产品 hero / marketing 用)

## 现有资产

```
clear-state.png            Pecker趴在文档上 + 3 个 jade 对勾
                           已用在: Phase 3 EmptyClearState

scene-running.png          4 鸟在笔记本边角并行审稿 + 苍鹰天空剪影
                           备用: Phase 2 hero(当前未使用,Phase 2 已视觉饱和)

scene-partial-silent.png   一只鸟变灰 + 苍鹰降临 + 警示带
                           备用: Phase 1.5 RunHealthCheck 警告 banner
                           (待 PM 反馈再决定是否上)

ceremony-export.png        苍鹰展翅栖立报告堆 + 4 鸟围观 + 羽毛笔
                           备用: Phase 4 报告头条 hero
                           (当前用 64px goshawk avatar 已足)

hero-workbench.png         笔记本工作台 + 4 鸟 avatar 拓扑 + 苍鹰栖立左角
                           用途: README / 公众号 / 对外营销头图
                           不进产品 UI
```

## 何时新增

- 产品里出现某个高频"PM 需要被引导"的页面/状态时,优先生成新场景图
- 不要为了凑数而画(画 = 维护成本,不是免费的)
- 风格参考: 参考已有 8 张系列图(`public/birds/` + `public/illustrations/`),
  保持"同一只手画"的笔触

## 处理脚本

源文件丢到 `~/Desktop/birds/`,跑 `process_freestanding.py` 自动 flood-fill 抠白底
+ 重命名到对应目录(birds/ vs illustrations/)。
