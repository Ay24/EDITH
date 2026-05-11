import re
with open(r'f:\EDITH-AI\edith_app\assistant.py', 'r', encoding='utf-8') as f:
    code = f.read()

replacements = [
    (r'self\.agent\.reply\(([^)]+)\)', r'self.agent.reply(\1, context_kwargs=self._build_dynamic_context())'),
    (r'self\.agent\.brainstorm\(([^)]+)\)', r'self.agent.brainstorm(\1, context_kwargs=self._build_dynamic_context())'),
    (r'self\.agent\.plan\(([^)]+)\)', r'self.agent.plan(\1, context_kwargs=self._build_dynamic_context())'),
    (r'self\.agent\.quick_think\(([^)]+)\)', r'self.agent.quick_think(\1, context_kwargs=self._build_dynamic_context())'),
    (r'self\.agent\.think_with_user\(([^)]+)\)', r'self.agent.think_with_user(\1, context_kwargs=self._build_dynamic_context())')
]

for pat, repl in replacements:
    code = re.sub(pat, repl, code)

with open(r'f:\EDITH-AI\edith_app\assistant.py', 'w', encoding='utf-8') as f:
    f.write(code)
