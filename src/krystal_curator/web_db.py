"""Curator account storage; separate from the collector's existing SQLite history."""

import os

from tortoise import fields, models

TORTOISE_ORM = {
    "connections": {
        "default": os.environ.get(
            "CURATOR_DATABASE_URL", "postgres://curator:curator@127.0.0.1:5432/curator"
        )
    },
    "apps": {
        "models": {
            "models": ["krystal_curator.web_db", "aerich.models"],
            "default_connection": "default",
        }
    },
    "use_tz": True,
    "timezone": "UTC",
}


class User(models.Model):
    """One of `email` + `password_hash` (local account) or `address` (SIWE) is set."""

    id = fields.UUIDField(primary_key=True)
    email = fields.CharField(max_length=254, unique=True, null=True)
    password_hash = fields.CharField(max_length=255, null=True)
    address = fields.CharField(max_length=42, unique=True, null=True)  # EIP-55 checksummed
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "curator_users"


class Session(models.Model):
    token_hash = fields.CharField(max_length=64, primary_key=True)
    user = fields.ForeignKeyField("models.User", related_name="sessions", on_delete=fields.CASCADE)
    expires_at = fields.DatetimeField(db_index=True)

    class Meta:
        table = "curator_sessions"


class Nonce(models.Model):
    """Single-use SIWE challenge; consumed by the sign-in that presents it."""

    nonce = fields.CharField(max_length=32, primary_key=True)
    expires_at = fields.DatetimeField(db_index=True)

    class Meta:
        table = "curator_nonces"


class Preferences(models.Model):
    user = fields.OneToOneField(
        "models.User", primary_key=True, related_name="preferences", on_delete=fields.CASCADE
    )
    profile = fields.CharField(max_length=20, default="balanced")
    chain = fields.IntField(default=4663)
    source = fields.CharField(max_length=20, default="krystal")
    size = fields.FloatField(default=10000)
    wallet = fields.CharField(max_length=42, default="")
    telegram_chat_id = fields.CharField(max_length=32, default="")
    alerts = fields.BooleanField(default=True)

    class Meta:
        table = "curator_preferences"


class Watch(models.Model):
    id = fields.IntField(primary_key=True)
    user = fields.ForeignKeyField("models.User", related_name="watchlist", on_delete=fields.CASCADE)
    pool_id = fields.CharField(max_length=180)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "curator_watchlist"
        unique_together = (("user", "pool_id"),)


class Verdict(models.Model):
    """Rotation verdict as shown to a user; the track record compares it with what followed."""

    id = fields.IntField(primary_key=True)
    user = fields.ForeignKeyField("models.User", related_name="verdicts", on_delete=fields.CASCADE)
    position_id = fields.CharField(max_length=120)
    pair = fields.CharField(max_length=60)
    kind = fields.CharField(max_length=10)  # rotate / consider / stay / none
    best_pool = fields.CharField(max_length=60, default="")
    best_pool_id = fields.CharField(max_length=180, default="")
    uplift_day = fields.FloatField(default=0)
    payback_days = fields.FloatField(null=True)
    value = fields.FloatField()
    current_net_day = fields.FloatField()
    fees_total = fields.FloatField()  # position fees (claimed + pending) at that moment
    age_days = fields.FloatField()
    at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "curator_verdicts"
        indexes = (("user", "position_id", "at"),)


class AlertState(models.Model):
    """What the alert loop last saw for one position; alerts fire on changes."""

    id = fields.IntField(primary_key=True)
    user = fields.ForeignKeyField(
        "models.User", related_name="alert_states", on_delete=fields.CASCADE
    )
    position_id = fields.CharField(max_length=120)
    state = fields.JSONField()
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "curator_alert_state"
        unique_together = (("user", "position_id"),)


class Job(models.Model):
    """Cross-worker lease so a periodic job runs once per interval, not once per process."""

    name = fields.CharField(max_length=40, primary_key=True)
    locked_until = fields.DatetimeField()

    class Meta:
        table = "curator_jobs"


class RateLimit(models.Model):
    key = fields.CharField(max_length=80, primary_key=True)
    window = fields.BigIntField()
    count = fields.IntField(default=1)

    class Meta:
        table = "curator_rate_limits"
