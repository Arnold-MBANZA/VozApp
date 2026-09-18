# VozLocal

VozLocal est une application web complète de transcription de cours en portugais brésilien. Le moteur fonctionne sur votre propre Mac ou PC : les utilisateurs disposent d’un compte, d’un historique privé, d’un lecteur audio et d’exports TXT/Word. Un tableau de bord d’administration permet de suivre l’activité et de suspendre des comptes.

## Fonctionnalités

- accueil public, inscription et connexion sécurisée ;
- premier compte automatiquement administrateur ;
- comptes utilisateur et administrateur avec sessions expirables ;
- import M4A, MP3, WAV, FLAC, OGG, WEBM et MP4 jusqu’à 500 Mo par défaut ;
- transcription intégrale des audios longs, découpés par FFmpeg en segments de 28 secondes ;
- stockage persistant dans SQLite ;
- historique privé avec audio et texte brut associés ;
- module « Mes cours » avec cartes, enseignant, couleur et archivage ;
- classement des séances par cours, titre et date, avec catégorie automatique « Sans cours » ;
- filtres d’historique par cours, date et statut ;
- copie du texte et téléchargements TXT et DOCX ;
- suppression indépendante de l’audio, du texte, ou des deux ;
- accélération Apple Metal, NVIDIA CUDA ou CPU ;
- interface responsive pour ordinateur, tablette et téléphone.

## Démarrer sur macOS

Prérequis : Python 3.11, FFmpeg, 8 Go de RAM minimum et environ 5 Go d’espace libre.

```bash
brew install python@3.11 ffmpeg
cd /chemin/vers/VozLocal
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --timeout 120 --retries 10 -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Ouvrez ensuite `http://127.0.0.1:8000`. Le premier compte créé devient administrateur. Les comptes suivants sont de simples utilisateurs.

Vous pouvez aussi lancer :

```bash
chmod +x lancer_mac_linux.sh
./lancer_mac_linux.sh
```

## Démarrer sur Windows Intel

Installez FFmpeg puis double-cliquez sur `lancer_windows.bat` :

```powershell
winget install Gyan.FFmpeg
```

Le script crée l’environnement Python, installe les dépendances et ouvre l’application.

## Mode démo sans modèle lourd

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-demo.txt
TRANSCRIBER_DEMO=1 python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Le mode démo produit un petit texte de démonstration et permet de tester tous les comptes, écrans, exports et suppressions.

## Données et administration

Les données sont conservées dans :

```text
data/
├── vozlocal.sqlite3       # comptes, cours, sessions, historique et textes
├── uploads/               # audios conservés
└── outputs/               # exports TXT et DOCX
```

Pour promouvoir un autre compte administrateur :

```bash
source .venv/bin/activate
python manage.py promote adresse@exemple.com
```

Sauvegardez régulièrement le dossier `data/`. Ne le placez jamais dans un dépôt Git public.

La mise à jour crée automatiquement la table `courses` et ajoute les informations de séance
à la table `jobs`. Les anciens enregistrements restent intacts et apparaissent dans
la catégorie « Sans cours ». Supprimer un cours ne supprime ni ses audios ni ses textes :
ils reviennent également dans « Sans cours ».

## Mettre le site sur Vercel et traiter sur le Mac

Vercel héberge uniquement les fichiers du dossier `frontend/`. Le Mac reste le serveur privé qui exécute Whisper, conserve les comptes, les audios et les textes.

1. Publiez le dossier `frontend/` comme projet Vercel.
2. Donnez à votre Mac une URL HTTPS stable, par exemple avec Tailscale Funnel ou Cloudflare Tunnel.
3. Dans `frontend/config.js`, indiquez cette URL :

```js
window.VOZLOCAL_CONFIG = { apiBaseUrl: "https://votre-mac.exemple.ts.net" };
```

4. Autorisez uniquement votre domaine Vercel au démarrage du serveur :

```bash
VOZLOCAL_ALLOWED_ORIGINS=https://votre-projet.vercel.app \
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Important : Vercel ne lance pas le modèle Whisper et ne conserve pas la base de données. Si le Mac est éteint ou en veille, le site public reste visible mais la connexion, l’historique et les transcriptions sont indisponibles. Pour une vraie mise en production publique, placez le serveur derrière HTTPS et protégez l’accès au Mac avec un tunnel correctement configuré.

## Réglages utiles

```bash
# Autre modèle Hugging Face
TRANSCRIBER_MODEL=openai/whisper-large-v3-turbo ./lancer_mac_linux.sh

# Limite d’import en Mo
VOZLOCAL_MAX_UPLOAD_MB=750 ./lancer_mac_linux.sh

# Durée des sessions (1 à 90 jours)
VOZLOCAL_SESSION_DAYS=7 ./lancer_mac_linux.sh

# Dossier de données personnalisé
VOZLOCAL_DATA_DIR=/chemin/vers/donnees ./lancer_mac_linux.sh
```

Le modèle par défaut est `freds0/distil-whisper-large-v3-ptbr`. Il est téléchargé lors de la première transcription puis réutilisé depuis le cache local Hugging Face.

## Vérification

```bash
python -m unittest discover -s tests -v
```

Le serveur expose aussi sa documentation technique sur `http://127.0.0.1:8000/docs`.
