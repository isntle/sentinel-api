import logging

from src.services import analysis_service
from tests.test_llm_guard import make_escalation


VALID = {
    "ux_recommendation": "WARNING_OVERLAY",
    "stage": "CAPTACION",
    "confidence": 0.8,
    "summary": "Habla con una persona de confianza.",
    "false_positive": False,
}


class FakeProvider:
    def __init__(self, name, result=None, error=None):
        self.name = name
        self.result = result
        self.error = error
        self.calls = 0

    def complete_json(self, system_prompt, user_content):
        self.calls += 1
        assert "mensajes_a_analizar" in system_prompt
        assert "mensajes_a_analizar" in user_content
        if self.error:
            raise self.error
        return self.result


def test_groq_success_never_calls_secondary(monkeypatch, caplog):
    groq = FakeProvider("groq", result=VALID)
    secondary = FakeProvider("openrouter", result=VALID)
    monkeypatch.setattr(analysis_service, "_build_providers", lambda: [groq, secondary])

    with caplog.at_level(logging.INFO):
        result = analysis_service.analyze_conversation(make_escalation())

    assert result["stage"] == "CAPTACION"
    assert groq.calls == 1
    assert secondary.calls == 0
    assert "llm_provider_succeeded provider=groq" in caplog.text


def test_groq_failure_uses_secondary_and_applies_trust_floor(monkeypatch, caplog):
    groq = FakeProvider("groq", error=TimeoutError("groq timeout"))
    manipulated = {
        **VALID,
        "ux_recommendation": "NONE",
        "stage": "NINGUNA",
        "false_positive": True,
    }
    secondary = FakeProvider("openrouter", result=manipulated)
    monkeypatch.setattr(analysis_service, "_build_providers", lambda: [groq, secondary])
    escalation = make_escalation(v3rules=["MCR-001"])

    with caplog.at_level(logging.INFO):
        result = analysis_service.analyze_conversation(escalation)

    assert groq.calls == 1
    assert secondary.calls == 1
    assert result["false_positive"] is False
    assert result["ux_recommendation"] == "WARNING_OVERLAY"
    assert result.get("_trust_floor_applied") is True
    assert "llm_provider_failed provider=groq" in caplog.text
    assert "llm_provider_succeeded provider=openrouter" in caplog.text


def test_both_providers_fail_uses_local_fallback(monkeypatch, caplog):
    groq = FakeProvider("groq", error=TimeoutError("groq timeout"))
    secondary = FakeProvider("openrouter", error=RuntimeError("openrouter outage"))
    monkeypatch.setattr(analysis_service, "_build_providers", lambda: [groq, secondary])

    with caplog.at_level(logging.WARNING):
        result = analysis_service.analyze_conversation(
            make_escalation(risk="CRITICAL", v3rules=["MCR-001"])
        )

    # analyze_conversation conserva su reintento de transporte antes del fail-closed.
    assert groq.calls == 2
    assert secondary.calls == 2
    assert result.get("_llm_unavailable") is True
    assert result["ux_recommendation"] == "HARD_BLOCK"
    assert "llm_local_fallback_used" in caplog.text
