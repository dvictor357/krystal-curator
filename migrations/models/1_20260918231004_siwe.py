from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "curator_nonces" (
    "nonce" VARCHAR(32) NOT NULL PRIMARY KEY,
    "expires_at" TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS "idx_curator_non_expires_6522b0" ON "curator_nonces" ("expires_at");
COMMENT ON TABLE "curator_nonces" IS 'Single-use SIWE challenge; consumed by the sign-in that presents it.';
        ALTER TABLE "curator_users" ADD "address" VARCHAR(42) UNIQUE;
        ALTER TABLE "curator_users" ALTER COLUMN "email" DROP NOT NULL;
        ALTER TABLE "curator_users" ALTER COLUMN "password_hash" DROP NOT NULL;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "uid_curator_use_address_619ced";
        ALTER TABLE "curator_users" DROP COLUMN "address";
        ALTER TABLE "curator_users" ALTER COLUMN "email" SET NOT NULL;
        ALTER TABLE "curator_users" ALTER COLUMN "password_hash" SET NOT NULL;
        DROP TABLE IF EXISTS "curator_nonces";"""


MODELS_STATE = (
    "eJztWm1P4zgQ/itWP4FuQW36Qu9FJxUot72FFtFynHa1CiZxW4vU7sbOQW+P/362kzTvbQ"
    "J9oSx8QDD2OPYz4/EzY38vTaiJLHbYpcRApV/A9xKBE/lHtOEDKMHpNBBLAYd3luppODbk"
    "1NaJ7Kqa4B3jNjS4aB1CiyEhMhEzbDzlmBKp08dkZKEDhyHQ79y0gTGGloXICP0KDEqYM0"
    "EmuJsBPkaA4RE5wET8DTmY2oghwhnA/FB+yaSG+JQYbJWDOgR/c5DO6QiJvrYY+stXIcbE"
    "RI9igd6/03t9iJFlRlAjPlyqSeezqRKfjKF9pjrLOd/pBrWcCYkoTGd8TMlcQ6xKSkeIII"
    "EuMkNQEseyPOx9kTtjIeC2g+ZTNQOBiYbQsaRBpLY7iUBW0vVub6D32wNdLyWM5WuEoPZE"
    "ElVhaCywUyhM4KMuAedj8W9Ve3K/E0Dh9pIf/Kt1dfKxdbVX1fblB6nwFteZul6Lppqe1B"
    "CQQ3cQhX0ANnqcYmE6HfIk4qcCNI4nKB31qGYMetNTPfT/eI4hfMF2LLEA+UHnot0ftC4u"
    "5fATxr5ZCq7WoC1bNCWdxaR7jZiV5oOAm87gI5D/gs+9bluhSRkf2eqLQb/B55KcE3Q4FX"
    "HiQYdmGEhf7Iue5P4a3oeMLgV30Lh/gLapJ1qoRrP6Jpsm2iQugQSOlI0kmnKeXvC7tNEQ"
    "2UiFtZTYGG7OFSGnMYVlYTLb3i8IUSI82jo2k1vm+rpzmr5dQiqxveI42DyUijsXrBZsET"
    "cyuT4f9ma1zsUhaWrTIbYKnQAhldWcAcnQE3jXHMQ7aEHhh/501nwWaOUcZ4FWzjwLZJME"
    "PgBanO2YJGHuEJ6O8rx/DGMx33VhXGs0qutCdyQncaBVake1ZrVRa4ouaqJzydECwDvdQQ"
    "xNRh27GG8JNDbotPf2jHFo7arPMvxvCsZnFoUZTusrxCAeSo11gVwpi5/Nx9zT3vXxeRtc"
    "XrVPOv1OrxvlIapRioQAcwXCVbt1HsP3QdL9FC6Y7cWBxga9eDPuW8tDv2vZ9Lum6PeLiF"
    "iUcyTt0iNoQMUvZZuOWAtMz4U8unXtDbKLNCOQBt+34cOcnoUplli5WC9y3fyk1T9pnbZL"
    "T6tjtVcCu3M8wbyUwmmDxlyMVtpBt2T/LTLaezQrsum97m8u4W7mObCa2QdWs7ws4X4Qyx"
    "RZWgLrYzzKJF6BzuaY1zohd5nXz5pWrR5p5WqjWa8dHdWb5TkFSzYt4mLHnT8kHYuYJMnP"
    "DOqQlIMtm+36/TeHeeUVU91XUk7oI8bc1SfCrt+UK+gyt/MWIy6n94joY8jGRQJvVOvNxd"
    "9GLUf8bdQy469sei94/pgFzw+vskC35bP2+SW6RMBfloqcURvhEfmEZmtORl4HpCtORzZ2"
    "girUU45P3xrLz065sJx3lCIzBXQIbtEEYusW/ARup5CxByoWIc+wW7BnUQNaABqKbu0Dao"
    "Nbsc+FKzLRKK8g9wFmgKGUu8pVD/6Cw7xYqNnGNUDpt6FDDGkXoL4kf9V+X1cdZT03A8rQ"
    "RdjSXOFZRMnD8DXyJK2ehyiJXtml1XotXluN7J5C1y9xxZXAve0sNQZ4PRfg9QWA1+OAe7"
    "GoCNQhlbfm06uptkZSfhtJJJ7B9aOam+H6m/VusUCzR6yZZ/IdIf+ed77ksUPoLilUA4gV"
    "4zzNs09XyILcqyqks9hQ2WHHfCCLyMYuhLgxtjBL2UJFULqRw7wljApR9PDjhsjzlXRA/U"
    "ud5bDGns/s1gm7ENsCGY3rWykpzdzpluc0ETdfbUHwyzxfnlJqyYzw60vSisyCdWpWkVKt"
    "9rzg9VYEV/IwY8H7Is8KRQhuoLK5S+6NEa9KrluvyoJrr0oz+bjonXv9INzrve76Xnd9r7"
    "suZSktZON0muK1LOQpMOizldvKdyayBibyD7L91DEvEwmpvEEmsp4qm9hUBRD2ur9BdCvl"
    "XDyvvIDnlZM8jxKO0h7W/NnvdbNe1sxV4uwOGxz8B/w8bMfQXgCuBCNC4XxM9y5af8fhPj"
    "nvHcfJgRzgeNvPcJ7+B599Sok="
)
