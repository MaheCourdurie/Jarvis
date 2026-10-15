from __future__ import annotations
from pathlib import Path
from dotenv import load_dotenv
from services.google_client import GoogleClient, GoogleConfigError

ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ROOT_ENV)

def main() -> None:
    """Lance l'authentification Google et enregistre le token local."""
    client = GoogleClient.from_env()
    token_path = client.setup_oauth_token()
    print(f"[google-auth] Token enregistré: {token_path}")


if __name__ == "__main__":
    try:
        main()
    except GoogleConfigError as exc:
        print(f"[google-auth] Erreur de configuration: {exc}")
        raise SystemExit(1)
    except Exception as exc:
        print(f"[google-auth] Erreur: {exc}")
        raise SystemExit(1)