"""Per-model token pricing (USD per 1M tokens), used to turn raw transcript
token counts into real dollar costs for the office's usage stats bar. Rates
mirror Anthropic's published pricing; an unrecognized model string falls
back to Sonnet-tier rates rather than failing, since transcripts may
reference a model newer than this table.
"""

from __future__ import annotations

# model -> (input $/1M, output $/1M)
_MODEL_RATES: dict[str, tuple[float, float]] = {
    "claude-fable-5": (10.00, 50.00),
    "claude-mythos-5": (10.00, 50.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-opus-4-5": (5.00, 25.00),
    "claude-opus-4-1": (5.00, 25.00),
    "claude-opus-4-0": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-sonnet-4-0": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
_DEFAULT_RATE = (3.00, 15.00)  # Sonnet-tier fallback for unrecognized models.

# Cache tokens are priced as a multiple of the input rate.
_CACHE_WRITE_MULTIPLIER = 1.25  # 5-minute ephemeral cache write.
_CACHE_READ_MULTIPLIER = 0.1


def cost_for_usage(model: str, usage: dict) -> float:
    """USD cost of one transcript line's token usage."""
    input_rate, output_rate = _MODEL_RATES.get(model, _DEFAULT_RATE)
    input_tokens = usage.get("input_tokens") or 0
    output_tokens = usage.get("output_tokens") or 0
    cache_write = usage.get("cache_creation_input_tokens") or 0
    cache_read = usage.get("cache_read_input_tokens") or 0

    cost = input_tokens * input_rate
    cost += output_tokens * output_rate
    cost += cache_write * input_rate * _CACHE_WRITE_MULTIPLIER
    cost += cache_read * input_rate * _CACHE_READ_MULTIPLIER
    return cost / 1_000_000
