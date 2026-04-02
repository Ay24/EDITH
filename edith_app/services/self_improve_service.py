from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

from edith_app.models import ChatMessage
from edith_app.services.agent_service import AgentService


@dataclass(slots=True)
class ImproveMetrics:
    compile_ok: bool
    success_rate: float
    avg_latency_ms: float
    p95_latency_ms: float
    total_samples: int
    baseline_score: int


class SelfImproveService:
    def __init__(
        self,
        project_root: str,
        telemetry_path: str,
        overrides_path: str,
        agent: AgentService,
    ) -> None:
        self._project_root = Path(project_root)
        self._telemetry_path = Path(telemetry_path)
        self._overrides_path = Path(overrides_path)
        self._agent = agent

    def status_report(self) -> str:
        metrics = self._metrics()
        return self._format_metrics(metrics)

    def propose_skill(self, goal: str, history: list[ChatMessage]) -> str:
        slug = self._slug(goal) or "new_skill"
        out_dir = self._project_root / "data" / "generated_skills"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{slug}.md"
        prompt = (
            "Design a new assistant capability as a compact spec.\n"
            "Return markdown with these sections:\n"
            "- Goal\n- User commands\n- Tool actions\n- Safety gates\n- Verification tests\n"
            f"Capability goal: {goal}"
        )
        spec = self._agent.plan(prompt, history)
        if "preparing the local model" in spec.lower() or "warming up" in spec.lower():
            spec = (
                f"## Goal\n{goal}\n\n"
                "## User commands\n- Add 3 to 5 natural commands for this capability.\n\n"
                "## Tool actions\n- Define deterministic action sequence and fallback path.\n\n"
                "## Safety gates\n- Ask for confirmation on high-risk actions.\n\n"
                "## Verification tests\n- Add at least 5 pass/fail command tests."
            )
        out_path.write_text(spec, encoding="utf-8")
        return f"Generated capability spec at {out_path}."

    def run(self, goal: str, history: list[ChatMessage], apply: bool = False) -> str:
        metrics = self._metrics()
        prompt = (
            "You are a runtime reliability engineer for a local desktop assistant.\n"
            "Given the metrics, suggest compact, low-risk improvements for speed, stability, and voice quality.\n"
            "Do not suggest model retraining. Keep it practical for 16GB RAM consumer hardware.\n"
            f"User goal: {goal}\n"
            f"Metrics:\n{self._format_metrics(metrics)}\n"
            "Provide:\n"
            "1) top 5 improvements\n"
            "2) what to monitor\n"
            "3) one low-risk next action."
        )
        proposal = self._agent.plan(prompt, history)
        if "preparing the local model" in proposal.lower() or "warming up" in proposal.lower():
            proposal = self._fallback_proposal(metrics)
        if not apply:
            return (
                f"{self._format_metrics(metrics)}\n\n"
                "Self-improvement proposal (safe, dry-run):\n"
                f"{proposal}\n\n"
                "Say: self improve apply to apply safe runtime tuning only."
            )

        applied = self._apply_safe_overrides(metrics)
        return (
            f"{self._format_metrics(metrics)}\n\n"
            f"Applied safe runtime tuning: {applied}\n"
            f"Proposal summary:\n{proposal}"
        )

    def _metrics(self) -> ImproveMetrics:
        compile_ok = self._compile_ok()
        rows = self._read_telemetry(limit=160)
        total = len(rows)
        if total == 0:
            success_rate = 1.0
            avg_latency = 0.0
            p95 = 0.0
        else:
            ok_count = sum(1 for row in rows if row.get("status") == "ok")
            success_rate = ok_count / total
            latencies = sorted(float(row.get("latency_ms", 0)) for row in rows)
            avg_latency = sum(latencies) / len(latencies)
            idx = min(len(latencies) - 1, int(math.ceil(0.95 * len(latencies))) - 1)
            p95 = latencies[idx]
        score = self._score(compile_ok, success_rate, p95)
        return ImproveMetrics(
            compile_ok=compile_ok,
            success_rate=success_rate,
            avg_latency_ms=avg_latency,
            p95_latency_ms=p95,
            total_samples=total,
            baseline_score=score,
        )

    def _compile_ok(self) -> bool:
        try:
            result = subprocess.run(
                ["python", "-m", "compileall", ".", "-q"],
                cwd=self._project_root,
                capture_output=True,
                text=True,
                timeout=120,
                shell=False,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _read_telemetry(self, limit: int) -> list[dict]:
        if not self._telemetry_path.exists():
            return []
        try:
            lines = self._telemetry_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
        rows: list[dict] = []
        for line in lines[-limit:]:
            try:
                parsed = json.loads(line)
            except Exception:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
        return rows

    def _score(self, compile_ok: bool, success_rate: float, p95_latency_ms: float) -> int:
        score = 0.0
        score += 35.0 if compile_ok else 10.0
        score += max(0.0, min(40.0, success_rate * 40.0))
        if p95_latency_ms <= 0:
            score += 15.0
        elif p95_latency_ms <= 1200:
            score += 25.0
        elif p95_latency_ms <= 2200:
            score += 18.0
        elif p95_latency_ms <= 3500:
            score += 10.0
        else:
            score += 4.0
        return int(round(min(100.0, score)))

    def _apply_safe_overrides(self, metrics: ImproveMetrics) -> str:
        command_timeout = 35
        voice_threshold = 0.45
        if metrics.p95_latency_ms > 2600:
            command_timeout = 45
            voice_threshold = 0.5
        if metrics.success_rate < 0.85:
            command_timeout = max(command_timeout, 50)
            voice_threshold = max(voice_threshold, 0.55)

        payload = {
            "command_timeout_seconds": command_timeout,
            "voice_confidence_threshold": round(voice_threshold, 2),
        }
        try:
            self._overrides_path.parent.mkdir(parents=True, exist_ok=True)
            self._overrides_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return f"timeout={command_timeout}s, voice_confidence_threshold={payload['voice_confidence_threshold']}"
        except Exception as exc:
            return f"failed to write overrides ({exc})"

    def _format_metrics(self, metrics: ImproveMetrics) -> str:
        return (
            "Runtime baseline:\n"
            f"- score: {metrics.baseline_score}/100\n"
            f"- compile: {'PASS' if metrics.compile_ok else 'FAIL'}\n"
            f"- success_rate: {metrics.success_rate * 100:.1f}%\n"
            f"- avg_latency: {metrics.avg_latency_ms:.0f}ms\n"
            f"- p95_latency: {metrics.p95_latency_ms:.0f}ms\n"
            f"- telemetry_samples: {metrics.total_samples}"
        )

    def _fallback_proposal(self, metrics: ImproveMetrics) -> str:
        lines = [
            "1. Keep voice confidence gating enabled to reduce bad triggers in noisy input.",
            "2. Keep command watchdog timeout at a safe level to prevent UI lockups.",
            "3. Run preflight at startup and fix model readiness before long demos.",
            "4. Use preview-first organization and confirm before apply for safer file actions.",
            "5. Track telemetry failure spikes and tune only one parameter per run.",
            "Monitor: success rate >= 92% and p95 latency < 2200ms.",
            "Next action: run preflight, then test 20 mixed commands and review telemetry.",
        ]
        if metrics.p95_latency_ms > 2600:
            lines[-1] = "Next action: apply safe tuning and re-test 20 mixed commands."
        return "\n".join(lines)

    def _slug(self, text: str) -> str:
        lowered = text.lower().strip()
        chars = []
        for ch in lowered:
            if ch.isalnum():
                chars.append(ch)
            elif ch in {" ", "-", "_"}:
                chars.append("_")
        slug = "".join(chars).strip("_")
        while "__" in slug:
            slug = slug.replace("__", "_")
        return slug[:64]
