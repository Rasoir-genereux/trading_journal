# Guide d'utilisation — Journal de Trading

Outil local de journalisation et de visualisation de trades, hébergé sur ton propre
ordinateur. Aucune donnée n'est envoyée sur internet — tout reste dans le dossier
`trading-journal`.

---

## 1. Démarrer l'outil

1. Ouvre le dossier `E:\trading-journal`
2. Double-clique sur **`start.bat`**
3. Une fenêtre noire (terminal) s'ouvre et reste ouverte — c'est normal, c'est le serveur.
   **Ne la ferme pas** tant que tu utilises l'outil.
4. Ouvre ton navigateur à l'adresse : **http://127.0.0.1:8420**

### Important : le serveur ne redémarre pas tout seul

Le serveur tourne uniquement pendant que la fenêtre `start.bat` est ouverte. Si tu :
- fermes cette fenêtre,
- éteins ou redémarres l'ordinateur,
- ou que Windows se met à jour et redémarre,

...le serveur s'arrête, et `http://127.0.0.1:8420` ne répondra plus jusqu'à ce que tu
relances `start.bat`.

**Pour lancer le serveur automatiquement à chaque démarrage de Windows** (optionnel) :
1. Appuie sur `Win + R`, tape `shell:startup`, Entrée — ça ouvre ton dossier de démarrage
2. Fais un clic droit dans ce dossier → **Nouveau → Raccourci**
3. Cible : `E:\trading-journal\start.bat`
4. Donne-lui un nom (ex. "Journal de Trading") et termine

À chaque connexion Windows, une fenêtre de terminal s'ouvrira brièvement en arrière-plan
et le serveur sera prêt sans que tu aies à y penser. Tu peux minimiser cette fenêtre, mais
ne pas la fermer.

---

## 2. Vue d'ensemble de l'outil

Le ruban à gauche donne accès à ces sections :

| Section | Contenu |
|---|---|
| **Dashboard** | Vue d'ensemble : solde, jauges (win %, profit factor...), courbes de solde et de P&L, calendrier mensuel cliquable, tableau par symbole |
| **Trades** | Liste complète de tous les trades, filtrable, avec ajout/édition manuelle, sélection et export CSV |
| **Performance** | 4 sous-onglets : Aperçu, Résumé, Jours, Trades — statistiques détaillées |
| **Prop Firms** | Suivi de tes comptes de prop firm (achats, passages de phase, financement, payouts...) |
| **Compte** | Gestion des comptes, dépôts/retraits, catégories de tags, langue |
| **Importer CSV** | Import des exports TradingView ou des rapports MetaTrader 5, avec journal des imports |
| **Analyses** | Journal de tes analyses de marché, organisé par calendrier mensuel |
| **Aide** | Ce guide, directement dans l'application |

Le bouton ☀️/🌙 en haut à droite bascule entre thème clair et sombre (préférence
sauvegardée dans le navigateur). Le sélecteur de langue (Compte → Réglages) bascule toute
l'interface entre français et anglais.

---

## 3. Comptes multiples

Tu peux créer plusieurs comptes (ex. un par broker/prop firm) dans **Compte → Comptes**.
Chaque compte a :
- un nom
- un solde de départ et une date de départ
- ses propres dépôts/retraits (section **Dépôts / Retraits**)
- un statut actif/archivé (archiver au lieu de supprimer si tu veux garder l'historique
  sans qu'il pollue les listes courantes)

Un compte ne peut être **supprimé** que s'il n'a aucun trade ni mouvement associé —
sinon, archive-le.

Le filtre **"Tous les comptes"** en haut à droite permet de restreindre tout le dashboard
(soldes, graphiques, calendrier, performance) à un ou plusieurs comptes précis.

---

## 4. Importer des trades (TradingView ou MetaTrader 5)

Dans l'onglet **Importer CSV**, choisis d'abord la **plateforme** (TradingView ou
MetaTrader 5) dans le menu déroulant en haut — la description et le type de fichier
attendu s'ajustent automatiquement.

### Où trouver l'export TradingView
Dans TradingView : **Paper Trading → Historique des ordres → Exporter**.

### Ce que fait l'outil
Ce fichier liste des **ordres** (entrées, stops, cibles, clôtures partielles), pas des
trades. L'outil reconstruit chaque position réelle en appariant les fills en **FIFO**
(premier entré, premier sorti), y compris pour les clôtures en plusieurs fois. Les ordres
`Cancelled` (stops/cibles jamais déclenchés) sont ignorés.

### Étapes
1. Va dans **Importer CSV**
2. Choisis le **compte** cible dans le menu déroulant (obligatoire — c'est à ce compte
   que les trades seront rattachés)
3. Sélectionne le fichier CSV, clique **Analyser le fichier**
4. Un aperçu des trades reconstruits s'affiche ; les doublons déjà présents sont grisés
   et décochés automatiquement
5. Clique **Importer la sélection**

### Doublons
Un trade est reconnu comme doublon (et ignoré) si, pour le **même compte**, le symbole,
la quantité, l'heure d'entrée et l'heure de sortie correspondent exactement à un trade
déjà importé. Tu peux donc réimporter le même fichier ou des fichiers qui se chevauchent
sans crainte — rien ne sera compté en double.

### Historique des imports
Le bas de l'onglet **Importer CSV** liste tous les imports effectués (date, fichier,
compte, nombre de trades importés/ignorés). Le bouton **Annuler l'import** supprime en
un clic tous les trades d'un import précis, si tu t'es trompé de compte par exemple.

### Conversion en USD
Le P&L est calculé en USD :
- directement si la paire est cotée en USD (ex. EURUSD, XAUUSD)
- via le taux implicite dérivé de la marge/levier déclarés par TradingView pour les
  paires croisées (ex. EURAUD, USDCHF, CHFJPY)

Dans de rares cas (une position qui s'inverse en un seul ordre), TradingView ne fournit
pas cette info pour un fill précis ; l'outil réutilise alors automatiquement le taux du
dernier trade converti pour ce même symbole (dans le fichier, ou dans un import
précédent) plutôt que de laisser le P&L incorrect.

### "Ce fichier ne ressemble pas à un export TradingView..."
TradingView a changé la casse de ses en-têtes de colonnes selon la version de l'export
(`Quantity` vs `Qty`, `Fill price` vs `Fill Price`...). L'outil gère normalement toutes
ces variantes automatiquement. Si cette erreur apparaît quand même, le fichier n'est
probablement pas un export "Paper Trading → Order History" — vérifie que tu n'as pas
exporté autre chose (positions, résumé de compte, etc.).

### Import MetaTrader 5

**Où trouver le rapport** : dans le terminal MT5, onglet **Historique**, clic droit →
**Rapport** → enregistrer au format **.xlsx**.

**Ce que fait l'outil** : contrairement à TradingView, MT5 fournit déjà une section
"Positions" avec une ligne par position clôturée (les clôtures partielles sont déjà
regroupées par la plateforme) — aucune reconstruction n'est nécessaire, les trades sont
importés tels quels. Le P&L (colonne "Profit") est déjà exprimé dans la devise du compte
par MT5 ; il est traité comme un montant en USD si le rapport indique un compte libellé
en USD (cas de la plupart des prop firms), sinon il reste affiché dans sa devise
d'origine sans conversion. La commission et le swap (frais de financement overnight)
sont additionnés dans la colonne "Commission" du journal.

Les étapes et la logique de doublons sont identiques à l'import TradingView (voir
ci-dessus) — seul le fichier attendu change (.xlsx au lieu de .csv).

---

## 5. Saisie manuelle

Dans **Trades → + Ajouter un trade**, tu peux entrer un trade à la main : compte,
symbole, sens, quantité, prix d'entrée/sortie, stop/take profit, prix MAE/MFE,
commission, dates, stratégie, catégories/tags, notes et des captures d'écran.

Le P&L en USD n'est calculé automatiquement pour un trade manuel que si la paire est
déjà cotée en USD ; pour une paire croisée saisie à la main, le P&L reste affiché dans
sa devise native (aucune donnée de marge/levier n'est disponible pour le déduire).

### Prix MAE / MFE
MAE (Maximum Adverse Excursion) et MFE (Maximum Favorable Excursion) — respectivement le
point le plus défavorable et le plus favorable atteint par le prix pendant la durée du
trade. L'outil n'ayant pas accès à un flux de données de marché, ces deux prix doivent
être renseignés manuellement (en regardant le graphique) ; une fois saisis, ils
s'affichent sous forme de badges colorés (rouge/vert) dans le détail du trade.

### Notes et captures d'écran
Le champ Notes propose une mise en forme basique (gras, italique, souligné, couleur de
texte, lien). Colle un lien seul sur sa propre ligne pour obtenir un aperçu automatique
(titre, image, description) directement dans le texte. Tu peux joindre plusieurs
captures d'écran par trade ; chacune a son propre bouton de suppression, et un aperçu
s'affiche dès que tu la sélectionnes, avant même d'enregistrer.

---

## 6. Journal d'analyses

L'onglet **Analyses** affiche un calendrier mensuel indépendant de tes comptes de
trading — pratique pour journaliser tes analyses de marché sans les rattacher à un
trade précis.

- Survole un jour puis clique le bouton **+** (apparaît au survol) pour créer une
  analyse à cette date
- Une analyse a un **titre** libre et le même éditeur de notes riches (avec captures
  d'écran) que les trades
- Clique sur une entrée existante dans le calendrier pour l'ouvrir en édition, ou pour
  la supprimer

---

## 7. Catégories et tags

Dans **Compte → Catégories**, crée des catégories (ex. "Erreurs", "Timeframe d'entrée",
avec une couleur) puis ajoute des tags à l'intérieur. Ces tags apparaissent ensuite dans
les détails de chaque trade sous forme de menus déroulants par catégorie — tu peux aussi
créer un nouveau tag directement depuis là avec le bouton **+**.

Le filtre **"Tags & Stratégie"** en haut à droite permet de filtrer tout le dashboard par
tag et/ou par stratégie utilisée (le champ Stratégie est un texte libre proposant
l'auto-complétion des valeurs déjà saisies).

---

## 8. Filtres globaux

Trois filtres en haut à droite s'appliquent à **tout** le dashboard (Dashboard, Trades,
Performance, aperçu journalier du calendrier) :

- **Date** : raccourcis (aujourd'hui, cette semaine, ce mois-ci, 30 derniers jours...) ou
  plage personnalisée
- **Comptes** : un ou plusieurs comptes, avec option d'inclure les archivés
- **Tags & Stratégie** : un ou plusieurs tags et/ou stratégies

---

## 9. Sauvegarder tes données

Toutes tes données vivent dans deux endroits, à l'intérieur du dossier
`trading-journal` :

- **`trades.db`** — la base de données (comptes, trades, tags, dépôts/retraits, réglages)
- **`screenshots/`** — les captures d'écran attachées aux trades et aux analyses

### Sauvegarde automatique
À chaque démarrage de l'outil, une copie de `trades.db` (horodatée) et des captures
d'écran est automatiquement enregistrée dans `OneDrive\LibertamBackups\` — aucune
manipulation requise de ta part. Les 14 dernières sauvegardes de la base sont
conservées ; les plus anciennes sont supprimées automatiquement. Les captures d'écran
sont copiées de façon additive (jamais supprimées de la sauvegarde, même si tu en
retires une dans l'outil).

Cette sauvegarde protège contre une panne de disque ou une perte de la machine
puisqu'elle part dans le cloud via OneDrive — vérifie simplement que OneDrive est bien
lancé et synchronise normalement sur ta machine (icône dans la barre des tâches).

### Export CSV
En complément, l'onglet **Trades** permet d'exporter tes trades (tous ceux filtrés, ou
une sélection précise via les cases à cocher) au format CSV — utile pour une déclaration
fiscale, une analyse dans Excel, ou un partage avec un mentor/prop firm.

---

## 10. Transférer l'outil sur un autre ordinateur

Oui, c'est possible — l'outil est 100 % local, rien n'est lié à cet ordinateur en
particulier.

### Étape 1 — Copier le dossier
Copie tout le dossier `E:\trading-journal` sur une clé USB, un disque
externe ou via le cloud (OneDrive, etc.), puis colle-le sur le nouvel ordinateur (par
exemple à `C:\Users\<toi>\trading-journal`).

**Tu peux exclure le dossier `venv\`** avant de copier (c'est le plus volumineux et il
sera régénéré à l'étape 2) — sinon, le copier ne pose pas de problème non plus, juste
plus long.

### Étape 2 — Installer Python
Sur le nouvel ordinateur, installe **Python 3.11 ou plus récent**
(https://www.python.org/downloads/) si ce n'est pas déjà fait. Coche bien
"Add Python to PATH" pendant l'installation.

### Étape 3 — Réinstaller les dépendances
Ouvre un terminal (PowerShell) dans le dossier `trading-journal` copié, puis :

```powershell
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```

Si tu as exclu `venv\` à l'étape 1, cette étape le recrée proprement. Si tu l'as copié
tel quel, tu peux quand même relancer cette commande par sécurité (elle ne fait rien de
mal si tout est déjà en place) — ou simplement essayer `start.bat` directement, ça
fonctionne souvent même avec un `venv` copié tel quel du moment que la version de Python
est proche.

### Étape 4 — Lancer
Double-clique sur `start.bat` comme d'habitude, puis ouvre
`http://127.0.0.1:8420`.

Tes comptes, trades, tags, captures d'écran et réglages seront exactement comme sur
l'ancien ordinateur, puisque tout vit dans `trades.db` et `screenshots/` que tu as
copiés.

### À savoir
- Les deux ordinateurs peuvent avoir une copie du dossier en même temps, mais **ils ne
  se synchronisent pas automatiquement entre eux** — si tu modifies des trades sur l'un,
  il faut recopier `trades.db` (et `screenshots/` si besoin) vers l'autre pour que les
  deux soient à jour. Pour éviter toute confusion, le plus simple est de n'utiliser
  qu'une seule copie "active" à la fois.
- Si tu veux que les deux ordinateurs travaillent sur les **mêmes données en
  permanence**, il faudrait héberger `trading-journal` sur un espace synchronisé en
  continu (ex. le dossier lui-même dans OneDrive) — possible, mais pas configuré comme
  ça actuellement, et il y a un risque de conflit si les deux machines écrivent en même
  temps. Demande-moi si tu veux explorer cette option.

---

## 11. Dépannage

**Le navigateur affiche "Impossible d'accéder à ce site" sur `127.0.0.1:8420`**
→ Le serveur n'est pas lancé. Double-clique sur `start.bat` (voir section 1).

**`start.bat` s'ouvre puis se ferme tout de suite**
→ Une erreur a eu lieu au démarrage. Relance-le en ouvrant d'abord un terminal
(PowerShell) dans le dossier, puis tape `start.bat` directement pour voir le message
d'erreur qui reste affiché.

**"Address already in use" / le port 8420 est occupé**
→ Un serveur tourne déjà (peut-être une fenêtre `start.bat` oubliée en arrière-plan,
minimisée). Cherche-la dans la barre des tâches avant d'en relancer une nouvelle.

**J'ai perdu des données / un import s'est mal passé**
→ Rien n'est jamais supprimé silencieusement par l'outil lui-même. Si un import a
inséré ce qu'il ne fallait pas, va dans **Importer CSV → Historique des imports** et
clique **Annuler l'import** sur la ligne concernée.

**Le solde ne correspond pas à ce que j'attends**
→ Vérifie le filtre de comptes en haut à droite (peut-être qu'un seul compte est
sélectionné), et le filtre de dates (peut-être qu'une période restreinte est active).
Clique sur "Toute la période" et "Tous les comptes" pour repartir d'une vue complète.
