
import os
from dotenv import load_dotenv

load_dotenv()

# --- LLM configuration ---
MODEL = os.getenv("MODEL", "openai/gpt-oss-120b")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = os.getenv(
    "GROQ_BASE_URL",
    "https://api.groq.com/openai/v1",
)

# --- Authentication ---
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()

if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET must be configured in the environment or .env file"
    )

JWT_TTL_MIN = int(os.getenv("JWT_TTL_MIN", "30"))

# --- Rate limiting ---
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "30"))
LOGIN_RATE_LIMIT_PER_MIN = 5

# --- Agent limits ---
MAX_AGENT_STEPS = 6
MAX_HISTORY_MESSAGES = 20

# --- Optional self-hosted LLM (OpenAI-compatible API) ---
SELF_HOSTED_URL = os.getenv("SELF_HOSTED_URL", "")
SELF_HOSTED_MODEL = os.getenv("SELF_HOSTED_MODEL", "llama3.1")
SELF_HOSTED_API_KEY = os.getenv("SELF_HOSTED_API_KEY", "")

# --- Cost tracking: USD per 1 million tokens ---
# Placeholder prices; configure according to your provider/contract.
THIRD_PARTY_PRICE_IN = float(
    os.getenv("THIRD_PARTY_PRICE_IN_PER_M", "3.0")
)
THIRD_PARTY_PRICE_OUT = float(
    os.getenv("THIRD_PARTY_PRICE_OUT_PER_M", "15.0")
)
SELF_HOSTED_PRICE_IN = float(
    os.getenv("SELF_HOSTED_PRICE_IN_PER_M", "0.0")
)
SELF_HOSTED_PRICE_OUT = float(
    os.getenv("SELF_HOSTED_PRICE_OUT_PER_M", "0.0")
)

# --- Session store ---
SESSION_DB = os.getenv(
    "SESSION_DB",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "sessions.db",
    ),
)
