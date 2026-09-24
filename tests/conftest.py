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

import pytest


@pytest.fixture(autouse=True)
def logged_in_member(request):
    """Most API tests act as a logged-in admin of TEST_TEAM_ID. Tests marked
    `real_auth` exercise the real login dependency instead."""
    if request.node.get_closest_marker("real_auth"):
        yield None
        return
    from backend import accounts, main
    from tests.support import TEST_TEAM_ID

    member = accounts.Member(
        user_id="00000000-0000-0000-0000-00000000test", email="tester@example.com",
        team_id=TEST_TEAM_ID, team_name="Test team", role="admin",
    )
    main.app.dependency_overrides[accounts.current_member] = lambda: member
    yield member
    main.app.dependency_overrides.pop(accounts.current_member, None)
