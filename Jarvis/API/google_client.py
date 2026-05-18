from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


class GoogleConfigError(Exception):
    pass


class GoogleApiError(Exception):
    pass


class GoogleClient:
    SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events",
    ]

    def __init__(
        self,
        client_secret_file: str,
        token_file: str,
        timezone_name: str,
        calendar_id: str,
    ) -> None:
        """Initialise le client Google (Gmail + Calendar) avec les chemins de config."""
        self.client_secret_file = client_secret_file
        self.token_file = token_file
        self.timezone_name = timezone_name or "Europe/Paris"
        self.timezone = ZoneInfo(self.timezone_name)
        self.calendar_id = calendar_id or "primary"

    @classmethod
    def from_env(cls) -> "GoogleClient":
        """Construit le client à partir des variables d'environnement."""
        default_token = str(Path(__file__).resolve().parent / ".google-token.json")
        timezone_name = os.getenv("GOOGLE_TIMEZONE", "Europe/Paris")
        return cls(
            client_secret_file=os.getenv("GOOGLE_CLIENT_SECRET_FILE", "").strip(),
            token_file=os.getenv("GOOGLE_TOKEN_FILE", default_token).strip(),
            timezone_name=timezone_name.strip(),
            calendar_id=os.getenv("GOOGLE_CALENDAR_ID", "primary").strip(),
        )

    @property
    def client_secret_path(self) -> Path:
        """Retourne le chemin absolu du fichier client secret Google."""
        return Path(self.client_secret_file).expanduser()

    @property
    def token_path(self) -> Path:
        """Retourne le chemin absolu du fichier token OAuth local."""
        return Path(self.token_file).expanduser()

    def missing_keys(self) -> list[str]:
        """Liste les clés/fichiers manquants nécessaires au fonctionnement Google."""
        missing = []

        if not self.client_secret_file:
            missing.append("GOOGLE_CLIENT_SECRET_FILE")
        elif not self.client_secret_path.exists():
            missing.append("GOOGLE_CLIENT_SECRET_FILE (file not found)")

        if not self.token_path.exists():
            missing.append("GOOGLE_TOKEN_FILE (connecte Google depuis l'interface)")

        return missing

    def is_configured(self) -> bool:
        """Indique si la configuration Google est complète et utilisable."""
        return len(self.missing_keys()) == 0

    def status(self) -> dict:
        """Retourne un état de santé synthétique du provider Google."""
        token_exists = self.token_path.exists()
        return {
            "provider": "google",
            "provider_label": "Google",
            "configured": self.is_configured(),
            "missing_keys": self.missing_keys(),
            "timezone": self.timezone_name,
            "mode": "delegated",
            "token_file": str(self.token_path),
            "token_present": token_exists,
        }

    def disconnect(self, revoke: bool = True) -> dict:
        """Révoque les tokens Google puis supprime le token local."""
        result = {
            "token_path": str(self.token_path),
            "token_deleted": False,
            "revoked": False,
            "revoke_errors": [],
        }

        token_payload: dict = {}
        if self.token_path.exists():
            try:
                token_payload = json.loads(self.token_path.read_text(encoding="utf-8"))
            except Exception:
                token_payload = {}

        if revoke and token_payload:
            revoke_candidates = []
            for key in ("refresh_token", "token"):
                value = str(token_payload.get(key) or "").strip()
                if value and value not in revoke_candidates:
                    revoke_candidates.append(value)

            for token in revoke_candidates:
                try:
                    response = requests.post(
                        "https://oauth2.googleapis.com/revoke",
                        data={"token": token},
                        timeout=10,
                    )
                    if response.status_code in (200, 400):
                        result["revoked"] = True
                    else:
                        result["revoke_errors"].append(
                            f"HTTP {response.status_code}: {response.text.strip()}"
                        )
                except Exception as exc:
                    result["revoke_errors"].append(str(exc))

        if self.token_path.exists():
            try:
                self.token_path.unlink()
                result["token_deleted"] = True
            except Exception as exc:
                raise GoogleApiError(f"Impossible de supprimer le token local: {exc}") from exc

        return result

    def _save_credentials(self, creds) -> None:
        """Sauvegarde les credentials OAuth dans le fichier token."""
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(creds.to_json(), encoding="utf-8")

    def setup_oauth_token(self) -> str:
        """Lance le consentement OAuth et crée le token Google local."""
        if not self.client_secret_file:
            raise GoogleConfigError("GOOGLE_CLIENT_SECRET_FILE manquant")
        if not self.client_secret_path.exists():
            raise GoogleConfigError(f"Fichier client secret introuvable: {self.client_secret_path}")

        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise GoogleConfigError("Dépendances Google manquantes dans requirements.txt") from exc

        flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secret_path), self.SCOPES)
        creds = flow.run_local_server(port=0)
        self._save_credentials(creds)
        return str(self.token_path)

    def _load_credentials(self):
        """Charge, valide et rafraîchit si besoin les credentials OAuth."""
        if not self.client_secret_file:
            raise GoogleConfigError("GOOGLE_CLIENT_SECRET_FILE manquant")
        if not self.client_secret_path.exists():
            raise GoogleConfigError(f"Fichier client secret introuvable: {self.client_secret_path}")
        if not self.token_path.exists():
            raise GoogleConfigError(
                f"Token Google manquant: {self.token_path}. "
                "Connecte-toi via la commande Discord /google ou depuis l'interface web."
            )

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
        except ImportError as exc:
            raise GoogleConfigError("Dépendances Google manquantes dans requirements.txt") from exc

        try:
            creds = Credentials.from_authorized_user_file(str(self.token_path), self.SCOPES)
        except Exception as exc:
            raise GoogleConfigError(f"Token Google invalide ({self.token_path}): {exc}") from exc

        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save_credentials(creds)
            except Exception as exc:
                raise GoogleApiError(f"Impossible de refresh le token Google: {exc}") from exc

        if not creds.valid:
            raise GoogleConfigError(
                f"Token Google invalide ({self.token_path}). "
                "Reconnecte-toi via la commande Discord /google ou depuis l'interface web."
            )

        return creds

    def _gmail_service(self):
        """Construit le client de service Gmail authentifié."""
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise GoogleConfigError("Dépendances Google manquantes dans requirements.txt") from exc

        creds = self._load_credentials()
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def _calendar_service(self):
        """Construit le client de service Google Calendar authentifié."""
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise GoogleConfigError("Dépendances Google manquantes dans requirements.txt") from exc

        creds = self._load_credentials()
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    def _parse_sender_name(self, value: str) -> str:
        """Extrait un nom lisible à partir de l'en-tête From d'un email."""
        if not value:
            return "Expéditeur inconnu"
        m = re.match(r"\s*\"?([^\"<]+)\"?\s*<[^>]+>", value)
        if m:
            return m.group(1).strip()
        return value.strip()

    def _gmail_message_to_common(self, message: dict) -> dict:
        """Convertit un message Gmail en format commun utilisé par l'API."""
        payload = message.get("payload", {})
        headers = payload.get("headers", [])
        header_map = {h.get("name", "").lower(): h.get("value", "") for h in headers}

        sender_name = self._parse_sender_name(header_map.get("from", ""))
        subject = header_map.get("subject") or "(sans objet)"
        preview = (message.get("snippet") or "").strip()
        received = header_map.get("date", "")

        return {
            "from": {"emailAddress": {"name": sender_name}},
            "subject": subject,
            "receivedDateTime": received,
            "bodyPreview": preview,
        }

    def get_unread_emails(self, limit: int = 5) -> list[dict]:
        """Retourne les derniers emails non lus de la boîte de réception."""
        service = self._gmail_service()
        try:
            listing = service.users().messages().list(
                userId="me",
                labelIds=["INBOX", "UNREAD"],
                maxResults=limit,
            ).execute()
        except Exception as exc:
            raise GoogleApiError(str(exc)) from exc

        items = []
        for item in listing.get("messages", []) or []:
            try:
                msg = service.users().messages().get(
                    userId="me",
                    id=item["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                ).execute()
                items.append(self._gmail_message_to_common(msg))
            except Exception as exc:
                raise GoogleApiError(str(exc)) from exc

        return items

    def get_latest_email(self) -> dict | None:
        """Retourne le dernier email de la boîte de réception."""
        service = self._gmail_service()
        try:
            listing = service.users().messages().list(
                userId="me",
                labelIds=["INBOX"],
                maxResults=1,
            ).execute()
        except Exception as exc:
            raise GoogleApiError(str(exc)) from exc

        messages = listing.get("messages", []) or []
        if not messages:
            return None

        try:
            msg = service.users().messages().get(
                userId="me",
                id=messages[0]["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
        except Exception as exc:
            raise GoogleApiError(str(exc)) from exc

        return self._gmail_message_to_common(msg)

    def send_mail(self, to_email: str, subject: str, body: str) -> None:
        """Envoie un email via Gmail API."""
        service = self._gmail_service()

        message = MIMEText(body or "")
        message["to"] = to_email
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        try:
            service.users().messages().send(userId="me", body={"raw": raw}).execute()
        except Exception as exc:
            raise GoogleApiError(str(exc)) from exc

    def _to_rfc3339(self, value: datetime) -> str:
        """Convertit une date en chaîne RFC3339 UTC pour l'API Google."""
        if value.tzinfo is None:
            value = value.replace(tzinfo=self.timezone)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _parse_google_datetime(self, value: str) -> datetime:
        """Convertit une date Google (date/dateTime) en datetime timezone-aware."""
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            dt = datetime.fromisoformat(value)
            return dt.replace(tzinfo=self.timezone)

        raw = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self.timezone)
        return dt.astimezone(self.timezone)

    def list_week_events(self) -> list[dict]:
        """Retourne les événements de la semaine courante."""
        now = datetime.now(self.timezone)
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)

        return self.list_events_in_range(start, end)

    def list_events_in_range(self, start: datetime, end: datetime) -> list[dict]:
        """Liste les événements Calendar dans une période donnée."""
        service = self._calendar_service()

        if start.tzinfo is None:
            start = start.replace(tzinfo=self.timezone)
        else:
            start = start.astimezone(self.timezone)

        if end.tzinfo is None:
            end = end.replace(tzinfo=self.timezone)
        else:
            end = end.astimezone(self.timezone)

        if end <= start:
            raise GoogleConfigError("La période de suppression est invalide (fin <= début).")

        events = []
        page_token = None

        while True:
            try:
                data = service.events().list(
                    calendarId=self.calendar_id,
                    timeMin=self._to_rfc3339(start),
                    timeMax=self._to_rfc3339(end),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=2500,
                    pageToken=page_token,
                ).execute()
            except Exception as exc:
                raise GoogleApiError(str(exc)) from exc

            for item in data.get("items", []) or []:
                start_obj = item.get("start", {})
                end_obj = item.get("end", {})
                start_raw = start_obj.get("dateTime") or start_obj.get("date")
                end_raw = end_obj.get("dateTime") or end_obj.get("date")
                if not start_raw or not end_raw:
                    continue

                events.append(
                    {
                        "id": item.get("id") or "",
                        "subject": item.get("summary") or "(sans titre)",
                        "location": item.get("location") or "",
                        "isAllDay": "date" in start_obj,
                        "start": self._parse_google_datetime(start_raw),
                        "end": self._parse_google_datetime(end_raw),
                        "webLink": item.get("htmlLink") or "",
                    }
                )

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return events

    def delete_events_in_range(self, start: datetime, end: datetime) -> list[dict]:
        """Supprime tous les événements trouvés dans une période donnée."""
        service = self._calendar_service()
        events = self.list_events_in_range(start, end)

        deleted: list[dict] = []
        for event in events:
            event_id = str(event.get("id") or "").strip()
            if not event_id:
                continue
            try:
                service.events().delete(calendarId=self.calendar_id, eventId=event_id).execute()
                deleted.append(event)
            except Exception as exc:
                message = str(exc)
                if "404" in message or "Not Found" in message:
                    continue
                raise GoogleApiError(message) from exc

        return deleted

    def create_event(self, subject: str, start: datetime, end: datetime) -> dict:
        """Crée un événement Google Calendar avec sujet et créneau."""
        service = self._calendar_service()

        if start.tzinfo is None:
            start = start.replace(tzinfo=self.timezone)
        if end.tzinfo is None:
            end = end.replace(tzinfo=self.timezone)

        payload = {
            "summary": subject,
            "start": {
                "dateTime": start.astimezone(self.timezone).isoformat(),
                "timeZone": self.timezone_name,
            },
            "end": {
                "dateTime": end.astimezone(self.timezone).isoformat(),
                "timeZone": self.timezone_name,
            },
        }

        try:
            created = service.events().insert(calendarId=self.calendar_id, body=payload).execute()
        except Exception as exc:
            raise GoogleApiError(str(exc)) from exc

        return {
            "webLink": created.get("htmlLink"),
            **created,
        }

    def delete_event(self, event_id: str) -> bool:
        """Supprime un événement Calendar par son identifiant."""
        service = self._calendar_service()
        event_id = (event_id or "").strip()
        if not event_id:
            raise GoogleConfigError("event_id manquant")

        try:
            service.events().delete(calendarId=self.calendar_id, eventId=event_id).execute()
            return True
        except Exception as exc:
            message = str(exc)
            if "404" in message or "Not Found" in message:
                return False
            raise GoogleApiError(message) from exc