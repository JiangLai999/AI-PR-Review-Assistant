"""Token Bucket Rate Limiter 实现。

使用 Token Bucket 算法控制 GitHub API 请求速率，防止触发 403 Rate Limit。
"""

import threading
import time
from dataclasses import dataclass


@dataclass
class TokenBucket:
    """Token Bucket 速率限制器。

    以固定速率补充令牌，每次 API 调用消耗一个令牌。
    桶满时令牌不再增加，超限的请求需等待令牌补充。

    Attributes:
        rate: 令牌补充速率（tokens/second），默认 5000/hr ≈ 1.39/s
        burst: 桶的最大容量（允许的突发请求数）
    """

    rate: float
    burst: float = 10.0

    def __post_init__(self):
        self._tokens: float = self.burst
        self._last_refill: float = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
        self._last_refill = now

    def acquire(self) -> None:
        """阻塞直到获取一个令牌。"""
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            wait_time = (1.0 - self._tokens) / self.rate
        time.sleep(wait_time)
        with self._lock:
            self._refill()
            self._tokens -= 1.0

    def try_acquire(self) -> bool:
        """非阻塞尝试获取令牌。

        Returns:
            True 如果成功获取令牌，False 如果令牌不足。
        """
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    @property
    def available_tokens(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens

    def wait_for_tokens(self, required: int = 1, timeout: float | None = None) -> bool:
        """等待获取指定数量的令牌。

        Args:
            required: 需要的令牌数
            timeout: 最大等待时间（秒），None 表示无限等待

        Returns:
            True 如果成功获取，False 如果超时
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        acquired = 0
        while acquired < required:
            remaining = required - acquired
            with self._lock:
                self._refill()
                if self._tokens >= remaining:
                    self._tokens -= remaining
                    return True
                if self._tokens >= 1.0:
                    take = int(self._tokens)
                    self._tokens -= take
                    acquired += take
                    continue
                wait_time = (1.0 - self._tokens) / self.rate
            if deadline is not None and time.monotonic() + wait_time > deadline:
                return False
            time.sleep(wait_time)
        return True
