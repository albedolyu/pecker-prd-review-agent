"""
啄木鸟自定义异常体系
替代裸 except Exception，让错误处理更精确
"""


class PeckerError(Exception):
    """啄木鸟基础异常"""
    pass


class APIError(PeckerError):
    """Claude API 调用失败（含重试后仍失败）"""
    def __init__(self, message, model=None, status_code=None):
        self.model = model
        self.status_code = status_code
        super().__init__(message)


class WikiError(PeckerError):
    """Wiki 知识库操作失败（读写/锁/路径）"""
    pass


class ToolError(PeckerError):
    """工具执行失败"""
    def __init__(self, message, tool_name=None):
        self.tool_name = tool_name
        super().__init__(message)


class ConfigError(PeckerError):
    """配置缺失或格式错误"""
    pass


class AgentTimeoutError(PeckerError):
    """Agent 执行超过 wall-clock 上限(tool_loop 总时长 / Worker 超时)"""
    def __init__(self, message, elapsed=None, limit=None):
        self.elapsed = elapsed
        self.limit = limit
        super().__init__(message)


class VerificationError(PeckerError):
    """依据校验失败(evidence_content 指向不存在的 wiki 页或 rule_id)"""
    def __init__(self, message, evidence_type=None, target=None):
        self.evidence_type = evidence_type
        self.target = target
        super().__init__(message)
