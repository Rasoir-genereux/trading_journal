# Journal de Trading

Application web locale de journalisation et d'analyse de trades, pensée pour les
traders qui utilisent **TradingView Paper Trading**. Elle importe automatiquement les
exports d'historique d'ordres, reconstruit les positions réelles, et affiche des
statistiques de performance détaillées — sans rien envoyer sur internet : tout tourne
et reste sur ta propre machine.

## Pourquoi cet outil

Les plateformes de trading exposent rarement une vue claire de la performance réelle
d'un trader dans le temps (par compte, par symbole, par tag de stratégie...). Ce projet
comble ce manque avec :

- **Import CSV TradingView** — reconstruction FIFO des trades à partir des exports
  d'ordres (entrées, stops, cibles, clôtures partielles), avec détection automatique des
  doublons
- **Comptes multiples** — un compte par broker/prop firm, avec dépôts/retraits et
  archivage
- **Dashboard** — solde, win rate, profit factor, courbes de solde et de P&L, calendrier
  mensuel cliquable, répartition par symbole
- **Tags & catégories** — classification libre des trades (erreurs, timeframe d'entrée,
  stratégie...) avec filtres globaux
- **Saisie manuelle** — ajout/édition de trades à la main, captures d'écran incluses
- **100 % local** — les données (`trades.db`, `screenshots/`) restent sur la machine, la
  UI supporte thème clair/sombre et français/anglais

## Stack technique

- Backend : [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/)
- Base de données : SQLite (`trades.db`, généré au premier lancement)
- Frontend : HTML/CSS/JS vanilla (`static/`)

## Démarrage rapide

```powershell
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```

Puis double-clique sur `start.bat`, ou lance :

```powershell
venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8420
```

Ouvre ensuite [http://127.0.0.1:8420](http://127.0.0.1:8420).

## Tests

```powershell
venv\Scripts\python.exe -m pip install -r requirements-dev.txt
venv\Scripts\python.exe -m pytest
```

Les tests tournent sur une base de données temporaire isolée — ils ne touchent jamais à
`trades.db` ni aux sauvegardes OneDrive.

**Voir [GUIDE.md](GUIDE.md)** pour le mode d'emploi complet : démarrage automatique avec
Windows, import CSV pas à pas, gestion multi-comptes, tags, sauvegarde des données,
transfert vers un autre ordinateur, dépannage.
