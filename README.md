# Fond Vivant

Gestionnaire de fonds d'écran animés (vidéos) et de photos pour **Linux** et **Windows**.

- Lecture **fluide à 60 i/s** : décodage par la carte graphique, cadence calée sur la fréquence réelle de l'écran et interpolation entre les images (mpv).
- La vidéo **remplit tout l'écran**, quel que soit son format : elle est recadrée sans bandes noires ni déformation (on peut aussi choisir « en entier » ou « étirer »).
- **Optimiser pour mon écran** : ffmpeg prépare une copie à la taille exacte de l'écran et, si la vidéo est en 24 ou 30 i/s, crée les images manquantes par interpolation de mouvement pour obtenir une vraie vidéo à 60 i/s.
- **Diaporama** : tes photos (et vidéos) changent toutes seules, toutes les 15 secondes à 1 jour, dans l'ordre ou au hasard, avec un bouton « Image suivante ».
- Interface simple : on choisit « Un seul fond » ou « Diaporama », puis un clic sur une image suffit. Les réglages techniques sont rangés dans « Plus d'options ».
- Ajout de fichiers ou d'un dossier entier, glisser-déposer, son et volume, pause, plusieurs écrans, démarrage avec l'ordinateur.
- Les clics traversent le fond : les icônes et le menu du bureau restent utilisables.

## Comment ça marche

| Partie | Langage | Rôle |
|---|---|---|
| `natif/fv_bureau.c` | C | Crée la fenêtre « fond d'écran » derrière les icônes : fenêtre X11 de type bureau sous Linux, enfant du `WorkerW` de l'explorateur sous Windows. Liste aussi les écrans (taille réelle et fréquence). |
| mpv | (externe) | Dessine la vidéo ou la photo dans cette fenêtre. |
| `fond_vivant/lecteur.py` | Python | Lance une fenêtre de fond et un mpv par écran, les pilote à chaud par leur canal IPC. |
| `fond_vivant/reglages.py` | Python (Qt) | La fenêtre de réglage. |
| `fond_vivant/optimiseur.py` | Python + ffmpeg | Recadrage et passage à 60 i/s. |
| `gnome-extension/` | JavaScript | Sous GNOME : affiche le fond animé dans la couche du fond d'écran, sous les icônes du bureau. |

## Installation sous Linux (depuis les sources)

```bash
sudo apt install mpv ffmpeg libxcb-cursor0 libx11-dev libxext-dev libxrandr-dev
make -C natif                    # compile outils/fv-bureau
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python lancer.py
```

Sous GNOME, installe aussi l'extension pour que les icônes du bureau restent visibles :

```bash
ln -s "$PWD/gnome-extension/fond-vivant@gninoue-dev.github.com" ~/.local/share/gnome-shell/extensions/
# puis Alt+F2, « r », Entrée (recharge GNOME), et :
gnome-extensions enable fond-vivant@gninoue-dev.github.com
```

Il faut une session **X11** (« Ubuntu sur Xorg » sur l'écran de connexion). Sous Wayland, GNOME ne laisse pas une application se placer derrière le bureau.

## Windows

Le dossier `outils/` à côté de l'application doit contenir `mpv.exe`, `ffmpeg.exe`, `ffprobe.exe` et `fv-bureau.exe` (compilé avec `make -C natif windows`, qui demande `gcc-mingw-w64`).

## Commandes

```bash
python lancer.py             # fenêtre de réglage
python lancer.py --lecteur   # le fond seul (utilisé au démarrage de session)
python lancer.py --arreter   # arrête le fond
```

## Licence

MIT
