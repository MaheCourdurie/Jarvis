from datetime import datetime, timedelta

import pytest

import intents


def action(text, **kwargs):
    result = intents.detect_action(text, **kwargs)
    return result["action"] if result else None


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Quelle heure est-il ?", "time"),
        ("Jarvis, il est quelle heure ?", "time"),
        ("On est quel jour ?", "date"),
        ("Quel temps fait-il à Lyon ?", "weather"),
        ("Va-t-il pleuvoir demain ?", "weather"),
        ("Fais-moi le point", "briefing"),
        ("Lance un diagnostic système", "system_status"),
        ("Niveau de batterie ?", "system_status"),
        ("Ouvre Safari", "open_app"),
        ("Ouvre github.com", "open_url"),
        ("Ferme Safari", "quit_app"),
        ("Monte le volume", "volume"),
        ("Coupe le son", "volume"),
        ("Cherche les dernières news sur l'IA", "web_answer"),
        ("Quels sont les horaires du Leclerc de Blagnac ?", "web_answer"),
        ("Il y a une pharmacie de garde ce soir ?", "web_answer"),
        ("Qui a gagné le match du Stade Toulousain ?", "web_answer"),
        ("Combien coûte un iPhone ?", "web_answer"),
        ("Ouvre une recherche sur les réacteurs à arc", "web_search"),
        ("Mets l'écran en veille", "sleep_display"),
        ("Minuteur de 10 minutes", "set_alarm"),
        ("Rappelle-moi dans 20 minutes de sortir le gâteau", "set_alarm"),
        ("Réveille-moi demain à 7h30", "set_alarm"),
        ("Quelles sont mes alarmes ?", "list_alarms"),
        ("Annule le minuteur", "delete_timers"),
        ("Supprime toutes mes alarmes", "delete_alarms_all"),
        ("Planifie une réunion avec Sophie demain à 10h", "add_event"),
        ("Supprime les événements de vendredi", "delete_events_range"),
        ("Qu'est-ce que j'ai de prévu demain ?", "events_range"),
        ("Suis-je libre cette semaine ?", "availability_week"),
        ("Résume mes mails", "mail_resume"),
        ("Lis mon dernier mail", "mail_last"),
        ("Envoie un mail à client@exemple.com pour lui dire que le devis est prêt", "send_mail"),
        ("Jarvis, tu es là ?", "smalltalk"),
        ("/status", "system_status"),
        ("/weather Lyon", "weather"),
        ("/open Safari", "open_app"),
        ("/volume 40", "volume"),
    ],
)
def test_router_recognises_actions(text, expected):
    assert action(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Bonjour Jarvis",
        "Raconte-moi une blague",
        "Explique-moi ce qu'est un trou noir",
        "Rédige un message d'anniversaire pour ma mère",
        "Décris-moi ce message",
        "J'ai le temps de faire une sieste ?",
        "Supprime mon dernier mail",
        "Aide-moi à comprendre les fractions",
    ],
)
def test_router_leaves_conversation_to_the_model(text):
    assert action(text) is None


def test_weather_params():
    params = intents.detect_action("Quel temps fait-il à Lyon demain ?")["params"]
    assert params == {"city": "Lyon", "day": "tomorrow"}
    assert intents.detect_action("météo")["params"]["city"] is None
    assert intents.detect_action("Quel temps fait-il à New York ?")["params"]["city"] == "New York"


def test_volume_params():
    assert intents.detect_action("Volume à 40")["params"] == {"mode": "set", "level": 40}
    assert intents.detect_action("Mets le son à fond")["params"] == {"mode": "set", "level": 100}
    assert intents.detect_action("Baisse un peu le volume")["params"] == {"mode": "down"}
    assert intents.detect_action("Remets le son")["params"] == {"mode": "unmute"}


def test_web_questions():
    # Une recherche explicite : Jarvis cherche lui-même, avec la requête dictée.
    assert intents.detect_action("Cherche le prix d'un abonnement Netflix sur internet") == {
        "action": "web_answer",
        "params": {"query": "le prix d'un abonnement Netflix"},
    }
    # Une question d'information : la requête sera formulée par le modèle.
    assert intents.detect_action("À quelle heure ferme la Fnac de Toulouse ?")["params"] == {"query": None}
    # « sur YouTube » : c'est pour regarder, on ouvre le navigateur.
    assert intents.detect_action("Recherche Iron Man sur YouTube") == {
        "action": "web_search",
        "params": {"query": "Iron Man", "engine": "youtube"},
    }
    # Ses propres données ne se cherchent pas sur le web.
    assert action("Cherche dans mes mails le devis") is None
    assert action("Quels sont mes horaires demain ?") is None
    # Les modules existants gardent la priorité.
    assert action("Quelle heure est-il ?") == "time"
    assert action("Trouve-moi un créneau libre demain") == "availability_week"


def test_timer_and_reminder():
    now = datetime.now()
    timer = intents.detect_action("Lance un minuteur de 3 minutes pour les pâtes")["params"]
    assert timer["kind"] == "timer" and timer["title"] == "Minuteur : les pâtes"
    assert timedelta(minutes=2, seconds=50) < datetime.fromisoformat(timer["when"]) - now < timedelta(minutes=3, seconds=10)

    reminder = intents.detect_action("Rappelle-moi d'appeler Paul à 15h")["params"]
    assert reminder["kind"] == "reminder" and reminder["title"] == "Appeler Paul"
    assert datetime.fromisoformat(reminder["when"]).hour == 15

    assert action("Rappelle-moi de sortir le gâteau") == "command_error"
    assert action("Minuteur") == "command_error"


def test_alarm_title_is_never_a_time():
    params = intents.detect_action("Mets une alarme pour 7h30")["params"]
    assert params["title"] == "Alarme"
    assert datetime.fromisoformat(params["when"]).strftime("%H:%M") == "07:30"
    assert intents.detect_action("Réveille-moi demain à 7h")["params"]["title"] == "Réveil"


def test_alarm_date_is_not_mistaken_for_an_id():
    result = intents.detect_action("Supprime les alarmes du 2026-10-02")
    assert result["action"] == "delete_alarms_range"
    assert result["params"]["start"].startswith("2026-10-02")
    assert intents.detect_action("Supprime l'alarme ab12cd34")["params"] == {"alarm_id": "ab12cd34"}


@pytest.mark.parametrize(
    "text, hour, minute",
    [
        ("à 7 heures et demie", 7, 30),
        ("à 9 heures moins le quart", 8, 45),
        ("à 20 heures", 20, 0),
        ("demain à midi", 12, 0),
        ("ce soir à 8h", 20, 0),
        ("demain matin", 9, 0),
        ("à 15h30", 15, 30),
    ],
)
def test_spoken_times(text, hour, minute):
    parsed = intents._parse_datetime_expression(text)
    assert (parsed.hour, parsed.minute) == (hour, minute)


def test_relative_delays():
    assert intents._extract_relative_delay("une demi-heure") == timedelta(minutes=30)
    assert intents._extract_relative_delay("un quart d'heure") == timedelta(minutes=15)
    assert intents._extract_relative_delay("1h30") == timedelta(hours=1, minutes=30)
    assert intents._extract_relative_delay("deux minutes") == timedelta(minutes=2)
    assert intents._extract_relative_delay("45 secondes") == timedelta(seconds=45)
    assert intents._extract_relative_delay("bientôt") is None


def test_event_range_and_titles():
    params = intents.detect_action("Crée un événement lundi de 14h à 16h pour réunion client")["params"]
    start, end = datetime.fromisoformat(params["start"]), datetime.fromisoformat(params["end"])
    assert params["title"] == "Réunion client"
    assert (start.weekday(), start.hour, end.hour) == (0, 14, 16)

    assert intents.detect_action("Ajoute un déjeuner avec Paul demain à midi")["params"]["title"] == "Déjeuner avec Paul"
    duration = intents.detect_action("Planifie une réunion vendredi à 15h pendant 2 heures")["params"]
    assert datetime.fromisoformat(duration["end"]) - datetime.fromisoformat(duration["start"]) == timedelta(hours=2)


def test_natural_bulk_deletions_ask_for_confirmation():
    assert intents.detect_action("Supprime les événements de vendredi")["params"]["confirm"] is True
    assert intents.detect_action("Supprime toutes mes alarmes")["params"] == {"confirm": True}
    # Une commande slash est explicite : pas de confirmation.
    assert "confirm" not in intents.detect_action('/deleteeventsrange "2026-10-02"')["params"]
    assert "params" not in intents.detect_action("/deletealarmsall")


def test_mail_by_contact_name_and_dictated_address():
    params = intents.detect_action("Envoie un mail à Paul pour lui dire que je serai en retard")["params"]
    assert (params["to_email"], params["to_name"], params["confirm"]) == ("paul@exemple.com", "Paul", True)
    assert params["body"] == "je serai en retard"

    # Le nom le plus long l'emporte.
    params = intents.detect_action("Écris à Sophie Martin pour lui dire que c'est d'accord")["params"]
    assert params["to_email"] == "sophie@exemple.com"

    dictated = intents.detect_action("Envoie un mail à marc arobase exemple point com pour lui dire bonjour")["params"]
    assert dictated["to_email"] == "marc@exemple.com"

    unknown = intents.detect_action("Envoie un mail à Inconnu")
    assert unknown["action"] == "command_error" and "adresse" in unknown["message"]

    slash = intents.detect_action('/sendmail "a@b.fr" "Objet" "Message"')["params"]
    assert "confirm" not in slash


def test_mail_followup_reuses_previous_recipient():
    result = intents.detect_action("message Bonjour, je confirme le rendez-vous", fallback_email="client@exemple.com")
    assert result["action"] == "send_mail" and result["params"]["to_email"] == "client@exemple.com"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Oui", "yes"),
        ("oui envoie-le", "yes"),
        ("Vas-y Jarvis", "yes"),
        ("D'accord", "yes"),
        ("Non merci", "no"),
        ("Annule", "no"),
        ("Laisse tomber", "no"),
        ("Quelle heure est-il ?", None),
        ("euh", None),
    ],
)
def test_confirmation(text, expected):
    assert intents.classify_confirmation(text) == expected
