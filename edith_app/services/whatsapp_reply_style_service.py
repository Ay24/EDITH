from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from pathlib import Path


@dataclass(slots=True)
class ReplySample:
    message: str
    decision: str


@dataclass(slots=True)
class ReplyStyleState:
    enabled: bool = False
    mode: str = "yes_no"
    auto_send_enabled: bool = False
    samples: list[ReplySample] = field(default_factory=list)
    yes_keywords: dict[str, int] = field(default_factory=dict)
    no_keywords: dict[str, int] = field(default_factory=dict)


class WhatsAppReplyStyleService:
    def __init__(self, state_path: str) -> None:
        self._state_path = Path(state_path)
        self._state = ReplyStyleState()
        self._load()

    def set_enabled(self, enabled: bool) -> str:
        self._state.enabled = enabled
        self._save()
        if enabled:
            return "Experimental WhatsApp yes/no auto-reply is now ON."
        return "Experimental WhatsApp yes/no auto-reply is now OFF."

    def set_mode(self, mode: str) -> str:
        normalized = mode.strip().lower()
        if normalized not in {"yes_no", "contextual"}:
            return "Invalid mode. Use yes_no or contextual."
        self._state.mode = normalized
        self._save()
        return f"WhatsApp experimental reply mode set to {normalized}."

    def set_auto_send(self, enabled: bool) -> str:
        self._state.auto_send_enabled = enabled
        self._save()
        if enabled:
            return "WhatsApp experimental auto-send is ON."
        return "WhatsApp experimental auto-send is OFF."

    def status(self) -> str:
        return (
            "WhatsApp yes/no auto-reply status:\n"
            f"- Enabled: {self._state.enabled}\n"
            f"- Mode: {self._state.mode}\n"
            f"- Auto-send: {self._state.auto_send_enabled}\n"
            f"- Learned samples: {len(self._state.samples)}\n"
            f"- Learned yes-keywords: {len(self._state.yes_keywords)}\n"
            f"- Learned no-keywords: {len(self._state.no_keywords)}"
        )

    @property
    def enabled(self) -> bool:
        return self._state.enabled

    @property
    def mode(self) -> str:
        return self._state.mode

    @property
    def auto_send_enabled(self) -> bool:
        return self._state.auto_send_enabled

    def propose_yes_no(self, message: str) -> tuple[str, float, str]:
        tokens = self._tokens(message)
        if not tokens:
            return "No", 0.5, "empty_message_default"

        yes_score = 0
        no_score = 0
        for token in tokens:
            yes_score += self._state.yes_keywords.get(token, 0)
            no_score += self._state.no_keywords.get(token, 0)

        keyword_yes = {"ok", "okay", "approved", "confirm", "book", "buy", "proceed", "accept", "yes"}
        keyword_no = {"cancel", "stop", "reject", "decline", "deny", "avoid", "no", "not"}
        yes_score += sum(1 for token in tokens if token in keyword_yes)
        no_score += sum(1 for token in tokens if token in keyword_no)

        total = yes_score + no_score
        if total <= 0:
            return "No", 0.51, "cold_start_default_no"
        if yes_score >= no_score:
            confidence = yes_score / max(total, 1)
            return "Yes", confidence, "learned_yes"
        confidence = no_score / max(total, 1)
        return "No", confidence, "learned_no"

    def learn(self, message: str, approved: bool) -> None:
        decision = "Yes" if approved else "No"
        sample = ReplySample(message=message.strip(), decision=decision)
        self._state.samples.append(sample)
        if len(self._state.samples) > 600:
            self._state.samples = self._state.samples[-600:]

        target = self._state.yes_keywords if approved else self._state.no_keywords
        for token in self._tokens(message):
            target[token] = target.get(token, 0) + 1
        self._save()

    def _tokens(self, text: str) -> list[str]:
        return [t for t in re.findall(r"[a-z0-9']+", text.lower()) if len(t) > 1]

    def _load(self) -> None:
        if not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            samples_data = data.get("samples", [])
            samples = []
            for item in samples_data:
                if not isinstance(item, dict):
                    continue
                message = str(item.get("message", "")).strip()
                decision = str(item.get("decision", "")).strip()
                if message and decision in {"Yes", "No"}:
                    samples.append(ReplySample(message=message, decision=decision))
            self._state = ReplyStyleState(
                enabled=bool(data.get("enabled", False)),
                mode=str(data.get("mode", "yes_no")).strip().lower() if str(data.get("mode", "yes_no")).strip().lower() in {"yes_no", "contextual"} else "yes_no",
                auto_send_enabled=bool(data.get("auto_send_enabled", False)),
                samples=samples,
                yes_keywords={str(k): int(v) for k, v in dict(data.get("yes_keywords", {})).items()},
                no_keywords={str(k): int(v) for k, v in dict(data.get("no_keywords", {})).items()},
            )
        except Exception:
            self._state = ReplyStyleState()

    def _save(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "enabled": self._state.enabled,
            "mode": self._state.mode,
            "auto_send_enabled": self._state.auto_send_enabled,
            "samples": [{"message": s.message, "decision": s.decision} for s in self._state.samples[-300:]],
            "yes_keywords": self._state.yes_keywords,
            "no_keywords": self._state.no_keywords,
        }
        self._state_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
