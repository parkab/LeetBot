"""Session/manager behaviour introduced for practice mode."""
from leetbot.interview.manager import SessionManager
from leetbot.interview.session import InterviewSession, Mode, PendingPractice, State


def _daily(**kw) -> InterviewSession:
    defaults = dict(
        user_id="u1", day_key="2026-01-01", problem_title="Two Sum",
        problem_content="body", problem_url="https://leetcode.com/problems/two-sum/",
        reference_solution="ref",
    )
    defaults.update(kw)
    return InterviewSession(**defaults)


def _practice(**kw) -> InterviewSession:
    defaults = dict(
        mode=Mode.PRACTICE, list_name="grind75", problem_slug="lru-cache",
        problem_difficulty="Medium", problem_title="LRU Cache",
    )
    defaults.update(kw)
    return _daily(**defaults)


# ── session_key ───────────────────────────────────────────────────────────────

def test_daily_session_key_is_the_day():
    assert _daily().session_key == "2026-01-01"


def test_practice_session_key_is_the_slug():
    assert _practice().session_key == "practice:lru-cache"


def test_is_practice_flag():
    assert _practice().is_practice is True
    assert _daily().is_practice is False


def test_daily_and_practice_keys_never_collide():
    assert _daily().session_key != _practice().session_key


# ── reset_progress (reroll) ───────────────────────────────────────────────────

def test_reset_progress_clears_everything():
    s = _practice()
    s.reject()
    s.increment_hint()
    s.record_answer("some answer")
    s.accept()
    s.reject()

    s.reset_progress()

    assert s.state == State.BRUTE_FORCE
    assert s.bf_retries == 0 and s.tech_retries == 0 and s.code_retries == 0
    assert s.bf_hints == 0 and s.tech_hints == 0 and s.code_hints == 0
    assert s.bf_answers == [] and s.tech_answers == [] and s.code_answers == []
    assert s.compute_score() == 0


def test_reset_progress_clears_skips():
    s = _practice()
    s.skip_current_step()
    assert s.bf_skipped is True
    s.reset_progress()
    assert s.bf_skipped is False


# ── Manager: concurrent daily + practice ──────────────────────────────────────

def test_user_can_hold_daily_and_practice_at_once():
    mgr = SessionManager()
    daily, practice = _daily(), _practice()
    mgr.add(daily)
    mgr.add(practice)

    assert mgr.active_count() == 2
    assert mgr.get_by_user_day("u1", "2026-01-01") is daily
    assert mgr.get_by_user_key("u1", "practice:lru-cache") is practice


def test_get_by_user_day_ignores_practice_sessions():
    """A practice session must never be returned as the user's daily session."""
    mgr = SessionManager()
    practice = _practice(day_key="2026-01-01")
    mgr.add(practice)
    assert mgr.get_by_user_day("u1", "2026-01-01") is None


def test_channel_routing_distinguishes_sessions():
    mgr = SessionManager()
    daily, practice = _daily(), _practice()
    mgr.add(daily)
    mgr.add(practice)
    mgr.register_channel(daily, 111)
    mgr.register_channel(practice, 222)

    assert mgr.get_by_channel(111) is daily
    assert mgr.get_by_channel(222) is practice
    assert mgr.get_by_channel(999) is None


def test_sessions_for_user():
    mgr = SessionManager()
    mgr.add(_daily())
    mgr.add(_practice())
    mgr.add(_daily(user_id="u2", day_key="2026-01-02"))

    assert len(mgr.sessions_for_user("u1")) == 2
    assert len(mgr.sessions_for_user("u2")) == 1


def test_remove_clears_both_indexes():
    mgr = SessionManager()
    s = _practice()
    mgr.add(s)
    mgr.register_channel(s, 333)
    mgr.remove(s)

    assert mgr.get_by_channel(333) is None
    assert mgr.get_by_user_key("u1", "practice:lru-cache") is None
    assert mgr.active_count() == 0


# ── Manager: rekey on reroll ──────────────────────────────────────────────────

def test_rekey_after_reroll():
    mgr = SessionManager()
    s = _practice()
    mgr.add(s)
    mgr.register_channel(s, 444)

    old_key = s.session_key
    s.problem_slug = "course-schedule"
    mgr.rekey(s, old_key)

    assert mgr.get_by_user_key("u1", "practice:lru-cache") is None
    assert mgr.get_by_user_key("u1", "practice:course-schedule") is s
    assert mgr.get_by_channel(444) is s   # channel routing survives the reroll
    assert mgr.active_count() == 1


# ── Manager: pending practice threads ─────────────────────────────────────────

def test_pending_lifecycle():
    mgr = SessionManager()
    pending = PendingPractice(user_id="u1", list_name="pareto", channel_id=555)
    mgr.add_pending(pending)

    assert mgr.get_pending(555) is pending
    mgr.remove_pending(555)
    assert mgr.get_pending(555) is None


def test_pending_is_not_a_session():
    mgr = SessionManager()
    mgr.add_pending(PendingPractice(user_id="u1", list_name="pareto", channel_id=555))
    assert mgr.get_by_channel(555) is None
    assert mgr.active_count() == 0


# ── Scoring parity with daily ─────────────────────────────────────────────────

def test_practice_scores_identically_to_daily():
    import leetbot.config as config

    s = _practice()
    s.accept(); s.accept(); s.accept()
    assert s.compute_score() == 100
    assert s.step_breakdown()["code"] == config.CODE_MAX
