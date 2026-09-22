import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.classifiers.llm_classifier import LLMClassifier, LLMError
from src.models import CleanRecord


class _FakeResp:
    def __init__(self, content: str):
        self._content = content

    def read(self, *_a, **_k):
        import json
        return json.dumps({
            "choices": [{"message": {"content": self._content}}]
        }).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _config(tmp_path, **overrides) -> dict:
    cfg = {
        "enabled": True,
        "provider": "google_gemini",
        "endpoint": "https://generativelanguage.googleapis.com",
        "deployment": "gemini-3.6-flash",
        "model": "gemini-3.6-flash",
        "api_key_env": "GEMINI_API_KEY",
        "temperature": 0,
        "timeout_seconds": 30,
        "batch_size": 1,
        "max_retries": 3,
        "retry_base_seconds": 0.01,
        "cache_file": str(tmp_path / "llm_cache.jsonl"),
    }
    cfg.update(overrides)
    return cfg


def _record() -> CleanRecord:
    return CleanRecord(
        record_id="rec_test1", vehicle="Jaecoo J5", community="c", post_id="p1",
        comment_id="c1", parent_id=None, source_type="comment", date="2026-01-01",
        text_clean="ACC di tol mantap, mobil depan ngerem ikut halus.",
        url="u", scraped_at="t",
    )


def test_gemini_url_and_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
    clf = LLMClassifier(_config(tmp_path))

    body = '{"feature": "ACC", "subfeature": "following", "scenario": "highway_tol", ' \
           '"evidence_type": "direct_experience", "sentiment": "positive", ' \
           '"relevant": "relevant", "expectation_mismatch": "no", "smoothness": ' \
           '"smooth", "confidence": "high", "experience_summary": "ACC mantap."}'
    with mock.patch("src.classifiers.llm_classifier.urlopen", return_value=_FakeResp(body)) as m:
        content = clf._call([{"role": "user", "content": "x"}])
    assert "ACC mantap." in content
    req = m.call_args[0][0]
    assert "/v1beta/openai/chat/completions" in req.full_url
    assert req.get_header("Authorization") == "Bearer test-key-123"
    assert req.data


def test_gemini_default_endpoint(tmp_path):
    monkeypatch_set = {}
    cfg = _config(tmp_path)
    cfg["endpoint"] = ""
    with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}):
        clf = LLMClassifier(cfg)
    assert clf.endpoint == "https://generativelanguage.googleapis.com"


def test_gemini_requires_key(monkeypatch, tmp_path):
    cfg = _config(tmp_path)
    for k in list(os.environ.keys()):
        if "GEMINI" in k or "AZURE" in k:
            monkeypatch.delenv(k, raising=False)
    try:
        LLMClassifier(cfg)
        raised = False
    except LLMError:
        raised = True
    assert raised


def test_gemini_classify_validates_enum(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    clf = LLMClassifier(_config(tmp_path))
    clf._cache = {}
    body = '{"feature": "NONSENSE", "subfeature": "following", "scenario": "x", ' \
           '"evidence_type": "direct_experience", "sentiment": "positive", ' \
           '"relevant": "relevant", "expectation_mismatch": "no", "smoothness": ' \
           '"smooth", "confidence": "high", "experience_summary": "ok"}'
    with mock.patch("src.classifiers.llm_classifier.urlopen", return_value=_FakeResp(body)):
        labels = clf.classify(_record())
    assert labels["feature"] == "unknown"  # invalid enum coerced to safe default
    assert labels["subfeature"] == "not_stated"


def test_openai_compatible_openrouter_url_and_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key-1")
    cfg = _config(
        tmp_path,
        provider="openai_compatible",
        endpoint="https://openrouter.ai/api/v1",
        deployment="nex-agi/nex-n2.5-pro:free",
        model="nex-agi/nex-n2.5-pro:free",
        api_key_env="OPENROUTER_API_KEY",
    )
    clf = LLMClassifier(cfg)

    body = '{"feature": "ACC", "subfeature": "following", "scenario": "highway_tol", ' \
           '"evidence_type": "direct_experience", "sentiment": "positive", ' \
           '"relevant": "relevant", "expectation_mismatch": "no", "smoothness": ' \
           '"smooth", "confidence": "high", "experience_summary": "ACC mantap."}'
    with mock.patch("src.classifiers.llm_classifier.urlopen", return_value=_FakeResp(body)) as m:
        content = clf._call([{"role": "user", "content": "x"}])
    assert "ACC mantap." in content
    req = m.call_args[0][0]
    assert req.full_url == "https://openrouter.ai/api/v1/chat/completions"
    assert req.get_header("Authorization") == "Bearer or-key-1"
    import json
    sent = json.loads(req.data)
    assert sent["model"] == "nex-agi/nex-n2.5-pro:free"


def test_openai_compatible_no_double_v1(monkeypatch, tmp_path):
    cfg = _config(
        tmp_path,
        provider="openai_compatible",
        endpoint="https://openrouter.ai/api/v1",
        deployment="nex-agi/nex-n2.5-pro:free",
        model="nex-agi/nex-n2.5-pro:free",
        api_key_env="OPENROUTER_API_KEY",
    )
    clf = LLMClassifier(cfg)

    body = '{"feature": "ACC", "subfeature": "following", "scenario": "x", ' \
           '"evidence_type": "direct_experience", "sentiment": "positive", ' \
           '"relevant": "relevant", "expectation_mismatch": "no", "smoothness": ' \
           '"smooth", "confidence": "high", "experience_summary": "ok"}'
    with mock.patch("src.classifiers.llm_classifier.urlopen", return_value=_FakeResp(body)) as m:
        clf._call([{"role": "user", "content": "x"}])
    req = m.call_args[0][0]
    assert req.full_url == "https://openrouter.ai/api/v1/chat/completions"


def test_openai_compatible_appends_v1(monkeypatch, tmp_path):
    cfg = _config(
        tmp_path,
        provider="openai_compatible",
        endpoint="http://localhost:11434",
        deployment="qwen3:4b",
        model="qwen3:4b",
        api_key_env="",
    )
    clf = LLMClassifier(cfg)

    body = '{"feature": "ACC", "subfeature": "following", "scenario": "x", ' \
           '"evidence_type": "direct_experience", "sentiment": "positive", ' \
           '"relevant": "relevant", "expectation_mismatch": "no", "smoothness": ' \
           '"smooth", "confidence": "high", "experience_summary": "ok"}'
    with mock.patch("src.classifiers.llm_classifier.urlopen", return_value=_FakeResp(body)) as m:
        clf._call([{"role": "user", "content": "x"}])
    req = m.call_args[0][0]
    assert req.full_url == "http://localhost:11434/v1/chat/completions"
    assert req.get_header("Authorization") is None  # keyless local server


def _http_error(code: int):
    return __import__("urllib.error", fromlist=["HTTPError"]).HTTPError(
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        code, "err", {}, None)


def _raiser(code: int):
    def _inner(*_a, **_k):
        raise _http_error(code)
    return _inner


def test_retry_on_429_then_success(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    clf = LLMClassifier(_config(tmp_path))
    body = '{"feature": "ACC", "subfeature": "following", "scenario": "x", ' \
           '"evidence_type": "direct_experience", "sentiment": "positive", ' \
           '"relevant": "relevant", "expectation_mismatch": "no", "smoothness": ' \
           '"smooth", "confidence": "high", "experience_summary": "ok"}'
    good = _FakeResp(body)
    with mock.patch("src.classifiers.llm_classifier.time.sleep") as slp, \
            mock.patch("src.classifiers.llm_classifier.urlopen",
                       side_effect=[_http_error(429), _http_error(500), good]) as m:
        content = clf._call([{"role": "user", "content": "x"}])
    assert "ACC" in content
    assert m.call_count == 3
    assert slp.call_count == 2


def test_retry_exhausted_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    clf = LLMClassifier(_config(tmp_path))
    with mock.patch("src.classifiers.llm_classifier.time.sleep"), \
            mock.patch("src.classifiers.llm_classifier.urlopen",
                       side_effect=_raiser(429)) as m:
        try:
            clf._call([{"role": "user", "content": "x"}])
            raised = False
        except LLMError:
            raised = True
    assert raised
    assert m.call_count == 3  # initial + 2 retries