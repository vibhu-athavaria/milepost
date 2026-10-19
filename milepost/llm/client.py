"""The one place that calls an LLM provider (SPEC 3 and 9.3). LiteLLM is imported lazily."""

import importlib.util
import time
from collections.abc import Callable
from typing import Protocol

from milepost.errors import EnvironmentProblem, ProviderError

RETRIES = 2
BACKOFF_SECONDS = 2.0


def model_extra_available() -> bool:
    """True when the optional `model` extra (litellm) is installed."""
    return importlib.util.find_spec("litellm") is not None


class LlmClient(Protocol):
    def complete(self, model: str, system: str, user: str) -> str: ...


class LiteLlmClient:
    def complete(self, model: str, system: str, user: str) -> str:
        try:
            import litellm
        except ImportError as error:
            raise EnvironmentProblem(
                "drafting with a separate model needs the `model` extra: "
                "pip install 'milepost[model]' (or let Claude write the notes)"
            ) from error

        response = litellm.completion(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return str(response.choices[0].message.content or "")


def complete_with_retries(
    client: LlmClient,
    model: str,
    system: str,
    user: str,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Call the client; retry twice with growing backoff; then raise ProviderError (exit 4)."""
    last: Exception | None = None
    for attempt in range(RETRIES + 1):
        try:
            return client.complete(model, system, user)
        except Exception as error:  # noqa: BLE001 - any provider failure is retried the same way
            last = error
            if attempt < RETRIES:
                sleep(BACKOFF_SECONDS * (attempt + 1))
    raise ProviderError(f"provider failed after {RETRIES + 1} attempts: {last}") from last
