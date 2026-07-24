"""Small dependency-free Prometheus exposition for the single-process MVP."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock

LATENCY_BUCKETS_SECONDS = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0)


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _number(value: float) -> str:
    return f"{value:.9g}"


class HttpMetrics:
    """Collect bounded HTTP counters and latency buckets for one API process."""

    def __init__(self, *, version: str, environment: str) -> None:
        self._version = version
        self._environment = environment
        self._lock = Lock()
        self._inflight = 0
        self._requests: defaultdict[tuple[str, str, str], int] = defaultdict(int)
        self._duration_count: defaultdict[tuple[str, str], int] = defaultdict(int)
        self._duration_sum: defaultdict[tuple[str, str], float] = defaultdict(float)
        self._duration_buckets: defaultdict[tuple[str, str, float], int] = defaultdict(int)

    def started(self) -> None:
        with self._lock:
            self._inflight += 1

    def finished(self, *, method: str, route: str, status_code: int, duration: float) -> None:
        status_class = f"{status_code // 100}xx"
        with self._lock:
            self._inflight -= 1
            self._requests[(method, route, status_class)] += 1
            self._duration_count[(method, route)] += 1
            self._duration_sum[(method, route)] += duration
            for bucket in LATENCY_BUCKETS_SECONDS:
                if duration <= bucket:
                    self._duration_buckets[(method, route, bucket)] += 1

    def render(self) -> str:
        with self._lock:
            inflight = self._inflight
            requests = dict(self._requests)
            duration_count = dict(self._duration_count)
            duration_sum = dict(self._duration_sum)
            duration_buckets = dict(self._duration_buckets)

        lines = [
            "# HELP hotel_build_info Build and environment information.",
            "# TYPE hotel_build_info gauge",
            (
                'hotel_build_info{environment="'
                f'{_label(self._environment)}",version="{_label(self._version)}'
                '"} 1'
            ),
            "# HELP hotel_http_requests_inflight Current in-flight HTTP requests.",
            "# TYPE hotel_http_requests_inflight gauge",
            f"hotel_http_requests_inflight {inflight}",
            "# HELP hotel_http_requests_total Completed HTTP requests.",
            "# TYPE hotel_http_requests_total counter",
        ]
        for (method, route, status_class), count in sorted(requests.items()):
            lines.append(
                "hotel_http_requests_total"
                f'{{method="{_label(method)}",route="{_label(route)}",'
                f'status_class="{status_class}"}} {count}'
            )
        lines.extend(
            (
                "# HELP hotel_http_request_duration_seconds HTTP request duration.",
                "# TYPE hotel_http_request_duration_seconds histogram",
            )
        )
        for method, route in sorted(duration_count):
            labels = f'method="{_label(method)}",route="{_label(route)}"'
            for bucket in LATENCY_BUCKETS_SECONDS:
                count = duration_buckets.get((method, route, bucket), 0)
                lines.append(
                    "hotel_http_request_duration_seconds_bucket"
                    f'{{{labels},le="{_number(bucket)}"}} {count}'
                )
            count = duration_count[(method, route)]
            lines.append(
                f'hotel_http_request_duration_seconds_bucket{{{labels},le="+Inf"}} {count}'
            )
            lines.append(
                f"hotel_http_request_duration_seconds_sum{{{labels}}} "
                f"{_number(duration_sum[(method, route)])}"
            )
            lines.append(f"hotel_http_request_duration_seconds_count{{{labels}}} {count}")
        return "\n".join(lines) + "\n"
