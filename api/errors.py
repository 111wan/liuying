class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.status, self.retryable = code, message, status, retryable

    def public(self):
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


def upstream_error(error: Exception) -> AppError:
    text = str(error).lower()
    if any(term in text for term in ("sign in", "login", "cookies", "登录", "authentication")):
        return AppError(
            "AUTH_REQUIRED", "平台要求有效的访问凭据，请查看原作品或由实例管理员配置本人登录态。", 422
        )
    if any(term in text for term in ("429", "too many requests", "rate limit")):
        return AppError("RATE_LIMITED", "平台暂时限制请求，请稍后再试。", 429, True)
    if any(term in text for term in ("private", "not available", "removed", "404", "deleted")):
        return AppError("NOT_FOUND", "原作品已删除、设为私密，或当前访问环境不可用。", 422)
    if any(term in text for term in ("timeout", "timed out", "connection", "resolve host")):
        return AppError("NETWORK_TIMEOUT", "连接平台超时，请稍后重试。", 502, True)
    if any(term in text for term in ("403", "412", "captcha", "blocked", "验证")):
        return AppError("ACCESS_DENIED", "平台暂未允许此访问，请在原平台确认作品可见后再试。", 422)
    return AppError(
        "UPSTREAM_CHANGED", "暂时无法获取这条视频。平台可能已调整接口，请换一条链接或稍后重试。", 502, True
    )
