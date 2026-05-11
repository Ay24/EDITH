import re
with open(r'f:\EDITH-AI\edith_app\services\agent_service.py', 'r', encoding='utf-8') as f:
    code = f.read()

def repl(m):
    return m.group(1) + 'context_kwargs=context_kwargs,\n        )'

code = re.sub(r'(temperature=decision\.temperature,\n        )\)', repl, code)

code = re.sub(
    r'def specialist_reply\([\s\S]*?lane: str = \x22chat\x22,\n\s+prefer_fast: bool = False,\n\s+\) -> str:',
    'def specialist_reply(\n        self,\n        prompt: str,\n        history: Iterable[ChatMessage],\n        specialist_instruction: str,\n        lane: str = \"chat\",\n        prefer_fast: bool = False,\n        context_kwargs: dict[str, str] | None = None,\n    ) -> str:',
    code
)

code = re.sub(
    r'def stream_specialist_reply\([\s\S]*?on_token: Callable\[\[str\], None\] \| None = None,\n\s+\) -> str:',
    'def stream_specialist_reply(\n        self,\n        prompt: str,\n        history: Iterable[ChatMessage],\n        specialist_instruction: str,\n        lane: str = \"chat\",\n        prefer_fast: bool = False,\n        on_token: Callable[[str], None] | None = None,\n        context_kwargs: dict[str, str] | None = None,\n    ) -> str:',
    code
)

code = re.sub(r'def think_with_user\(self, prompt: str, history: Iterable\[ChatMessage\]\) -> str:', 'def think_with_user(self, prompt: str, history: Iterable[ChatMessage], context_kwargs: dict[str, str] | None = None) -> str:', code)
code = re.sub(r'planner = self\.plan\(prompt, history\)', 'planner = self.plan(prompt, history, context_kwargs=context_kwargs)', code)
code = re.sub(r'creative = self\.brainstorm\(prompt, history\)', 'creative = self.brainstorm(prompt, history, context_kwargs=context_kwargs)', code)
code = re.sub(r'tactical = self\.quick_think\(prompt, history\)', 'tactical = self.quick_think(prompt, history, context_kwargs=context_kwargs)', code)

code = re.sub(
    r'def _run_model\([\s\S]*?temperature: float = 0\.45,\n\s+\) -> str:',
    'def _run_model(\n        self,\n        model: str,\n        prompt: str,\n        history: Iterable[ChatMessage],\n        system_instruction: str,\n        max_predict: int = 160,\n        timeout_seconds: int = 24,\n        temperature: float = 0.45,\n        context_kwargs: dict[str, str] | None = None,\n    ) -> str:',
    code
)

code = re.sub(
    r'def _run_model_stream\([\s\S]*?on_token: Callable\[\[str\], None\] \| None = None,\n\s+\) -> str:',
    'def _run_model_stream(\n        self,\n        model: str,\n        prompt: str,\n        history: Iterable[ChatMessage],\n        system_instruction: str,\n        max_predict: int = 160,\n        timeout_seconds: int = 24,\n        temperature: float = 0.45,\n        on_token: Callable[[str], None] | None = None,\n        context_kwargs: dict[str, str] | None = None,\n    ) -> str:',
    code
)

code = re.sub(r'def _compose_prompt\(self, system_instruction: str, prompt: str, history: Iterable\[ChatMessage\]\) -> str:', 'def _compose_prompt(self, system_instruction: str, prompt: str, history: Iterable[ChatMessage], context_kwargs: dict[str, str] | None = None) -> str:', code)
code = re.sub(r'self\._compose_prompt\(system_instruction, prompt, history\)', 'self._compose_prompt(system_instruction, prompt, history, context_kwargs)', code)

code = re.sub(
    r'now_dt = datetime\.now\(\)',
    'now_dt = datetime.now()\n        if context_kwargs:\n            try:\n                system_instruction = system_instruction.format(**context_kwargs)\n            except KeyError:\n                pass',
    code
)

with open(r'f:\EDITH-AI\edith_app\services\agent_service.py', 'w', encoding='utf-8') as f:
    f.write(code)
