from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "curator_verdicts" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "position_id" VARCHAR(120) NOT NULL,
    "pair" VARCHAR(60) NOT NULL,
    "kind" VARCHAR(10) NOT NULL,
    "best_pool" VARCHAR(60) NOT NULL,
    "best_pool_id" VARCHAR(180) NOT NULL,
    "uplift_day" DOUBLE PRECISION NOT NULL,
    "payback_days" DOUBLE PRECISION,
    "value" DOUBLE PRECISION NOT NULL,
    "current_net_day" DOUBLE PRECISION NOT NULL,
    "fees_total" DOUBLE PRECISION NOT NULL,
    "age_days" DOUBLE PRECISION NOT NULL,
    "at" TIMESTAMPTZ NOT NULL,
    "user_id" UUID NOT NULL REFERENCES "curator_users" ("id") ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS "idx_curator_ver_user_id_53cbce" ON "curator_verdicts" ("user_id", "position_id", "at");
COMMENT ON TABLE "curator_verdicts" IS 'Rotation verdict as shown to a user; the track record compares it with what followed.';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "curator_verdicts";"""


MODELS_STATE = (
    "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"
)
