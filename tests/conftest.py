"""Blank out every external service before any backend module is imported.

backend.db / backend.storage read their settings at import time (after
load_dotenv, which never overrides a variable that is already set, even
to ""). Setting them to "" here means tests never touch the real
Supabase project, R2 bucket, Groq or AWS account configured in .env.
"""
import os

for _key in [
    "SUPABASE_URL", "SUPABASE_KEY",
    "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_BASE_URL",
    "GROQ_KEY",
    "REMOTION_AWS_ACCESS_KEY_ID", "REMOTION_AWS_SECRET_ACCESS_KEY", "REMOTION_AWS_REGION",
    "REMOTION_FUNCTION_NAME", "REMOTION_SERVE_URL",
]:
    os.environ[_key] = ""
