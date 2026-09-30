# Landing Page - Documentation technique

## But du document

Documenter techniquement la landing page du dossier `Page/`.

## Vue d'ensemble

Le dossier contient 2 fichiers:

- `Page/index.html`
- `Page/style.css`

Cette landing page est statique et ne charge actuellement aucun script JavaScript.

Son bouton principal ouvre le HUD de Jarvis (`http://localhost:8001/`), servi par l'API : il faut donc que `./run_jarvis.sh start` tourne.

---

## `index.html` (resume)

Le fichier definit la structure generale de la page en quelques blocs:

- un header de marque avec indicateur de statut
- un bloc hero (titre, description, CTA)
- plusieurs sections de contenu (comparaison, fonctionnalites, etapes, KPI, roadmap, exemples)
- un footer de cloture

Le `<head>` charge les polices Google Fonts (`JetBrains Mono`, `Syne`) et la feuille de style `style.css`.

---

## `style.css` (resume)

Le fichier gere:

- le theme visuel global (variables CSS, couleurs, typo)
- les composants de layout (topbar, cards, grilles)
- les effets visuels (scanlines, pulse)
- le responsive (breakpoints desktop/mobile)

---