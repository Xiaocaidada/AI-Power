import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


@dataclass
class _Histogram:
    buckets: tuple[float, ...]
    counts: list[int] = field(default_factory=list)
    total: float = 0.0
    count: int = 0

    def __post_init__(self) -> None:
        if not self.counts:
            self.counts = [0 for _ in self.buckets]


class MetricsRegistry:
    """Minimal Prometheus text-format registry (counters, gauges, histograms)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], _Histogram] = {}
        self._help: dict[str, str] = {}
        self._types: dict[str, str] = {}

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._help.clear()
            self._types.clear()

    def inc_counter(self, name: str, value: float = 1.0, **labels: str) -> None:
        key = (name, _labels(labels))
        with self._lock:
            self._types.setdefault(name, "counter")
            self._counters[key] = self._counters.get(key, 0.0) + value

    def set_gauge(self, name: str, value: float, **labels: str) -> None:
        key = (name, _labels(labels))
        with self._lock:
            self._types.setdefault(name, "gauge")
            self._gauges[key] = value

    def inc_gauge(self, name: str, value: float = 1.0, **labels: str) -> None:
        key = (name, _labels(labels))
        with self._lock:
            self._types.setdefault(name, "gauge")
            self._gauges[key] = self._gauges.get(key, 0.0) + value

    def dec_gauge(self, name: str, value: float = 1.0, **labels: str) -> None:
        self.inc_gauge(name, -value, **labels)

    def observe(self, name: str, value: float, **labels: str) -> None:
        key = (name, _labels(labels))
        with self._lock:
            self._types.setdefault(name, "histogram")
            histogram = self._histograms.get(key)
            if histogram is None:
                histogram = _Histogram(DEFAULT_BUCKETS)
                self._histograms[key] = histogram
            histogram.total += value
            histogram.count += 1
            for index, bound in enumerate(histogram.buckets):
                if value <= bound:
                    histogram.counts[index] += 1

    def describe(self, name: str, help_text: str) -> None:
        self._help[name] = help_text

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            names = sorted({name for name, _ in self._counters})
            for name in names:
                lines.extend(_header(name, self._types.get(name, "counter"), self._help.get(name)))
                for (counter_name, labels), value in sorted(self._counters.items()):
                    if counter_name == name:
                        lines.append(f"{name}{_format_labels(labels)} {_number(value)}")
            for name in sorted({name for name, _ in self._gauges}):
                lines.extend(_header(name, "gauge", self._help.get(name)))
                for (gauge_name, labels), value in sorted(self._gauges.items()):
                    if gauge_name == name:
                        lines.append(f"{name}{_format_labels(labels)} {_number(value)}")
            for name in sorted({name for name, _ in self._histograms}):
                lines.extend(_header(name, "histogram", self._help.get(name)))
                for (histogram_name, labels), histogram in sorted(self._histograms.items()):
                    if histogram_name != name:
                        continue
                    for index, bound in enumerate(histogram.buckets):
                        bucket_labels = _labels_with(labels, "le", _number(bound))
                        lines.append(f"{name}_bucket{bucket_labels} {histogram.counts[index]}")
                    inf_labels = _labels_with(labels, "le", "+Inf")
                    lines.append(f"{name}_bucket{inf_labels} {histogram.count}")
                    lines.append(f"{name}_sum{_format_labels(labels)} {_number(histogram.total)}")
                    lines.append(f"{name}_count{_format_labels(labels)} {histogram.count}")
        return "\n".join(lines) + "\n"


def _labels(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((key, str(value)) for key, value in labels.items()))


def _labels_with(labels: tuple[tuple[str, str], ...], key: str, value: str) -> str:
    return _format_labels(tuple([*labels, (key, value)]))


def _format_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    content = ",".join(f'{key}="{_escape(value)}"' for key, value in labels)
    return "{" + content + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return repr(value)


def _header(name: str, type_name: str, help_text: str | None) -> list[str]:
    lines = []
    if help_text:
        lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} {type_name}")
    return lines


metrics = MetricsRegistry()
metrics.describe("ai_power_http_requests_total", "HTTP requests by route and status")
metrics.describe("ai_power_http_request_duration_seconds", "HTTP request duration in seconds")
metrics.describe("ai_power_sse_active_streams", "Currently open SSE streams")
metrics.describe("ai_power_tokens_total", "LLM tokens by kind, provider, and model")
metrics.describe("ai_power_cost_usd_total", "Estimated model cost in USD")
metrics.describe("ai_power_ingestion_jobs", "Ingestion jobs by status")
metrics.describe("ai_power_circuit_open", "Provider circuit breaker state (1=open)")


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)
            metrics.inc_counter(
                "ai_power_http_requests_total",
                method=request.method,
                path=path,
                status="500",
            )
            raise
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        if path != "/metrics":
            metrics.inc_counter(
                "ai_power_http_requests_total",
                method=request.method,
                path=path,
                status=str(response.status_code),
            )
            metrics.observe(
                "ai_power_http_request_duration_seconds",
                time.perf_counter() - started,
                method=request.method,
                path=path,
                status=str(response.status_code),
            )
        return response


async def track_sse_stream(stream: AsyncIterator[str]) -> AsyncIterator[str]:
    metrics.inc_gauge("ai_power_sse_active_streams")
    try:
        async for item in stream:
            yield item
    finally:
        metrics.dec_gauge("ai_power_sse_active_streams")


def record_usage_metrics(
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    cost: float,
    provider_id: str | None,
    model: str | None,
) -> None:
    labels: dict[str, Any] = {
        "provider": provider_id or "unknown",
        "model": model or "unknown",
    }
    if prompt_tokens:
        metrics.inc_counter("ai_power_tokens_total", float(prompt_tokens), kind="prompt", **labels)
    if completion_tokens:
        metrics.inc_counter(
            "ai_power_tokens_total", float(completion_tokens), kind="completion", **labels
        )
    if cost:
        metrics.inc_counter("ai_power_cost_usd_total", float(cost), **labels)
