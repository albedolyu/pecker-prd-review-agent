"""route_eval.datasets -- 评测数据集子包.

5 个数据集统一通过 loader.load_dataset(name) 访问.

数据集列表:
    business_prd_gt    -- 真实业务 PRD + 现成 GT (劳动仲裁/风鸟诉前调解/积分抵扣支付)
    template_prd       -- 侵权软件模板 PRD (sampling noise 校准基线)
    advisor_conflicts  -- 苍鹰冲突调解评测 (含占位待补)
    hallucination      -- 幻觉检测 (30 真 + 30 假, 4 种构造手法等量)
    intent             -- 意图分类 (50 标签 + 5 reject)

参见 ``eval/route_eval/datasets/loader.py``.
"""

from .loader import load_dataset

__all__ = ["load_dataset"]
