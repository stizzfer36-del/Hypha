"""M6 — canary guard.

Role: the ONLY defense against prompt-evolution reward-hacking. A held-out
task set runs every candidate variant; any regression on canaries rejects
the variant regardless of main-metric gain. Non-negotiable.
Produces: canary pass/fail.
Consumes: candidate variant + canary task set + baseline score.

Refuse to enable reflection (clustering + variant acceptance) until this is
real. Stubbing is correct at scaffold time; enabling reflection against a
stubbed canary is a critical architectural violation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Sequence


@dataclass(frozen=True)
class CanaryTask:
    name: str
    prompt_input: str
    accept: Callable[[str], bool]  # True if the output passes on this task


@dataclass
class CanaryReport:
    ok: bool
    pass_rate: float
    baseline_pass_rate: float
    task_results: list[tuple[str, bool]]
    rationale: str


RunOutput = Callable[[str, str], Awaitable[str]]  # (variant_body, task_input) -> output


class CanaryGuard:
    """Runs a variant against the canary set with the provided `run`
    callback. `baseline_pass_rate` is the most recent accepted-variant
    performance on the same set; any regression is a rejection, period.
    """

    def __init__(self, tasks: Sequence[CanaryTask]):
        if not tasks:
            raise ValueError("canary guard requires at least one task")
        self.tasks = list(tasks)

    async def evaluate(
        self,
        variant_body: str,
        run: RunOutput,
        baseline_pass_rate: float,
    ) -> CanaryReport:
        if not 0.0 <= baseline_pass_rate <= 1.0:
            raise ValueError("baseline_pass_rate must be in [0, 1]")

        results: list[tuple[str, bool]] = []
        for task in self.tasks:
            output = await run(variant_body, task.prompt_input)
            try:
                ok = bool(task.accept(output))
            except Exception:
                ok = False
            results.append((task.name, ok))

        passed = sum(1 for _, ok in results if ok)
        rate = passed / len(self.tasks)

        # Any regression is a rejection — strictly less than baseline fails.
        # Equal-or-better passes.
        if rate < baseline_pass_rate:
            return CanaryReport(
                ok=False,
                pass_rate=rate,
                baseline_pass_rate=baseline_pass_rate,
                task_results=results,
                rationale=(
                    f"canary regression: {rate:.3f} < baseline {baseline_pass_rate:.3f}"
                ),
            )
        return CanaryReport(
            ok=True,
            pass_rate=rate,
            baseline_pass_rate=baseline_pass_rate,
            task_results=results,
            rationale="canary held",
        )
