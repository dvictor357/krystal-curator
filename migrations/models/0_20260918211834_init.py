from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "curator_rate_limits" (
    "key" VARCHAR(80) NOT NULL PRIMARY KEY,
    "window" BIGINT NOT NULL,
    "count" INT NOT NULL
);
CREATE TABLE IF NOT EXISTS "curator_users" (
    "id" UUID NOT NULL PRIMARY KEY,
    "email" VARCHAR(254) NOT NULL UNIQUE,
    "password_hash" VARCHAR(255) NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS "curator_preferences" (
    "profile" VARCHAR(20) NOT NULL,
    "chain" INT NOT NULL,
    "source" VARCHAR(20) NOT NULL,
    "size" DOUBLE PRECISION NOT NULL,
    "wallet" VARCHAR(42) NOT NULL,
    "user_id" UUID NOT NULL PRIMARY KEY REFERENCES "curator_users" ("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS "curator_sessions" (
    "token_hash" VARCHAR(64) NOT NULL PRIMARY KEY,
    "expires_at" TIMESTAMPTZ NOT NULL,
    "user_id" UUID NOT NULL REFERENCES "curator_users" ("id") ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS "idx_curator_ses_expires_a140ca" ON "curator_sessions" ("expires_at");
CREATE TABLE IF NOT EXISTS "curator_watchlist" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "pool_id" VARCHAR(180) NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL,
    "user_id" UUID NOT NULL REFERENCES "curator_users" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_curator_wat_user_id_89178f" UNIQUE ("user_id", "pool_id")
);
CREATE TABLE IF NOT EXISTS "aerich" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(100) NOT NULL,
    "content" JSONB NOT NULL
);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """


MODELS_STATE = (
    "eJztmmtv4kYUhv8K8qdUaiMwhtCqqkQI6dJNIALSrXa1sgZ7gBFmxmuPS+iW/96ZwfcL4A"
    "TMpeEDgnPm2DPP3N459ndpTnRo2NdPFhxDC2IN2tIvpe8SBnPIfqS5fyxJwDQDJzdQMDJE"
    "ec2xACWWasYCRja1gEZZkTEwbMhMOrQ1C5kUEcys2DEMbiQaK4jwJDA5GH1zoErJBNIptJ"
    "jjy1dmRliHL6Ky4q85U8cIGnqk8o4NLRXpvALCqdKlKRzPz527e1Gc33OkasRw5jgWYi7p"
    "lGA/xnGQfs0DuW8CMWQNhXqoQby+LgbPtK47M1DLgX6l9cCgwzFwDBoCMFIDm6Sq3d5QHb"
    "SHqirlQKYRzHEjTEVnrtbXDRCsu5jfoPWh2b+q1n8Q7SU2nVjCKQBJKxEIKFiHCtYBXNMi"
    "Y8Ram4DbmgIrHW4oJAaXVfc1WD1DwDUYXT7EETAAG4dedfaOV5qDF9WAeEKn7K9c3oD7z2"
    "ZfEJfLgjhhU2I9bbquRxYuDj4ArU3ZrZKYO5imU/bLxxiz+h6KsVKvVw9Fd8Ir8ZNcUW6U"
    "RrWuNFgRUVHfcrMBeKc7jNG0iWNpuUZtEFHgoJ1ZS5sC41zHrI3+SWF8bxCQMWi9gBjiMY"
    "84FORKmX2KX3Pves+3D+3SU7/d6gw6vS6/y3xpfzMCJzcxA6ICQr/dfIjxXQDDgDTPKA4i"
    "ChzFxQxfRd5h+Cpy5vDlrtWKq4jxLLTVccMIaLMFsHQ14SEySd0WuYBI9ksPwyFhX6JvOq"
    "wtfEdK6QxXbj27FzlHmRFYg/tbYOHLs7DEYi1n7YXrYd5qDlrNu7a0ioCPcuauuTyPWwAG"
    "E9FeXjNeD5djn7F7QHNEpRRNGzh3UrS8H1SDlz+iop3BZZ5J7xbfz4w/6uCKzvjGLhtWI3"
    "vDargbVra6XbBmkkWS9S2aZAqvIKY45XVI5Gvl9bMsV6s3crlab9SUm5tao+xLsKRrkxa7"
    "7fzO5VikS5L6TCMOTtnYstWuV7445pUTlrpv2sX2t/AOoG2vW59Ydj3XTouuvS58xBWXkh"
    "nE6hTY0zwLbzTq4tbfurLD+ltXMtdf7tq8/sIXE1nQVkHKWnDHoFE0h+noo5Ex9Lobeu39"
    "2M8acSLZnGHnsT0YNh+fxJHC9o4UzWGbe+ToQcO1XtVjveRfpPSpM/xQ4n9Ln3vddjxF5J"
    "cbfpZ4nYBDiYrJQgV6GKRn9kyRxf50EnRH3mtfn6JLLPjbjiL3xIJogj/C5YEPI6eBdM/H"
    "kcJ2UEE9Zfv0emP73skbdsSNM9+0PkbKXfp17GCNMyiJO/Ev5bdD5SwOk4WHc4CMPMrED7"
    "g4USLXdlElrFR2HrOmxBOZJrDtBWGTOa8CTAQWl3YrkHhtJ+K1DcRriccdFuQ8XqH8opHF"
    "KL9i6bMG6j1sLN15diZS0F0SEkowx1k19GQhdCKMpWbcyPuPfWgA6p4x0zVN6BB6ZmMgS9"
    "bEHg9QbWogO2UK5aH0iV/mkhjlEmzhR92RlxnSgXop/u1YYy9TbIHrzp6zYJtD367HVorA"
    "9QfddoUbGeb7Vblf/NOTSYjBzwdf3yJ8M9OXqbo3JXfpjoLTlWJ7eUy/4W0TtxfyKLAg5A"
    "K1V2WnZyCVDQ9BKo3kqybv2ut/or3es3DvWbj3LNxWldKEFkqXKa5no04BQZmTScG9K5E3"
    "KpG/oeUdHXdVIqGQC1QiB8kC8UmVg7Bb/ALpVso76bzyBp1XTuo8gilMe83ij0Gvm/WehR"
    "8SV3dIo6V/S9457Mxob4DLYUQknMf06rH5Vxx366F3GxcH/AK3x34pY/UfJ+gEVQ=="
)
