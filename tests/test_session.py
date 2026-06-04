import pytest

import leetbot.config as config
from leetbot.interview.session import InterviewSession, State


def _session(**kwargs) -> InterviewSession:
    defaults = dict(
        user_id="u1",
        day_key="2024-01-01",
        problem_title="Two Sum",
        problem_content="Find two numbers that add to target.",
        problem_url="https://leetcode.com/problems/two-sum/",
        reference_solution="def twoSum(nums, target): ...",
    )
    defaults.update(kwargs)
    return InterviewSession(**defaults)


# ── Initial state ─────────────────────────────────────────────────────────────

def test_initial_state():
    s = _session()
    assert s.state == State.BRUTE_FORCE
    assert s.bf_retries == 0
    assert s.tech_retries == 0
    assert s.code_retries == 0


def test_initial_score_zero():
    s = _session()
    assert s.compute_score() == 0


# ── Transitions on accept ─────────────────────────────────────────────────────

def test_accept_advances_bf_to_technique():
    s = _session()
    s.accept()
    assert s.state == State.TECHNIQUE


def test_accept_advances_technique_to_code():
    s = _session()
    s.accept()
    s.accept()
    assert s.state == State.CODE


def test_accept_advances_code_to_done():
    s = _session()
    s.accept(); s.accept(); s.accept()
    assert s.state == State.DONE


def test_accept_done_is_noop():
    s = _session()
    s.accept(); s.accept(); s.accept()
    s.accept()  # extra accept on DONE state
    assert s.state == State.DONE


# ── Retry counting on reject ──────────────────────────────────────────────────

def test_reject_increments_bf_retries():
    s = _session()
    s.reject()
    assert s.bf_retries == 1
    assert s.state == State.BRUTE_FORCE


def test_reject_increments_tech_retries():
    s = _session()
    s.accept()  # advance to TECHNIQUE
    s.reject()
    assert s.tech_retries == 1
    assert s.state == State.TECHNIQUE


def test_reject_increments_code_retries():
    s = _session()
    s.accept(); s.accept()  # advance to CODE
    s.reject()
    assert s.code_retries == 1
    assert s.state == State.CODE


# ── Score computation ─────────────────────────────────────────────────────────

def test_score_after_bf_pass_no_retries():
    s = _session()
    s.accept()  # pass BF
    assert s.compute_score() == config.BF_MAX


def test_score_after_bf_pass_with_retries():
    s = _session()
    s.reject(); s.reject()  # 2 retries on BF
    s.accept()
    expected = max(config.BF_FLOOR, config.BF_MAX - config.BF_PENALTY * 2)
    assert s.compute_score() == expected


def test_score_tech_floor():
    s = _session()
    s.accept()  # pass BF
    for _ in range(100):  # way more retries than penalty can absorb
        s.reject()
    s.accept()  # pass TECH
    breakdown = s.step_breakdown()
    assert breakdown["technique"] == config.TECH_FLOOR


def test_score_code_floor_not_zero():
    s = _session()
    s.accept(); s.accept()  # pass BF and TECH
    for _ in range(100):
        s.reject()
    s.accept()  # pass CODE
    breakdown = s.step_breakdown()
    assert breakdown["code"] == config.CODE_FLOOR
    assert config.CODE_FLOOR > 0  # spec guarantees code floor is 10, not 0


def test_perfect_score():
    s = _session()
    s.accept(); s.accept(); s.accept()
    assert s.compute_score() == config.BF_MAX + config.TECH_MAX + config.CODE_MAX
    assert s.compute_score() == 100


def test_giveup_mid_technique_only_counts_bf():
    s = _session()
    s.accept()       # pass BF
    s.reject()       # fail TECH once, then give up
    score = s.compute_score()
    assert score == config.BF_MAX  # only BF completed


def test_step_breakdown_incomplete_steps_are_zero():
    s = _session()
    s.accept()  # pass BF
    breakdown = s.step_breakdown()
    assert breakdown["brute_force"] == config.BF_MAX
    assert breakdown["technique"] == 0
    assert breakdown["code"] == 0
