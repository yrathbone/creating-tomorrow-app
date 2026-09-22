"""
Shared helpers for parsing Claude API responses that may contain more than
a single text block - extended thinking blocks, server-side tool calls
(e.g. web search), and citations can all appear alongside the actual
answer, in any position. Assuming content[0] is the answer breaks easily;
these helpers don't.
"""
import json


def log_usage(tool_name: str, response) -> None:
    """Logs token counts only - never prompt/response content - so spend
    can be tracked per tool from Render's log viewer (e.g. grep '[usage]'
    and sum input_tokens/output_tokens) without storing any resume/job/
    profile text anywhere. Every tool module calls this once per successful
    API response. Safe to call even if `response.usage` is ever absent for
    some reason - falls back to logging nothing rather than raising."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    print(
        f"[usage] tool={tool_name} model={getattr(response, 'model', '?')} "
        f"input_tokens={getattr(usage, 'input_tokens', '?')} "
        f"output_tokens={getattr(usage, 'output_tokens', '?')}"
    )


def extract_final_text(response) -> str:
    """Concatenate every text-type content block, in order, skipping
    thinking/tool-use/tool-result blocks. Web search in particular can
    interleave several text blocks around search calls and citations."""
    parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    return "".join(parts).strip()


def extract_json_object(text: str) -> dict:
    """Pull a JSON object out of text that may have commentary, citation
    text, or a markdown code fence around it."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in the model's response text.")
    return json.loads(text[start : end + 1])
