"""The configured AI model must still support what this app does with it.

Every tool here forces a tool call (`tool_choice` of type "tool"). Anthropic's API errors page (retrieved 2026-11-01,
https://platform.claude.com/docs/en/api/errors) says Claude Opus 5.5, Sonnet 5.5, Fable 5.1 and Mythos 5.1 reject that with a 400,
so switching CT_MODEL to one of them would break every tool at once. This test fails first, in CI, instead of the live site.
If the code is later changed to not force tool calls, update UNSUPPORTED and this docstring.
"""
import os
import re
import unittest

UNSUPPORTED_FOR_FORCED_TOOL_USE = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1", "claude-mythos-5-1")
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _blocked(model: str) -> bool:
    return any(model == m or model.startswith(m + "-") for m in UNSUPPORTED_FOR_FORCED_TOOL_USE)


class ModelConfig(unittest.TestCase):
    def test_the_model_named_in_render_yaml_supports_forced_tool_use(self):
        with open(os.path.join(ROOT, "render.yaml"), encoding="utf-8") as f:
            text = f.read()
        m = re.search(r"key:\s*CT_MODEL\s*\n\s*value:\s*([\w.\-]+)", text)
        self.assertIsNotNone(m, "render.yaml should name CT_MODEL")
        self.assertFalse(_blocked(m.group(1)), f"{m.group(1)} does not support the forced tool calls every tool uses")

    def test_the_default_model_in_every_module_supports_forced_tool_use(self):
        backend = os.path.join(ROOT, "backend")
        found = 0
        for folder in (backend, os.path.join(backend, "career")):
            for name in os.listdir(folder):
                if not name.endswith(".py"):
                    continue
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    for model in re.findall(r'os\.environ\.get\("CT_MODEL",\s*"([^"]+)"\)', f.read()):
                        found += 1
                        self.assertFalse(_blocked(model), f"{name}: default model {model} does not support forced tool calls")
        self.assertGreaterEqual(found, 8, "expected the model default in each AI module")

    def test_the_guard_recognises_the_blocked_models(self):
        self.assertTrue(_blocked("claude-sonnet-5-5"))
        self.assertTrue(_blocked("claude-opus-5-5-20261101"))
        self.assertFalse(_blocked("claude-sonnet-5"))
