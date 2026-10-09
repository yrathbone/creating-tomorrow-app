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


def describe_provider_error(e) -> str:
    """One short line for the server log when a call to the AI service fails, so a failure can be told apart
    (out of credit, rate limit, busy, bad model name, bad key...) without guessing. It holds the error class, the
    HTTP status, the service's own error type and its first words, and the request id: never anything we sent it."""
    body = getattr(e, "body", None)
    err = body.get("error") if isinstance(body, dict) and isinstance(body.get("error"), dict) else {}
    message = " ".join(str(err.get("message") or getattr(e, "message", "") or "").split())[:160]
    return (
        f"class={type(e).__name__} status={getattr(e, 'status_code', '?')} "
        f"type={err.get('type', '?')} request_id={getattr(e, 'request_id', None) or '?'} message=\"{message}\""
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
