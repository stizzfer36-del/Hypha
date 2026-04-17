"""M6 — reflection tests. Canary guard is the critical case."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from hypha.events import Kind
from hypha.ledger import Ledger
from hypha.reflection.canary import CanaryGuard, CanaryTask
from hypha.reflection.clustering import Clusterer
from hypha.reflection.run_log import Run, RunLog
from hypha.reflection.variants import VariantStore


# ---- RunLog ------------------------------------------------------------------


def test_run_log_append_and_pass_rate(tmp_path: Path) -> None:
    rl = RunLog(tmp_path / "runs.db")
    rl.append(Run(agent="a", prompt_id="code", variant_id="v1",
                  model="m", tokens_in=0, tokens_out=0,
                  verification_passed=True, ms=1))
    rl.append(Run(agent="a", prompt_id="code", variant_id="v1",
                  model="m", tokens_in=0, tokens_out=0,
                  verification_passed=False, ms=1, failure_signature="E1"))
    passed, total = rl.pass_rate("v1")
    assert total == 2
    assert passed == 1


def test_run_log_recent_failures_surface_signature(tmp_path: Path) -> None:
    rl = RunLog(tmp_path / "runs.db")
    rl.append(Run(agent="a", prompt_id="code", variant_id="v1",
                  model="m", tokens_in=0, tokens_out=0,
                  verification_passed=False, ms=1, failure_signature="MissingImport"))
    fs = rl.recent_failures()
    assert len(fs) == 1
    assert fs[0].failure_signature == "MissingImport"


# ---- VariantStore ------------------------------------------------------------


def test_variant_register_dedups_on_hash(tmp_path: Path) -> None:
    vs = VariantStore(tmp_path / "v.db")
    a = vs.register("code", "prompt body")
    b = vs.register("code", "prompt body")
    assert a.id == b.id
    assert a.body_hash == b.body_hash


def test_variant_accept_sets_freeze_window(tmp_path: Path) -> None:
    vs = VariantStore(tmp_path / "v.db", freeze_days=1)
    v = vs.register("code", "body-x")
    assert not vs.is_frozen(v.id)
    vs.accept(v.id)
    assert vs.is_frozen(v.id)
    got = vs.get(v.id)
    assert got is not None
    assert got.accepted
    assert got.frozen_until_ts > time.time()


def test_active_returns_most_recent_accepted(tmp_path: Path) -> None:
    vs = VariantStore(tmp_path / "v.db")
    v1 = vs.register("code", "a")
    v2 = vs.register("code", "b")
    vs.accept(v1.id)
    vs.accept(v2.id)
    got = vs.active("code")
    assert got is not None and got.id in (v1.id, v2.id)


# ---- CanaryGuard (non-negotiable) --------------------------------------------


def _canary_tasks() -> list[CanaryTask]:
    return [
        CanaryTask("add", "1+1", lambda out: out.strip() == "2"),
        CanaryTask("say_hi", "hi", lambda out: out.strip() == "hi"),
        CanaryTask("double", "21", lambda out: out.strip() == "42"),
    ]


async def test_canary_rejects_any_regression() -> None:
    guard = CanaryGuard(tasks=_canary_tasks())

    async def run(body: str, inp: str) -> str:
        # "baseline" variant passes all three
        if body == "BASE":
            return {"1+1": "2", "hi": "hi", "21": "42"}[inp]
        # "bad" variant regresses on double
        return {"1+1": "2", "hi": "hi", "21": "41"}[inp]

    report = await guard.evaluate("BAD", run, baseline_pass_rate=1.0)
    assert not report.ok
    assert report.pass_rate < report.baseline_pass_rate
    assert "regression" in report.rationale


async def test_canary_accepts_improvement() -> None:
    guard = CanaryGuard(tasks=_canary_tasks())

    async def run(body: str, inp: str) -> str:
        # Variant passes all three; baseline was 2/3.
        return {"1+1": "2", "hi": "hi", "21": "42"}[inp]

    report = await guard.evaluate("GOOD", run, baseline_pass_rate=2 / 3)
    assert report.ok
    assert report.pass_rate == 1.0


async def test_canary_accepts_equal_performance() -> None:
    guard = CanaryGuard(tasks=_canary_tasks())

    async def run(body: str, inp: str) -> str:
        return {"1+1": "2", "hi": "hi", "21": "42"}[inp]

    report = await guard.evaluate("EQ", run, baseline_pass_rate=1.0)
    assert report.ok


def test_canary_rejects_empty_task_list() -> None:
    with pytest.raises(ValueError):
        CanaryGuard(tasks=[])


# ---- Clusterer ---------------------------------------------------------------


async def test_clusterer_groups_and_emits_candidate(tmp_path: Path) -> None:
    rl = RunLog(tmp_path / "runs.db")
    for _ in range(4):
        rl.append(Run(agent="a", prompt_id="code", variant_id="v1",
                      model="m", tokens_in=0, tokens_out=0,
                      verification_passed=False, ms=1,
                      failure_signature="JSONDecodeError"))
    for _ in range(2):
        rl.append(Run(agent="a", prompt_id="code", variant_id="v1",
                      model="m", tokens_in=0, tokens_out=0,
                      verification_passed=False, ms=1,
                      failure_signature="ImportError"))

    ledger = Ledger(str(tmp_path / "ledger.db"))
    await ledger.init()

    async def propose(prompt_id: str, rs: list[Run]) -> str:
        return f"new body for {prompt_id} after {len(rs)} {rs[0].failure_signature} failures"

    clusterer = Clusterer(rl, ledger, propose, min_cluster_size=3)
    clusters = await clusterer.reflect_nightly()
    # JSONDecodeError cluster (4 runs) crosses threshold; ImportError (2) does not.
    assert len(clusters) == 1
    assert clusters[0].signature == "JSONDecodeError"
    candidates = await ledger.recent(kind=Kind.PROMPT_VARIANT_CANDIDATE, limit=10)
    assert len(candidates) == 1


# ---- Integration: full guarded-accept flow -----------------------------------


async def test_variant_cannot_be_accepted_without_canary_pass(tmp_path: Path) -> None:
    """Integration: the *only* architecturally-sanctioned path to accept a
    variant is `canary.ok -> store.accept`. If canary fails, accept must not
    be called. This test asserts that invariant at the call-site level.
    """
    guard = CanaryGuard(tasks=_canary_tasks())
    vs = VariantStore(tmp_path / "v.db")
    cand = vs.register("code", "NEW")

    async def run(body: str, inp: str) -> str:
        return {"1+1": "2", "hi": "hi", "21": "41"}[inp]  # regresses

    report = await guard.evaluate("NEW", run, baseline_pass_rate=1.0)
    if report.ok:
        vs.accept(cand.id)
    # Not accepted because regression rejected the variant.
    assert not vs.get(cand.id).accepted
