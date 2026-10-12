"""AI summary (decision D22): Gemini is mocked; no network in tests."""
import asyncio
import logging
from types import SimpleNamespace

import pytest

from app.ai.summary import LABEL_AI, LABEL_TEMPLATE, Summarizer, build_cell_facts, cell_cache_key, clean_ai_text, template_cell
from app.config import Settings
from app.runtime import Runtime
from conftest import POLL_TS, make

DELHI = (28.47, 77.20)


class FakeGemini:
    """Stands in for google.genai.Client: answers[model] is the text, or an exception to raise."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []
        fake = self

        class Models:
            async def generate_content(self, model, contents, config):
                fake.calls.append(model)
                answer = fake.answers.get(model, RuntimeError(f"no such model {model}"))
                if isinstance(answer, BaseException):
                    raise answer
                if isinstance(answer, float):  # a model that hangs for this long
                    await asyncio.sleep(answer)
                    return SimpleNamespace(text="too late")
                return SimpleNamespace(text=answer)

        self.aio = SimpleNamespace(models=Models())


def summarizer(answers=None, key="test-key", **settings):
    fake, made = FakeGemini(answers or {}), []

    def factory(api_key):
        made.append(api_key)
        return fake

    s = Settings(GEMINI_API_KEY=key, ai_models="m1,m2,m3", **settings)
    return Summarizer(s, client_factory=factory), fake, made


@pytest.fixture
def jam_facts(tmp_path):
    """Facts for a hexagon an injected jammer turned red, built from a real tick."""
    rt = Runtime(Settings(db_path=tmp_path / "t.db", recordings_dir=tmp_path))
    rt.clock.use_replay(POLL_TS)
    rt.create_attack({"kind": "jamming", "center": list(DELHI), "radius_km": 30, "strength": 1.0, "position_loss": 0.0})
    rt.ingest_records([make(f"{i:06x}", DELHI[0] + (i - 10) * 0.01, DELHI[1], flight=f"IGO{i}") for i in range(20)]
                      + [make("inbnd1", DELHI[0], DELHI[1] - 1.3, track=90.0, gs=450.0, flight="AIC101")], now=POLL_TS)
    rt.compute_tick()
    [cell] = [h for h, c in rt.last_cells.items() if c.state == "jammed"]
    return build_cell_facts(cell, rt.tick_state)


def ask(ai, facts):
    return asyncio.run(ai.summarize("cell", facts["h3"], facts, cell_cache_key(facts), now_ts=POLL_TS))


def test_settings_read_backend_env_wherever_uvicorn_starts(tmp_path, monkeypatch):
    from app.config import BACKEND_DIR, REPO_ROOT

    files = Settings.model_config["env_file"]
    assert files == (REPO_ROOT / ".env", BACKEND_DIR / ".env") and all(p.is_absolute() for p in files)  # backend/.env wins
    monkeypatch.delenv("GEMINI_API_KEY")  # conftest blanks it; here the dotenv file must provide it
    monkeypatch.chdir(tmp_path)  # a different working directory
    env = tmp_path / "x.env"
    env.write_text("GEMINI_API_KEY=from-dotenv\nGAW_AI_MODELS=a, b\n", encoding="utf-8")
    s = Settings(_env_file=env)
    assert s.gemini_api_key.get_secret_value() == "from-dotenv" and s.ai_model_list == ["a", "b"]


def test_facts_hold_only_rule_engine_output(jam_facts):
    f = jam_facts
    assert (f["state"], f["n_bad"], f["injected"], f["mixed"]) == ("jammed", 20, True, False)
    assert f["early_warnings"][0]["flight"] == "AIC101" and f["flagged_aircraft"][0]["bad_reason"] == "low_nacp"
    assert f["open_incident"]["approximate_area_for_investigation"]["radius_km"] >= 15


def test_first_model_fails_second_is_used(jam_facts):
    ai, fake, _ = summarizer({"m1": RuntimeError("429 RESOURCE_EXHAUSTED"), "m2": "This is a simulated test attack. Twenty aircraft lost GPS."})
    r = ask(ai, jam_facts)
    assert (r["source"], r["model"], r["label"], r["cached"]) == ("ai", "m2", LABEL_AI, False)
    assert r["summary"].startswith("This is a simulated test attack") and fake.calls == ["m1", "m2"]
    assert ai.status()["last_model_used"] == "m2" and ai.status()["last_error"] is None


def test_all_models_fail_gives_the_template(jam_facts):
    ai, fake, _ = summarizer({"m1": RuntimeError("quota"), "m2": 5.0, "m3": ""})  # error, hangs past the timeout, empty
    ai.settings.ai_timeout_s = 0.05
    r = ask(ai, jam_facts)
    assert (r["source"], r["model"], r["label"]) == ("template", None, LABEL_TEMPLATE)
    assert r["summary"] and fake.calls == ["m1", "m2", "m3"] and "m3: empty answer" in ai.status()["last_error"]


def test_no_key_uses_the_template_and_never_builds_a_client(jam_facts):
    ai, fake, made = summarizer({"m1": "should not be used"}, key="")
    r = ask(ai, jam_facts)
    assert r["source"] == "template" and made == [] and fake.calls == []
    assert ai.status()["key_present"] is False
    ai_off, _, made_off = summarizer({"m1": "x"}, ai_enabled=False)
    assert ask(ai_off, jam_facts)["source"] == "template" and made_off == []


def test_injected_template_says_simulated_test_attack_first(jam_facts):
    first_sentence = template_cell(jam_facts).split(". ")[0].lower()
    assert "simulated test attack" in first_sentence
    assert "simulated test attack" not in template_cell({**jam_facts, "injected": False, "mixed": False}).lower()
    mixed = template_cell({**jam_facts, "mixed": True})
    assert "Real (non-injected) GPS problems are also present" in mixed


def test_cache_hit_makes_no_new_call(jam_facts):
    ai, fake, _ = summarizer({"m1": "Simulated test attack: twenty aircraft lost GPS here."})
    first, second = ask(ai, jam_facts), ask(ai, jam_facts)
    assert (first["cached"], second["cached"]) == (False, True) and fake.calls == ["m1"]
    assert second["summary"] == first["summary"]
    ask(ai, {**jam_facts, "n_bad": 19})  # different rule-engine state: a new summary
    assert fake.calls == ["m1", "m1"]


def test_rate_limit_falls_back_to_the_template(jam_facts):
    ai, fake, _ = summarizer({"m1": "Simulated test attack."}, ai_max_per_min=1)
    assert ask(ai, jam_facts)["source"] == "ai"
    r = ask(ai, {**jam_facts, "n_bad": 19})
    assert r["source"] == "template" and "rate limit" in ai.status()["last_error"] and fake.calls == ["m1"]


def test_ai_text_is_cleaned_and_an_injected_test_is_always_labelled(jam_facts):
    text = clean_ai_text("**Twenty aircraft** lost GPS near Delhi.\n- Controllers were warned.", jam_facts)
    assert text == "Simulated test attack (INJECTED TEST ATTACK). Twenty aircraft lost GPS near Delhi. Controllers were warned."
    long = " ".join(["Word"] * 200) + "."
    assert len(clean_ai_text(long, {"injected": False}).split()) <= 111


def test_the_api_key_never_reaches_logs_or_status(jam_facts, caplog):
    ai, _, _ = summarizer({"m1": RuntimeError("API key test-key not valid"), "m2": RuntimeError("down")})
    with caplog.at_level(logging.DEBUG):
        ask(ai, jam_facts)
    assert "test-key" not in caplog.text and "test-key" not in str(ai.status())
    assert "test-key" not in repr(ai.settings)
