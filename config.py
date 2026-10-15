import os

from dotenv import load_dotenv

load_dotenv()

# OpenAI
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"].strip()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# AWS (on EC2, credentials come from the instance IAM role)
AWS_REGION = os.getenv("AWS_REGION", "eu-central-1")
VECTOR_BUCKET = os.environ["VECTOR_BUCKET"].strip()
VECTOR_INDEX = os.getenv("VECTOR_INDEX", "documents")
S3_BUCKET = os.environ["S3_BUCKET"].strip()
S3_HISTORY_PREFIX = os.getenv("S3_HISTORY_PREFIX", "chat-history/")
S3_DOCS_PREFIX = os.getenv("S3_DOCS_PREFIX", "").strip()

# App / RAG settings
APP_PASSWORD = os.getenv("APP_PASSWORD", "")  # leave empty to disable the login

TOP_K = int(os.getenv("TOP_K", "5"))
MAX_DISTANCE = float(os.getenv("MAX_DISTANCE", "0.9"))  # cosine distance cut-off (0 = identical)
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "4"))
