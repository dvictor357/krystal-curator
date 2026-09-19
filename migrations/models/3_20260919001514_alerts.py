from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "curator_jobs" (
    "name" VARCHAR(40) NOT NULL PRIMARY KEY,
    "locked_until" TIMESTAMPTZ NOT NULL
);
COMMENT ON TABLE "curator_jobs" IS 'Cross-worker lease so a periodic job runs once per interval, not once per process.';
        CREATE TABLE IF NOT EXISTS "curator_alert_state" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "position_id" VARCHAR(120) NOT NULL,
    "state" JSONB NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "user_id" UUID NOT NULL REFERENCES "curator_users" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_curator_ale_user_id_d45b84" UNIQUE ("user_id", "position_id")
);
COMMENT ON TABLE "curator_alert_state" IS 'What the alert loop last saw for one position; alerts fire on changes.';
        ALTER TABLE "curator_preferences" ADD "telegram_chat_id" VARCHAR(32) NOT NULL DEFAULT '';
        ALTER TABLE "curator_preferences" ADD "alerts" BOOL NOT NULL DEFAULT True;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "curator_preferences" DROP COLUMN "telegram_chat_id";
        ALTER TABLE "curator_preferences" DROP COLUMN "alerts";
        DROP TABLE IF EXISTS "curator_alert_state";
        DROP TABLE IF EXISTS "curator_jobs";"""


MODELS_STATE = (
    "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"
    "9MN/f6efMQ=="
)
