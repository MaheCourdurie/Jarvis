from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


class AlarmStore:
    def __init__(self, file_path: Path, timezone_name: str) -> None:
        """Initialise le stockage des alarmes avec persistance JSON locale."""
        self.file_path = file_path
        self.timezone_name = timezone_name or "Europe/Paris"
        self.timezone = ZoneInfo(self.timezone_name)
        self._lock = threading.Lock()
        self._ensure_file_exists()

    @classmethod
    def from_env(cls, timezone_name: str) -> "AlarmStore":
        """Construit le store d'alarmes depuis la configuration d'environnement."""
        raw = os.getenv(
            "ALARMS_FILE",
            str(Path(__file__).resolve().parent / ".alarms.json"),
        )
        return cls(Path(raw).expanduser(), timezone_name)

    def _ensure_file_exists(self) -> None:
        """Crée le fichier de stockage s'il n'existe pas encore."""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self.file_path.write_text("[]", encoding="utf-8")

    def _read_items(self) -> list[dict]:
        """Lit la liste brute des alarmes depuis le fichier JSON."""
        try:
            raw = self.file_path.read_text(encoding="utf-8").strip()
            if not raw:
                return []
            data = json.loads(raw)
            if isinstance(data, list):
                return data
            return []
        except Exception:
            return []

    def _write_items(self, items: list[dict]) -> None:
        """Écrit la liste des alarmes dans le fichier JSON."""
        self.file_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    def _normalize_datetime(self, value: datetime) -> datetime:
        """Normalise une date vers le fuseau du store."""
        if value.tzinfo is None:
            value = value.replace(tzinfo=self.timezone)
        return value.astimezone(self.timezone)

    def create_alarm(self, when: datetime, label: str) -> dict:
        """Crée et persiste une nouvelle alarme."""
        when_local = self._normalize_datetime(when)
        now = datetime.now(self.timezone)

        alarm = {
            "id": uuid.uuid4().hex[:8],
            "label": label.strip() or "Alarme Jarvis",
            "when": when_local.isoformat(),
            "created_at": now.isoformat(),
            "triggered": False,
            "triggered_at": None,
        }

        with self._lock:
            items = self._read_items()
            items.append(alarm)
            items.sort(key=lambda item: item.get("when", ""))
            self._write_items(items)

        return alarm

    def list_alarms(self, include_triggered: bool = False) -> list[dict]:
        """Retourne les alarmes actives, ou toutes si include_triggered est vrai."""
        with self._lock:
            items = self._read_items()

        if include_triggered:
            return sorted(items, key=lambda item: item.get("when", ""))
        return sorted(
            [item for item in items if not item.get("triggered", False)],
            key=lambda item: item.get("when", ""),
        )

    def delete_alarm(self, alarm_id: str) -> bool:
        """Supprime une alarme par id exact ou préfixe."""
        needle = alarm_id.strip().lower()
        if not needle:
            return False

        with self._lock:
            items = self._read_items()
            kept = []
            deleted = False

            for item in items:
                current = str(item.get("id", "")).lower()
                if current == needle or current.startswith(needle):
                    deleted = True
                    continue
                kept.append(item)

            if deleted:
                self._write_items(kept)

        return deleted

    def _parse_alarm_when(self, item: dict) -> datetime | None:
        """Convertit la date stockée d'une alarme en datetime timezone-aware."""
        when_raw = str(item.get("when") or "").strip()
        if not when_raw:
            return None

        try:
            when_dt = datetime.fromisoformat(when_raw)
        except ValueError:
            return None

        if when_dt.tzinfo is None:
            when_dt = when_dt.replace(tzinfo=self.timezone)
        return when_dt.astimezone(self.timezone)

    def delete_alarms_in_range(self, start: datetime, end: datetime, include_triggered: bool = False) -> int:
        """Supprime les alarmes comprises dans une période [start, end)."""
        start_local = self._normalize_datetime(start)
        end_local = self._normalize_datetime(end)
        if end_local <= start_local:
            return 0

        with self._lock:
            items = self._read_items()
            kept = []
            deleted_count = 0

            for item in items:
                if not include_triggered and item.get("triggered", False):
                    kept.append(item)
                    continue

                when_dt = self._parse_alarm_when(item)
                if when_dt is None:
                    kept.append(item)
                    continue

                if start_local <= when_dt < end_local:
                    deleted_count += 1
                    continue

                kept.append(item)

            if deleted_count:
                self._write_items(kept)

        return deleted_count

    def delete_all_alarms(self, include_triggered: bool = True) -> int:
        """Supprime toutes les alarmes, ou seulement les non déclenchées."""
        with self._lock:
            items = self._read_items()
            if include_triggered:
                deleted_count = len(items)
                if deleted_count:
                    self._write_items([])
                return deleted_count

            active_items = [item for item in items if not item.get("triggered", False)]
            if not active_items:
                return 0

            kept = [item for item in items if item.get("triggered", False)]
            self._write_items(kept)
            return len(active_items)

    def trigger_due_alarms(self) -> list[dict]:
        """Marque comme déclenchées les alarmes arrivées à échéance."""
        now = datetime.now(self.timezone)
        triggered = []

        with self._lock:
            items = self._read_items()
            changed = False

            for item in items:
                if item.get("triggered", False):
                    continue

                when_raw = item.get("when")
                if not when_raw:
                    continue

                try:
                    when_dt = datetime.fromisoformat(when_raw)
                except ValueError:
                    continue

                if when_dt.tzinfo is None:
                    when_dt = when_dt.replace(tzinfo=self.timezone)
                when_dt = when_dt.astimezone(self.timezone)

                if when_dt <= now:
                    item["triggered"] = True
                    item["triggered_at"] = now.isoformat()
                    triggered.append(item)
                    changed = True

            if changed:
                self._write_items(items)

        return triggered