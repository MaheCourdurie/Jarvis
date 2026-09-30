from datetime import datetime, timedelta

import persona


NOW = datetime(2026, 9, 30, 12, 4)


def test_time_formats():
    assert persona.format_time(NOW) == "12 h 04"
    assert persona.format_time(NOW.replace(hour=10, minute=0)) == "10 h"
    assert persona.spoken_time(NOW) == "12 heures 4"
    assert persona.spoken_time(NOW.replace(minute=0)) == "midi"
    assert persona.spoken_time(NOW.replace(hour=0, minute=0)) == "minuit"
    assert persona.spoken_time(NOW.replace(hour=1, minute=0)) == "1 heure"
    assert persona.spoken_time(NOW.replace(hour=7, minute=30)) == "7 heures 30"


def test_day_labels_are_french():
    assert persona.format_date(NOW) == "mercredi 30 septembre"
    assert persona.format_date(NOW + timedelta(days=1)) == "jeudi 1er octobre"
    assert persona.day_label(NOW, NOW) == "aujourd'hui"
    assert persona.day_label(NOW + timedelta(days=1), NOW) == "demain"
    assert persona.day_label(NOW + timedelta(days=6), NOW) == "mardi 6 octobre"
    assert persona.spoken_when(NOW + timedelta(days=1, hours=-5, minutes=26), NOW) == "demain à 7 heures 30"


def test_period_label():
    start = NOW.replace(hour=0, minute=0)
    assert persona.period_label(start, start + timedelta(days=1), NOW) == "aujourd'hui"
    assert persona.period_label(start + timedelta(days=2), start + timedelta(days=3), NOW) == "le vendredi 2 octobre"
    assert persona.period_label(start + timedelta(days=2), start + timedelta(days=5), NOW) == (
        "entre le vendredi 2 octobre et le dimanche 4 octobre"
    )


def test_to_speech_removes_what_cannot_be_spoken():
    text = "Vos événements :\n- **Réunion** [id: abc123]\n- Voir https://exemple.com/x\n/deleteevent \"id\""
    spoken = persona.to_speech(text)
    assert "abc123" not in spoken and "http" not in spoken and "*" not in spoken and "/deleteevent" not in spoken
    assert "Réunion" in spoken


def test_strip_vocative():
    assert persona.strip_vocative("Jarvis, ouvre Safari") == "ouvre Safari"
    assert persona.strip_vocative("Dis Jarvis, quelle heure est-il ?") == "quelle heure est-il ?"
    assert persona.strip_vocative("Quelle heure est-il, Jarvis ?") == "Quelle heure est-il"
    assert persona.strip_vocative("Jarvis") == ""


def test_smalltalk_easter_eggs():
    assert persona.smalltalk_reply("Jarvis, tu es là ?").text == "Pour vous, Monsieur, toujours."
    assert persona.smalltalk_reply("Réveille-toi, papa est rentré").text == "Bienvenue à la maison, Monsieur."
    assert persona.smalltalk_reply("Jarvis ?").data == {"attentive": True}
    assert persona.smalltalk_reply("Merci beaucoup").data == {"standby": True}
    # Une vraie question ne doit jamais être prise pour une petite phrase.
    assert persona.smalltalk_reply("Je suis la personne que tu cherches ?") is None
    assert persona.smalltalk_reply("Merci de m'expliquer la relativité") is None


def test_reply_spoken_falls_back_to_cleaned_text():
    assert persona.Reply(text="- Point [id: x]").spoken == "Point."
    assert persona.Reply(text="Affiché", speech="Prononcé").spoken == "Prononcé"
