# Rapport marketing — JARVIS

> Assistant de productivité conversationnel pour indépendants  
> Projet ELIZA — Epitech 2025/2026

---

## Sommaire

1. [Présentation du concept](#1-présentation-du-concept)
2. [Cible et persona](#2-cible-et-persona)
3. [Besoins identifiés](#3-besoins-identifiés)
4. [Objectifs du chatbot](#4-objectifs-du-chatbot)
5. [Value chain](#5-value-chain)
6. [KPIs](#6-kpis)
7. [ROI](#7-roi)
8. [Éthique](#8-éthique)

---

## 1. Présentation du concept

Il y a un paradoxe assez absurde dans le quotidien d'un freelance : plus il travaille, moins il a de temps pour travailler. Entre les emails à gérer, le calendrier à tenir, les relances clients à ne pas oublier et les réunions à planifier, une bonne partie de sa journée part dans de l'administratif qui ne génère aucune valeur.

JARVIS est né de ce constat. C'est un assistant conversationnel qui permet de gérer tout ça — agenda, emails, rappels, tâches — depuis une seule interface, en langage naturel. Pas besoin de naviguer entre cinq applications. L'utilisateur dit ce qu'il veut faire, JARVIS le fait.

Le nom est une référence directe à l'assistant IA de Tony Stark : omniprésent, réactif, qui anticipe les besoins sans qu'on ait à tout lui expliquer.

---

## 2. Cible et persona

**Cible :** Les travailleurs indépendants (consultants, développeurs, auto-entrepreneurs) qui gèrent seuls leur flux de travail.

**Persona — Théo, 31 ans :** Consultant IT indépendant. Il passe trop de temps sur Gmail et Google Calendar pour organiser ses rendez-vous, ce qui empiète sur son temps de production facturable.

---

## 3. Besoins identifiés

* Centraliser les outils Google (Gmail/Calendar).
* Réduire le temps de saisie manuelle.
* Avoir une vision claire des disponibilités sans ouvrir d'agenda.
* Automatiser les rappels pour ne rien oublier.

---

## 4. Objectifs du chatbot

* **Fluidité :** Comprendre le langage naturel pour exécuter des actions métier.
* **Rapidité :** Répondre et agir en quelques secondes.
* **Fiabilité :** Garantir que les emails sont envoyés et les RDV notés correctement.

---

## 5. Value chain

### Sans JARVIS — les frictions du quotidien

```
Réveil
  └─ Ouvre Gmail + Calendar + Slack + Notion séparément
     └─ 20-30 min perdues pour faire le point
        └─ Risque d'oublier une tâche ou un message urgent

Demande de RDV d'un client
  └─ Vérifie Calendar manuellement
     └─ Revient dans Gmail pour répondre
        └─ Crée l'événement à la main
           └─ ~5 min pour une action qui devrait prendre 30 secondes

Fin de journée
  └─ Note les tâches dans Notion
     └─ Les duplique dans Calendar
        └─ Double saisie, risque d'erreur ou d'oubli
```

À chaque étape, il y a du temps perdu, un risque d'erreur et une friction qui fatigue sans qu'on s'en rende compte. Sur une journée entière, ça représente facilement 1h30 à 2h de travail non productif.

### Avec JARVIS — ce qui change

```
Réveil
  └─ "JARVIS, résume ma journée"
     └─ Récap immédiat : RDV, emails prioritaires, tâches du jour

Demande de RDV d'un client
  └─ "JARVIS, planifie une réunion avec Dupont vendredi 14h et envoie-lui une invitation"
     └─ Exécuté automatiquement après confirmation

Relances
  └─ Configurées une fois, déclenchées automatiquement

Fin de journée
  └─ "JARVIS, ajoute 'revoir la prop commerciale' pour demain 9h"
     └─ Tâche créée ET ajoutée au calendrier en une commande
```

## Impact sur la chaîne de valeur

JARVIS intervient sur chaque point de friction identifié. Il ne remplace pas les outils existants — il les pilote. Le gain n'est pas uniquement en temps : c'est aussi moins d'erreurs, moins d'oublis, et une charge mentale réduite qui améliore la qualité du travail lui-même.

---

## 6. KPIs

### Contexte marché :

Avant de définir les KPIs du pilote, il est utile d'ancrer la réflexion dans des données existantes sur le temps que les freelances perdent réellement en tâches non facturables.

Selon une étude TPE Mag de mai 2024 sur les pratiques administratives des indépendants, **63 % des freelances consacrent jusqu'à une demi-journée par semaine à l'administratif**, soit environ 45 à 90 minutes par jour selon l'intensité des échanges clients. Près de la moitié (47 %) jugent cette charge stressante. Les tâches les plus chronophages citées sont la facturation et les relances (28 %), la gestion d'emails et de calendrier, et les déclarations récurrentes.

Ces chiffres cadrent directement avec la douleur que JARVIS cherche à résoudre. Ils fournissent aussi un **référentiel de baseline** : si un utilisateur type passe 60 minutes par jour en gestion email/agenda, et que JARVIS en réduit la moitié, le gain est de 30 minutes par jour, soit environ **10 heures par mois**.

### KPIs du pilote

Pour éviter les chiffres inventés, les KPIs ci-dessous sont définis avec une méthode de calcul et une colonne "valeur observée" à remplir après pilote. Les valeurs cibles sont des hypothèses de travail construites à partir des données marché ci-dessus.

| KPI | Définition | Méthode de calcul | Cible hypothétique | Valeur observée |
|---|---|---|---|---|
| **Temps gagné / jour** | Minutes économisées par utilisateur sur l'administratif email/agenda | (temps sans JARVIS) - (temps avec JARVIS), mesuré sur 2 semaines | ≥ 30 min/jour (hypothèse : -50 % sur ~60 min baseline) | À mesurer |
| **Taux de succès des actions** | % de commandes exécutées correctement du premier coup | actions réussies / actions demandées | ≥ 85 % | À mesurer |
| **Taux d'erreur critique** | % d'actions annulées ou corrigées après exécution | actions corrigées / actions exécutées | ≤ 5 % | À mesurer |
| **Activation J+7** | % de nouveaux utilisateurs encore actifs à 7 jours | utilisateurs actifs à J+7 / nouveaux inscrits | ≥ 60 % | À mesurer |
| **Rétention J+30** | % d'utilisateurs actifs à 30 jours | utilisateurs actifs à J+30 / nouveaux inscrits | ≥ 40 % | À mesurer |
| **Usage quotidien** | Intensité d'usage réelle | nombre moyen d'actions utiles par utilisateur actif et par jour | ≥ 5 actions/jour | À mesurer |
| **Satisfaction (CSAT/NPS)** | Satisfaction perçue | questionnaire court post-usage (NPS sur 0-10) | NPS ≥ 30 | À mesurer |

> **Note sur les cibles :** Ces valeurs ne sont pas garanties. Elles constituent des hypothèses de travail raisonnables, fondées sur les données de marché disponibles et la nature du problème résolu. Elles doivent être ajustées ou abandonnées si les mesures pilote s'en écartent significativement.

### Protocole minimal de collecte

1. **Baseline :** mesurer pendant 5 jours le temps passé sans JARVIS sur email et agenda (chrono ou déclaratif).
2. **Pilote :** mesurer les mêmes tâches pendant 10 jours avec JARVIS.
3. Journaliser automatiquement les actions, erreurs, annulations dans les logs.
4. Faire un mini questionnaire en fin de pilote (5 questions max, NPS inclus).
5. Reporter uniquement les résultats observés, pas de projection.

### Lecture marketing

- **Acquisition :** activation J+7.
- **Rétention :** rétention J+30 et usage quotidien.
- **Automatisation :** temps gagné et taux de succès.
- **Confiance produit :** taux d'erreur critique et NPS.

---

## 7. ROI

### Données de référence marché

Le ROI de JARVIS repose sur une équation simple : combien vaut une heure récupérée sur l'administratif pour un freelance IT ?

Sur ce point, les données de marché sont claires. Selon l'étude RH Solutions 2025 menée auprès de plus de 10 000 professionnels du secteur tech en France, **le TJM moyen d'un consultant IT confirmé (5-10 ans d'expérience) est de 462 €/jour**, avec des variations selon la spécialisation : infrastructure/réseaux à 556 €, consultant SI à 629 €, et un TJM moyen IDF de 613 €. L'étude Morgan Philips Freelance (BDM, 2025) situe les profils confirmés en cybersécurité entre 700 et 800 €/jour en IDF.

En retenant une hypothèse médiane de **500 €/jour** pour le profil de Théo (consultant IT confirmé, région parisienne), le taux horaire implicite est de **62,50 €/heure** (sur une base de 8h facturables par jour).

Par ailleurs, selon la même étude TPE Mag citée en section 6, un freelance consacre en moyenne **45 à 90 minutes par jour** à la gestion administrative (emails, agenda, relances). En hypothèse conservatrice, on retient **60 minutes par jour**, soit **20 heures par mois** sur 20 jours travaillés.

### Calcul du ROI (hypothèse de travail)

Le calcul suivant repose sur des hypothèses explicites, pas sur des mesures réelles. Il doit être mis à jour après le pilote.

**Hypothèses retenues :**
- Temps administratif baseline : 60 min/jour (source : TPE Mag, 2024).
- Réduction estimée avec JARVIS : 50 % → 30 min gagnées/jour → **~10 h/mois**.
- Part convertie en temps facturable supplémentaire : 40 % (hypothèse conservatrice, car tout le temps récupéré n'est pas immédiatement facturé).
- **Heures facturables récupérées : 4 h/mois.**
- Valeur horaire : 62,50 €/h (TJM 500 €/j, base 8h).
- **Gain mensuel : 4 × 62,50 = 250 €/mois.**
- Coût mensuel estimé de JARVIS : ~30-50 € (API LLM + hébergement minimal).

| Élément | Valeur |
|---|---|
| Baseline admin. quotidienne (source marché) | ~60 min/jour (TPE Mag, 2024) |
| Heures gagnées estimées / mois (-50 %) | ~10 h/mois |
| Part convertie en temps facturable | 40 % (hypothèse conservatrice) |
| Heures facturables récupérées / mois | ~4 h/mois |
| Valeur horaire (TJM 500 €/j, 8h) | 62,50 €/h (RH Solutions, 2025) |
| **Gain mensuel estimé (€)** | **~250 €/mois** |
| Coût mensuel infra + maintenance | ~30-50 €/mois (à confirmer) |
| **ROI mensuel estimé** | **~400-730 %** |
| Délai de retour (payback) | **< 1 semaine** |

**Formule appliquée :**
- Gain mensuel (€) = heures facturables récupérées × valeur horaire réelle
- ROI (%) = ((gain mensuel − coût mensuel) / coût mensuel) × 100

### Exigence de rigueur

Ces chiffres sont des **hypothèses de travail**, pas des résultats. Ils sont là pour dimensionner l'intérêt potentiel du produit et justifier la démarche pilote — pas pour être présentés comme des faits établis.

- Toute valeur chiffrée présentée en soutenance doit être traçable à une source (études citées, logs, questionnaire, suivi de tâches).
- Les hypothèses doivent être explicitement nommées comme telles.
- Après pilote, les valeurs mesurées remplacent les hypothèses dans ce tableau.

---

## 8. Éthique

### 8.1 Risque ELIZA et anthropomorphisme

Le projet reconnaît explicitement l'**effet ELIZA** : l'utilisateur peut attribuer au chatbot une compréhension humaine qu'il n'a pas.

Mesures :

- Le bot se présente comme un assistant IA, pas comme une personne.
- Les réponses rappellent qu'il peut se tromper sur des sujets ambigus.
- Les actions sensibles (emails, suppressions, planification) restent pilotées par l'utilisateur et vérifiables.

### 8.2 Évaluation d'impact éthique 

| Risque | Impact potentiel | Niveau | Mesures de prévention/mitigation |
|---|---|---|---|
| **Atteinte à la vie privée** | exposition de données email/calendrier | Élevé | OAuth2, token local, périmètre de scopes limité, suppression token à la déconnexion/arrêt |
| **Manque de transparence** | confusion sur la nature IA du système | Moyen | expliciter le statut IA, documentation des limites, messages de confirmation |
| **Désinformation / hallucination** | mauvaise décision utilisateur | Moyen | ton factuel, confirmation avant action, possibilité de vérification via Gmail/Calendar |
| **Dépendance d'usage** | perte d'autonomie sur tâches simples | Faible à moyen | design orienté assistant outillage, pas compagnon affectif, contrôle manuel possible |
| **Chatbot psychosis / projection émotionnelle** | surinvestissement émotionnel, confusion relationnelle | Moyen | éviter langage de substitution affective, rappeler le rôle utilitaire, encourager recours humain en cas de détresse |
| **Biais algorithmiques** | réponses inéquitables ou stéréotypées | Moyen | prompts neutres, revue de cas limites, tests sur formulations variées, corrections itératives |

### 8.3 Données : responsabilité et transparence

- Données traitées : emails, événements calendrier, alarmes locales.
- Stockage : token OAuth et alarmes stockés localement côté API.
- Contrôle utilisateur : connexion/déconnexion Google explicite, suppression du token local.
- Principe de minimisation : seulement les accès nécessaires aux fonctionnalités demandées.
- Conformité RGPD : le traitement de données personnelles (contenu des emails, événements) implique une information claire de l'utilisateur sur la nature, la durée et la finalité du traitement, conformément au règlement européen en vigueur.

### 8.4 Fairness et biais

Le modèle peut refléter des biais présents dans les données et dans les formulations utilisateur.

Plan de réduction :

- jeux de tests multi-formulations (genre, ton, niveau de langue, accents, fautes) ;
- vérification que l'intention détectée dépend du besoin, pas du style de l'utilisateur ;
- revue régulière des échecs et ajustement des prompts/règles de parsing.

### 8.5 Gouvernance produit

Pour garantir un usage responsable dans le temps :

- suivi des incidents (mauvaise action, mauvaise interprétation, contenu inadéquat) ;
- revue mensuelle KPI + incidents ;
- correction prioritaire des risques à impact élevé (vie privée, suppression involontaire, envoi mail erroné).

---

*Sources utilisées pour les sections 6 et 7 :*
- *TPE Mag, « Administratif : tant d'heures perdues », mai 2024.*
- *RH Solutions, « TJM des freelances tech : Étude 2025 », oct. 2025.*
- *Morgan Philips Freelance / BDM, « TJM dans l'IT en France en 2025 », oct. 2025.*
- *Clockify, « How freelancers spend time », étude internationale.*