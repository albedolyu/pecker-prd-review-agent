"""scorers -- 包现成 cuckoo / consistency 引擎, 暴露统一签名给 metrics 层调用."""

from . import consistency_adapter, cuckoo_adapter

__all__ = ["consistency_adapter", "cuckoo_adapter"]
