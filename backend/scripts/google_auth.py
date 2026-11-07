"""One-time Google sign-in for the demo account. Run locally, from the backend/ folder:

    python scripts/google_auth.py

Needs client_secret.json (OAuth client of type "Desktop app") in this folder.
Writes token.json. For Render, paste its contents into the GOOGLE_TOKEN_JSON env var.
Never commit either file (.gitignore already excludes them).
"""

import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.calendar.google import SCOPES  # noqa: E402

HERE = Path(__file__).resolve().parent.parent
SECRET = HERE / "client_secret.json"
TOKEN = HERE / "token.json"

if not SECRET.exists():
    sys.exit(f"Missing {SECRET}. Download it from Google Cloud: Credentials -> OAuth client (Desktop app).")

flow = InstalledAppFlow.from_client_secrets_file(str(SECRET), SCOPES)
creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
if not creds.refresh_token:
    sys.exit("Google returned no refresh token. Remove the app's access in your Google account and run again.")
TOKEN.write_text(creds.to_json())
print(f"Saved {TOKEN}. Signed in. For Render, set GOOGLE_TOKEN_JSON to the contents of this file.")
