from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "curator_usage" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "day" DATE NOT NULL,
    "route" VARCHAR(60) NOT NULL,
    "count" INT NOT NULL,
    "errors" INT NOT NULL,
    "ms_total" DOUBLE PRECISION NOT NULL,
    "user_id" UUID NOT NULL REFERENCES "curator_users" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_curator_usa_user_id_f7cbc3" UNIQUE ("user_id", "day", "route")
);
COMMENT ON TABLE "curator_usage" IS 'Per user, per day, per route request counters: who uses what, how much, how slowly.';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "curator_usage";"""


MODELS_STATE = (
    "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"
)
