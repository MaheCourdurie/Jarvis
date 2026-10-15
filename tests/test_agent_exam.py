"""L'examen des agents : des phrases de tous les jours, et l'action que chacun doit en tirer.

C'est leur « entraînement » : chaque tournure qu'un agent comprend mal est ajoutée ici,
puis apprise dans core/intents.py. L'examen garantit qu'elle ne sera jamais oubliée.
"""

import pytest

from core.intents import detect_action

EXAM = {
    "messagerie": [
        ("Lis-moi mes mails", "mail_resume"),
        ("J'ai des nouveaux messages ?", "mail_resume"),
        ("Quel est mon dernier mail ?", "mail_last"),
        ("Résume mes emails non lus", "mail_resume"),
        ("Est-ce que j'ai reçu un mail ?", "mail_resume"),
        ("Envoie un mail à paul@exemple.com pour lui dire que j'arrive à 18h", "send_mail"),
        ("Écris un email à marie@test.fr : la réunion est annulée", "send_mail"),
        ("Qui m'a écrit aujourd'hui ?", "mail_resume"),
        ("Check mes mails", "mail_resume"),
        ("Tu peux regarder ma boîte mail ?", "mail_resume"),
        ("Montre-moi mes derniers emails", "mail_resume"),
    ],
    "agenda": [
        ("Qu'est-ce que j'ai cette semaine ?", "events_week"),
        ("Quel est mon programme demain ?", "events_range"),
        ("Ajoute un rendez-vous chez le dentiste demain à 15h", "add_event"),
        ("Mets une réunion lundi à 10h", "add_event"),
        ("Je suis libre quand cette semaine ?", "availability_week"),
        ("Quels sont mes rendez-vous aujourd'hui ?", "events_range"),
        ("Programme un déjeuner avec Sophie vendredi à midi", "add_event"),
        ("Supprime mes événements de demain", "delete_events_range"),
        ("C'est quoi mon agenda ?", "events_week"),
        ("Note dans mon agenda : match de foot samedi à 14h", "add_event"),
        ("Est-ce que j'ai quelque chose ce soir ?", "events_range"),
        ("Mes disponibilités cette semaine", "availability_week"),
    ],
    "alarmes": [
        ("Réveille-moi demain à 7h", "set_alarm"),
        ("Mets un réveil à 6h30", "set_alarm"),
        ("Lance un minuteur de 10 minutes", "set_alarm"),
        ("Minuteur 5 minutes", "set_alarm"),
        ("Rappelle-moi d'appeler maman à 18h", "set_alarm"),
        ("Rappelle-moi dans 20 minutes de sortir le linge", "set_alarm"),
        ("Quelles sont mes alarmes ?", "list_alarms"),
        ("Supprime toutes mes alarmes", "delete_alarms_all"),
        ("Annule le minuteur", "delete_timers"),
        ("Mets une alarme dans une heure", "set_alarm"),
        ("Préviens-moi dans un quart d'heure", "set_alarm"),
        ("Combien de temps reste-t-il sur le minuteur ?", "list_alarms"),
    ],
    "poste": [
        ("Ouvre Safari", "open_app"),
        ("Lance Spotify", "open_app"),
        ("Ferme Chrome", "quit_app"),
        ("Monte le son", "volume"),
        ("Baisse le volume", "volume"),
        ("Mets le volume à 30", "volume"),
        ("Coupe le son", "volume"),
        ("Remets le son", "volume"),
        ("Mets l'écran en veille", "sleep_display"),
        ("État du système", "system_status"),
        ("Combien de batterie il me reste ?", "system_status"),
        ("Ouvre youtube.com", "open_url"),
        ("Quitte Mail", "quit_app"),
        ("Ouvre le terminal", "open_app"),
    ],
    "informations": [
        ("Quelle heure est-il ?", "time"),
        ("Il est quelle heure ?", "time"),
        ("On est quel jour ?", "date"),
        ("Quelle est la date d'aujourd'hui ?", "date"),
        ("Quel temps fait-il ?", "weather"),
        ("Il va pleuvoir demain ?", "weather"),
        ("Météo à Toulouse", "weather"),
        ("Quelle température fait-il dehors ?", "weather"),
        ("Il fait beau à Colomiers ?", "weather"),
        ("Est-ce que je dois prendre un parapluie ?", "weather"),
        ("Fais-moi un briefing", "briefing"),
    ],
    "web": [
        ("Cherche les horaires du Leclerc de Blagnac", "web_answer"),
        ("Qui a gagné le match du Stade Toulousain ?", "web_answer"),
        ("Quel est le prix du Bitcoin ?", "web_answer"),
        ("Trouve-moi une pizzeria à Colomiers", "web_answer"),
        ("Quelles sont les actualités du jour ?", "web_answer"),
        ("Recherche sur Google la recette des crêpes", "web_answer"),
        ("C'est quand la prochaine sortie de GTA 6 ?", "web_answer"),
        ("Cherche sur YouTube un tuto Blender", "web_search"),
    ],
    "code": [
        ("Crée-moi un script Python qui trie mes téléchargements par type de fichier", "write_code"),
        ("Écris un programme qui convertit des degrés Celsius en Fahrenheit", "write_code"),
        ("Fais-moi un petit jeu du serpent", "write_code"),
        ("Code une fonction en JavaScript qui vérifie un email", "write_code"),
        ("Développe une application de liste de courses", "write_code"),
    ],
    "design": [
        ("Fais-moi un site pour une boulangerie à Colomiers", "design_page"),
        ("Crée une page d'accueil pour mon portfolio de photographe", "design_page"),
        ("Dessine-moi un logo pour mon club de tennis", "design_logo"),
        ("Propose-moi une palette de couleurs pour une appli de méditation", "design_palette"),
        ("Conçois une maquette pour un restaurant japonais", "design_page"),
    ],
    "atelier": [
        ("Ajoute un formulaire de contact à la page", "revise_creation"),
        ("Change les couleurs du logo en bleu nuit", "revise_creation"),
        ("Corrige-le", "revise_creation"),
        ("Améliore la page", "revise_creation"),
        ("Ouvre ma dernière création", "open_creation"),
        ("Montre-moi mes créations", "list_creations"),
        ("Où en est la page ?", "list_creations"),
    ],
    "messagerie avancée": [
        ("Réponds à Paul que c'est d'accord pour demain", "reply_mail"),
        ("Réponds au mail de la banque : je confirme le rendez-vous", "reply_mail"),
        ("Réponds-lui que je serai en retard", "reply_mail"),
        ("Lis-moi le mail de Sophie", "read_mail"),
        ("Lis le dernier message de la banque", "read_mail"),
        ("Cherche les mails de Paul", "search_mail"),
        ("Retrouve les messages concernant la facture EDF", "search_mail"),
        ("Archive le dernier mail", "archive_mail"),
        ("Supprime le mail de la newsletter", "trash_mail"),
        ("Supprime mon dernier mail", "trash_mail"),
    ],
    "agenda avancé": [
        ("Décale le dentiste à 16h", "move_event"),
        ("Déplace la réunion de demain à jeudi 10h", "move_event"),
        ("Repousse le déjeuner avec Sophie à 13h", "move_event"),
        ("Ajoute une réunion d'équipe tous les lundis à 9h", "add_event"),
        ("Programme un cours de sport tous les mardis et jeudis à 18h", "add_event"),
    ],
    "alarmes avancées": [
        ("Encore 5 minutes", "snooze_alarm"),
        ("Snooze", "snooze_alarm"),
        ("Laisse-moi dormir encore 10 minutes", "snooze_alarm"),
        ("Réveille-moi tous les jours à 7h", "set_alarm"),
        ("Mets un réveil en semaine à 6h45", "set_alarm"),
        ("Mets une alarme tous les samedis à 9h", "set_alarm"),
        ("Il reste combien de temps sur le minuteur ?", "list_alarms"),
    ],
    "poste avancé": [
        ("Augmente la luminosité", "brightness"),
        ("Baisse la luminosité de l'écran", "brightness"),
        ("Active le mode sombre", "dark_mode"),
        ("Passe en mode clair", "dark_mode"),
        ("Verrouille le Mac", "lock_screen"),
        ("Fais une capture d'écran", "screenshot"),
        ("Coupe le Wi-Fi", "wifi"),
        ("Réactive le wifi", "wifi"),
        ("Active le Bluetooth", "bluetooth"),
        ("Active ne pas déranger", "do_not_disturb"),
        ("Désactive le mode concentration", "do_not_disturb"),
    ],
    "informations avancées": [
        ("Quel temps fera-t-il ce week-end ?", "weather"),
        ("La météo de la semaine", "weather"),
        ("Il fera beau jeudi ?", "weather"),
        ("Météo pour après-demain", "weather"),
        ("À quelle heure se couche le soleil ?", "sun"),
        ("Heure du lever du soleil demain", "sun"),
        ("Quelle est la qualité de l'air ?", "air_quality"),
        ("Il y a de la pollution aujourd'hui ?", "air_quality"),
    ],
    "web avancé": [
        ("Résume cette page https://fr.wikipedia.org/wiki/Colomiers", "summarize_url"),
        ("De quoi parle www.lemonde.fr ?", "summarize_url"),
    ],
    "mémoire": [
        ("Souviens-toi que je prends mon café sans sucre", "remember"),
        ("Retiens que ma sœur s'appelle Léa", "remember"),
        ("N'oublie pas que je suis allergique aux arachides", "remember"),
        ("Qu'est-ce que tu sais sur moi ?", "recall"),
        ("Oublie que je prends mon café sans sucre", "forget"),
        ("Oublie tout ce que tu sais sur moi", "forget"),
    ],
    "traduction": [
        ("Comment on dit bonjour en anglais ?", "translate"),
        ("Traduis je suis en retard en espagnol", "translate"),
        ("Traduis en allemand : où est la gare ?", "translate"),
        ("C'est quoi merci en japonais ?", "translate"),
    ],
    "vision": [
        ("Regarde mon écran", "look_screen"),
        ("Qu'est-ce qu'il y a sur mon écran ?", "look_screen"),
        ("Tu vois quoi ?", "look_screen"),
        ("Lis ce qu'il y a sur mon écran", "look_screen"),
    ],
    "notes": [
        ("Prends une note : appeler le plombier lundi", "add_note"),
        ("Note que le code du portail est 1234", "add_note"),
        ("Ajoute du lait à ma liste de courses", "add_to_list"),
        ("Ajoute des œufs et du pain à la liste de courses", "add_to_list"),
        ("Mets réviser l'anglais sur ma liste de tâches", "add_to_list"),
        ("Qu'est-ce qu'il y a sur ma liste de courses ?", "read_list"),
    ],
    "trajets": [
        ("Combien de temps pour aller à Toulouse ?", "travel_time"),
        ("Temps de trajet jusqu'à l'aéroport de Blagnac", "travel_time"),
        ("Combien de temps à vélo jusqu'à la gare de Colomiers ?", "travel_time"),
        ("Quelle distance jusqu'à Montpellier ?", "travel_time"),
        ("Je mets combien de temps pour aller au Capitole à pied ?", "travel_time"),
    ],
    "fichiers": [
        ("Où est mon fichier budget 2026 ?", "find_file"),
        ("Trouve le document contrat de location", "find_file"),
        ("Retrouve la facture Free", "find_file"),
        ("Ouvre le fichier notes de réunion", "open_file"),
        ("Résume le document rapport annuel", "summarize_file"),
        ("Fais-moi un résumé du pdf conditions générales", "summarize_file"),
    ],
    "musique": [
        ("Mets de la musique", "music"),
        ("Mets la musique en pause", "music"),
        ("Pause", "music"),
        ("Chanson suivante", "music"),
        ("Morceau précédent", "music"),
        ("C'est quoi cette chanson ?", "music"),
        ("Reprends la musique", "music"),
        ("Mets du Daft Punk", "music"),
        ("Joue Bohemian Rhapsody", "music"),
        ("Mets la playlist Chill sur Spotify", "music"),
    ],
    "documents": [
        ("Rédige une lettre de résiliation pour ma salle de sport", "write_document"),
        ("Écris-moi une lettre de motivation pour un stage en informatique", "write_document"),
        ("Fais-moi un CV de développeur web", "write_document"),
        ("Prépare un compte-rendu de la réunion de ce matin", "write_document"),
    ],
    "atelier avancé": [
        ("Reviens à la version précédente", "previous_version"),
        ("Remets la version d'avant", "previous_version"),
    ],
    "routines": [
        ("Lance la routine travail", "run_routine"),
        ("Mode travail", "run_routine"),
        ("Active le mode bonne nuit", "run_routine"),
        ("Quelles sont mes routines ?", "list_routines"),
        ("Crée une routine soirée : baisse le son, puis mets de la musique", "create_routine"),
    ],
    "maison": [
        ("Allume la lumière du salon", "run_shortcut"),
        ("Éteins les lumières de la cuisine", "run_shortcut"),
        ("Ferme les volets", "run_shortcut"),
        ("Lance le raccourci Bonne nuit", "run_shortcut"),
        ("Quels sont mes raccourcis ?", "list_shortcuts"),
    ],
    # Pièges : ces phrases appartiennent à un agent historique, pas aux nouveaux.
    "pièges": [
        ("Coupe le son", "volume"),
        ("Ouvre Spotify", "open_app"),
        ("Ferme Chrome", "quit_app"),
        ("Mets l'écran en veille", "sleep_display"),
        ("Cherche le cours du Bitcoin", "web_answer"),
        ("Rappelle-moi dans 20 minutes de sortir le linge", "set_alarm"),
        ("Note dans mon agenda : match de foot samedi à 14h", "add_event"),
        ("Quel temps fait-il ?", "weather"),
        ("Ouvre la page de Wikipédia sur Napoléon", "web_search"),
    ],
    # Ce qui doit rester à la conversation : aucun agent ne doit s'en emparer.
    "conversation": [
        ("Raconte-moi une blague", None),
        ("C'est quoi le meilleur langage de programmation ?", None),
        ("Fais-moi un programme d'entraînement pour courir", None),
        ("Que penses-tu de l'intelligence artificielle ?", None),
        ("Tu te souviens du film qu'on a vu ?", None),
        ("Raconte-moi l'histoire de la musique classique", None),
        ("Pourquoi le ciel est bleu ?", None),
        ("Merci pour ton aide, c'était parfait", None),
    ],
}

CASES = [(agent, phrase, expected) for agent, items in EXAM.items() for phrase, expected in items]


@pytest.mark.parametrize("agent,phrase,expected", CASES, ids=[f"{a}:{p}" for a, p, _ in CASES])
def test_agent_understands(agent, phrase, expected):
    detected = detect_action(phrase)
    assert (detected or {}).get("action") == expected, f"{agent} : « {phrase} » → {detected}"


def test_code_language_is_noted():
    assert detect_action("Crée-moi un script Python qui renomme mes photos")["params"]["language"] == "python"
    assert detect_action("Code une fonction en JavaScript qui vérifie un email")["params"]["language"] == "javascript"


def test_event_titles_are_meaningful():
    titles = {
        "Note dans mon agenda : match de foot samedi à 14h": "Match de foot",
        "Ajoute un rendez-vous chez le dentiste demain à 15h": "Rendez-vous chez le dentiste",
        "Programme un déjeuner avec Sophie vendredi à midi": "Déjeuner avec Sophie",
    }
    for phrase, title in titles.items():
        assert detect_action(phrase)["params"]["title"] == title
