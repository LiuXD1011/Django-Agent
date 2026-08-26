import hashlib
import os
import time
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import fcntl

from django.conf import settings
from django.db import OperationalError, transaction
from django.utils import timezone

from .models import ModelRateLimitState


def _state_key(provider: str, model_id: str) -> str:
    raw = f"{provider}:{model_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def _bucket_lock(key: str):
    root = Path(settings.BASE_DIR) / ".cache" / "model-rate-limits"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{key}.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.chmod(path, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def acquire_model_tokens(provider: str, model_id: str, estimated_tokens: int) -> None:
    """Acquire a cross-process token budget from the SQLite-backed bucket."""
    capacity = float(getattr(settings, "MODEL_RATE_LIMIT_TPM", 120_000))
    refill = capacity / 60.0
    amount = min(max(float(estimated_tokens), 1.0), capacity)
    key = _state_key(provider, model_id)
    while True:
        now = timezone.now()
        wait_seconds = 0.0
        try:
            with _bucket_lock(key), transaction.atomic():
                state, _created = ModelRateLimitState.objects.get_or_create(
                    key=key,
                    defaults={
                        "provider": provider,
                        "model_id": model_id,
                        "available_tokens": capacity,
                        "capacity": capacity,
                        "refill_per_second": refill,
                        "last_refill_at": now,
                    },
                )
                elapsed = max(0.0, (now - state.last_refill_at).total_seconds())
                available = min(capacity, state.available_tokens + elapsed * refill)
                if state.blocked_until and state.blocked_until > now:
                    wait_seconds = (state.blocked_until - now).total_seconds()
                elif available >= amount:
                    state.available_tokens = available - amount
                    state.capacity = capacity
                    state.refill_per_second = refill
                    state.last_refill_at = now
                    state.blocked_until = None
                    state.save(update_fields=[
                        "available_tokens", "capacity", "refill_per_second", "last_refill_at", "blocked_until"
                    ])
                    return
                else:
                    wait_seconds = (amount - available) / max(refill, 1.0)
                    state.available_tokens = available
                    state.capacity = capacity
                    state.refill_per_second = refill
                    state.last_refill_at = now
                    state.save(update_fields=["available_tokens", "capacity", "refill_per_second", "last_refill_at"])
        except OperationalError:
            time.sleep(0.1)
            continue
        time.sleep(min(max(wait_seconds, 0.05), 60.0))


def defer_model_calls(provider: str, model_id: str, retry_after: float) -> None:
    now = timezone.now()
    blocked_until = now + timedelta(seconds=max(0.0, retry_after))
    key = _state_key(provider, model_id)
    while True:
        try:
            with _bucket_lock(key), transaction.atomic():
                state, _created = ModelRateLimitState.objects.get_or_create(
                    key=key,
                    defaults={"provider": provider, "model_id": model_id, "last_refill_at": now},
                )
                if not state.blocked_until or state.blocked_until < blocked_until:
                    state.blocked_until = blocked_until
                    state.save(update_fields=["blocked_until"])
            return
        except OperationalError:
            time.sleep(0.1)
