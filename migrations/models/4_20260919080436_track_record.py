from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "curator_pool_samples" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "pool_id" VARCHAR(180) NOT NULL,
    "fee24" DOUBLE PRECISION NOT NULL,
    "tvl" DOUBLE PRECISION NOT NULL,
    "at" TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS "idx_curator_poo_pool_id_20fb2f" ON "curator_pool_samples" ("pool_id", "at");
COMMENT ON TABLE "curator_pool_samples" IS 'Pool-level fee24 / TVL seen while a verdict pointed at (or sat in) that pool; the';
        ALTER TABLE "curator_verdicts" ADD "cost" DOUBLE PRECISION NOT NULL DEFAULT 0;
        ALTER TABLE "curator_verdicts" ADD "best_fee_day" DOUBLE PRECISION NOT NULL DEFAULT 0;
        ALTER TABLE "curator_verdicts" ADD "best_il_day" DOUBLE PRECISION NOT NULL DEFAULT 0;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "curator_verdicts" DROP COLUMN "cost";
        ALTER TABLE "curator_verdicts" DROP COLUMN "best_fee_day";
        ALTER TABLE "curator_verdicts" DROP COLUMN "best_il_day";
        DROP TABLE IF EXISTS "curator_pool_samples";"""


MODELS_STATE = (
    "eJztXW1T47oV/iuafClMly2EEGi305kA2d7cy5IdEnY7d7tjFFtJ3CiWrySTTW/575X8/q"
    "I4NuT9mg8QpHNk65F89JyjI+f32pQYCLP3LYwo73HIUe1v4PeaBafyg6L2HahB247qZAGH"
    "A+yK6w6FnFANSnmNhQoDxinUuRAZQsyQKDIQ06lpc5NYUvHrGHLAxwi4mgATYgMMGQcMzs"
    "CQUEAsBGzCTKnwwZNiYGhSJGqAPobWCLH38loG0cXFTGu02mYdy/zNQRonIyTao6Lxb99q"
    "DhOfRGXQgmYate/fRYFpGegHYlJK/mtPtKGJsJGAVsiKKrdc43PbLetY/KMrKDsy0HSCna"
    "kVCdtzPhZXCaRNi8vSEbKQgB3J5jl1JLqWg7E/JgHgXgciEe8WYzoGGkIHyzGS2t4NRGU1"
    "Tbvv9rVeu69ptcz4BRox7P0inVhy7MWtMrf3I3kLJ/WzxmXj6rzZuBIi7m2GJZcv3qUjYD"
    "xFF577fu3FrYccehIuxhGo8ZHIoHszhlQNb0othbPoQBrnANU8oIOCCOlo8m8C6in8oWFk"
    "jfhY/HtWP80B9kvr4ean1sORkDqWlyTiafWe6Hu/qu7VSfQjtMMHPInzz73uvRrnUCGFsG"
    "HqHPwPYJNlZvQeIJ0DrIRCtjxl7Dccx/PoU+tfaahv7rrXvjnhI+q24jZwnYLdsQ0JjgZ5"
    "FvtbUcPNKVLjn9RMD4Kv+j74sIdDUaMIGl0Lz327ljM0/c6ndq/f+vQ5MT63rX5b1tTd0n"
    "mq9KiZGrOwEfC10/8JyH/Br937dnoYQ7n+rzV5T9DhRLPITINGHKOgOLr72KiLxUZp1h4f"
    "O7cLhjtSSY2145jGe6m4h2OcM6buk3XuDVIcfrenLy9yLR5OlAtHsJQnof1IKDJH1i9o7g"
    "LcEfcBLV1lwXyi9Og3s5+QRqURLaBwFpKX+IQSfRc9RtxbWVu9m9Ztu+YiPID6ZAapoSWg"
    "ljWkTlIloWy2alqfpkugBUcuOLIX8p591H8mAxVrlcWF6Op/yIAV46k3lDB2MiN0gijACD"
    "IEGAEQ2IiaRKxiQDQFqGMxwR91JIuBQBPRZyhQtwiPim1KdMQUnHU9l1Dw16JE1f1bgkwF"
    "8qthUdulqwkO1ShCoRqLGVTDJ1CL6Ssm+kQsz47FTVx2bU/rHuDqvr+ruVuUXX+2Yy7vpY"
    "VQGUyvopDJtKRoQaPZE2OK0YlYPECv87Ut/WosHyr0AcgBdqbIAIO566czsdqemJb4LBx3"
    "W8CNxNADk2fN5KoafYthDOAqbBmJmjzsv2k8rxcwjef1haZRVuWbRvTDNsXQvcLpSWpuxi"
    "xuciQqq7gSq/iZENyDUxsrTWOstpB9tIW8xlyFglZSXuEEo2eEwRChegP8BfS/3AGGkAVm"
    "YxMjwQGfEXVDJTaRlM8Awp4dEQqY+Gtax76BE+18kHYvYzJXfoV/W7JPE0CRTqgh/tgYzl"
    "nUyp+YsL3/RUKUEmc0lirCXHMiLymu6MdmZXNCV5jvObCh8EuLmeVvNRdjzxsRz/b3KtK6"
    "2UhrCH7xKGuocogR1qtCEdarnAjrVSbC6j6nirgEJnDB/A01UhAPpcoegpyD6W338fquDT"
    "4/tG86vY4faA2XM7dSFokC0wtTPLRbdymA+bPC0cqB15evwC0CbnmuVgWmd4u0+SvWznI2"
    "ioaIItcVVZG2WHUx1pZSWEbaFg//G9zK3Qn0b5XAvD7Mn0tbKBmauJTXHlPZHG0RDwiWWw"
    "3B7ayZvBTaHc7ZHM7uDetjcakSvDuUX069V4Vxo9k832n2HdtpJw4tF2uKNDY4aSd0zjjE"
    "+zpnpbNaig0GCpukg2en4mc/+eBMhmgVnHDxLI40NjiLNzN9G0VCpo3FIdNGPT19OcJoRO"
    "FUE7aUl/TNVboHB/mqotQxD8fNGMwCfU0IRtBa4OSESimEB0JrXRAH1G2zVuO6271LuDHX"
    "nX4K3cdP1+2Ho7PjpPXwlsA3uRnLkju6FuoT8WvNqR27QKJXnNjxJp/tQWB3Z05NXlN4bF"
    "HluyL+mhwHDUv5LfprEzQvY2l98YPbAiwU/syJfl4tzY6YiW6SmcLYmqOFbkWkszm/Yv1R"
    "/b/W6+fnl/XT8+bVRePy8uLqNHQwslV5nsZ155/S0iaGJOt96MSxFLRtsS8XyG8O87P1Av"
    "4mR25HgmU9xJjX+4zZDaoKGV3mCW/R4nIyQZY2hmxciuImtA7O/jYbBexvs7HQ/sqqKgXj"
    "j5mCUeWZV3nm++uObGwFdVFXLJ/BaCxfO2XHCuYDCc8UkCF4QlNo4ifwZ/BkQ8ZmRHRCrm"
    "FP4AgTHWIAdZduHQNCwZN4zsVUZKJSJkUeA5MBhhTZk6tu/A2LeTlTs41Nrtrfh46ly3EB"
    "7pXkr8Y/1hWyWs++lzvQZdhSqPAqouRjuIs8qX5RhCgJqcUbBxeNdBww8fSU2lxMK64E7m"
    "17qSnALwoBfpED+EUm8OrZojJQx1QObU6vfi9Bp+iVZ0yTmlUqz66Q/xWk8qT2PbwXPKh2"
    "P3ztj788IAy5H1lQM9nkqyX2bCos4rPJXeVYvOT1OMVCNIcIkp8x/kaQvnitHCpIM8j1cf"
    "CShNej9FU2c0gYlfL54rlgiWw/NaDBLuFyWFPZhvtF2XKxLeEiB0+gwkuOPZzLHeW4PVju"
    "Kz8Q7g5OeHwFCtd0TGaWPGwCgfS63QMrIHFeRSdTG4rFE5gczEw+9o6kDAnGZIaMrNO8tq"
    "sUOeyietfQu+rgi4KeVa8Y2o4TspZXDNnQVMRL8/xpT/4A8W0Wgbe5GN1mBtyJ6FcZcAP5"
    "AwT3rNDczZm6GXAHiHH3GGgZhBNKB5d/t/oZHOJV0hqn9Q4O6rWcRnRsbA65ZkBFwlNOln"
    "RSbZO50nuaJ23DuXReJGIKzyQH6bTiK7HeTd9kXWi7tmCIUOl5nVasZnYxrE38OqgjvQrp"
    "pUjrRBUmyoE4UKiwXYrtM8ROuYNCoUZ1cLzQ5HUoRRbXLFSebSh0K9CLgC5WMqZx4p/fK4"
    "x3Uq2CutCLEUaoPLmLK1UwV++f+CNvWlcJq1XCapWwWlu2G+ft9Cr24sIt4OU7cYlN59We"
    "94jvanmhuOrbM6p3uu3SrsA6oqhVal3FUiqWUrGUiqUEKaCImmqa4tfk8hQYyWzlMGrFRN"
    "bARJ4RDbJdizKRmMoBMpH1HKIQD1UJhH3xA0T37LRY+kde/keW5xGLI9V7ExZ/P1pMpfqG"
    "tJLfkLbVtyy8/B/J2BDn"
)
