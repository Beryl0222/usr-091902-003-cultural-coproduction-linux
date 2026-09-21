"""领域错误：错误码稳定，供接口层映射 HTTP 状态。"""


class DomainError(Exception):
    """所有业务规则冲突的基类。"""

    status = 422
    code = "domain_error"

    def __init__(self, message, *, code=None, status=None, details=None):
        super().__init__(message)
        if code:
            self.code = code
        if status:
            self.status = status
        self.details = details or {}

    def to_dict(self):
        return {"code": self.code, "message": str(self), "details": self.details}


class NotFoundError(DomainError):
    status = 404
    code = "not_found"


class ConflictError(DomainError):
    status = 409
    code = "conflict"


class ValidationError(DomainError):
    status = 400
    code = "validation_error"


class GateBlockedError(DomainError):
    """发行闸门未通过：携带每一项检查结果，供"未决阻塞"展示。"""

    status = 409
    code = "release_gate_blocked"

    def __init__(self, plan_id, checks):
        self.checks = checks
        pending = [c["名称"] for c in checks if c["状态"] != "通过"]
        super().__init__(
            f"发行计划 {plan_id} 仍有未决阻塞：{'、'.join(pending)}",
            details={"plan_id": plan_id, "checks": checks, "pending": pending},
        )
