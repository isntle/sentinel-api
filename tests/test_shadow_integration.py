import time
import pytest
from src.services.shadow_service import ShadowRunnerService

def test_shadow_runner_ok():
    service = ShadowRunnerService(enabled=True, max_latency_ms=50.0)
    res = service.evaluate_shadow_candidate(
        features=[0.1, 0.2, 0.3],
        candidate_fn=lambda feats: 0.85,
        model_id="convaiinnovations/laya-multilingual@v1.2.0",
    )
    assert res["status"] == "ok"
    assert res["shadow_probability"] == 0.85
    assert res["model_id"] == "convaiinnovations/laya-multilingual@v1.2.0"
    assert "error" not in res

def test_shadow_runner_error_isolation():
    service = ShadowRunnerService(enabled=True)
    def broken_fn(feats):
        raise ValueError("Model tensor parsing corrupted")

    res = service.evaluate_shadow_candidate(
        features=[0.1, 0.2],
        candidate_fn=broken_fn,
        model_id="broken-model",
    )
    assert res["status"] == "error"
    assert res["shadow_probability"] is None
    assert "Model tensor parsing corrupted" in res["error"]

def test_shadow_runner_timeout():
    service = ShadowRunnerService(enabled=True, max_latency_ms=10.0)
    def slow_fn(feats):
        time.sleep(0.025) # 25 ms > 10 ms limit
        return 0.9

    res = service.evaluate_shadow_candidate(
        features=[0.1],
        candidate_fn=slow_fn,
        model_id="slow-model",
    )
    assert res["status"] == "timeout"
    assert res["shadow_probability"] is None
    assert res["latency_ms"] >= 10.0

def test_shadow_runner_kill_switch():
    service = ShadowRunnerService(enabled=False)
    calls = []
    def spy_fn(feats):
        calls.append(1)
        return 0.5

    res = service.evaluate_shadow_candidate(
        features=[0.1],
        candidate_fn=spy_fn,
    )
    assert res["status"] == "disabled"
    assert res["shadow_probability"] is None
    assert len(calls) == 0

def test_shadow_runner_budget_limit():
    service = ShadowRunnerService(enabled=True, budget_limit_per_minute=2)
    def fast_fn(feats):
        return 0.3

    res1 = service.evaluate_shadow_candidate(features=[], candidate_fn=fast_fn)
    res2 = service.evaluate_shadow_candidate(features=[], candidate_fn=fast_fn)
    res3 = service.evaluate_shadow_candidate(features=[], candidate_fn=fast_fn) # 3rd call exceeds

    assert res1["status"] == "ok"
    assert res2["status"] == "ok"
    assert res3["status"] == "budget_exceeded"

def test_shadow_runner_missing_model():
    service = ShadowRunnerService(enabled=True)
    res = service.evaluate_shadow_candidate(features=[], candidate_fn=None)
    assert res["status"] == "missing_model"
    assert res["shadow_probability"] is None
