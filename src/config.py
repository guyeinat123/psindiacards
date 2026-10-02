import os
from dotenv import load_dotenv

load_dotenv()


def _int_list(raw: str) -> list[int]:
    return [int(x) for x in raw.split(",") if x.strip()]


def _asin_map(raw: str) -> dict[int, str]:
    """'1000:B0AAA,2000:B0BBB' -> {1000: 'B0AAA', 2000: 'B0BBB'}"""
    out = {}
    for part in raw.split(","):
        if ":" in part:
            face, asin = part.split(":", 1)
            out[int(face.strip())] = asin.strip()
    return out


class Config:
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    MAX_MARKUP_PCT: float = float(os.getenv("MAX_MARKUP_PCT", "15"))
    MIN_IMPROVEMENT_PCT: float = float(os.getenv("MIN_IMPROVEMENT_PCT", "1"))
    FOREIGN_FEE_PCT: float = float(os.getenv("FOREIGN_FEE_PCT", "2.5"))
    SEAGM_FEE_PCT: float = float(os.getenv("SEAGM_FEE_PCT", "3"))
    ENEBA_FEE_PCT: float = float(os.getenv("ENEBA_FEE_PCT", "11"))
    BROKEN_AFTER_FAILURES: int = int(os.getenv("BROKEN_AFTER_FAILURES", "3"))

    DENOMINATIONS: list[int] = _int_list(
        os.getenv("DENOMINATIONS", "500,1000,1500,2000,2500,3000,4000,5000,7000,8000")
    )

    KEEPA_API_KEY: str = os.getenv("KEEPA_API_KEY", "")
    AMAZON_ASINS: dict[int, str] = _asin_map(os.getenv("AMAZON_ASINS", ""))

    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "./data/scout.db")
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Jerusalem")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


config = Config()
