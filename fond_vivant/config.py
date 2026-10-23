"""Configuration partagée entre la fenêtre de réglage et le lecteur."""
import json
import os

from .systeme import dossier_config

FICHIER = dossier_config() / "config.json"

CADRAGES = {
    "remplir": "Remplir l'écran (rogne les bords si besoin)",
    "entier": "Afficher en entier (bandes noires)",
    "etirer": "Étirer à la taille de l'écran (déforme)",
}

DEFAUT = {
    "bibliotheque": [],      # [{"chemin": ..., "type": "video"|"image", "optimise": chemin ou ""}]
    "mode": "unique",        # "unique" : un seul fond ; "diaporama" : les images changent
    "actuel": "",            # chemin d'origine du fond affiché en mode unique
    "diaporama": [],         # chemins d'origine choisis pour le diaporama
    "intervalle": 600,       # secondes entre deux images du diaporama
    "aleatoire": True,
    "cadrage": "remplir",
    "fluidite": True,        # interpolation de mpv calée sur la fréquence de l'écran
    "son": False,
    "volume": 50,
    "pause": False,
}


def lire() -> dict:
    config = json.loads(json.dumps(DEFAUT))
    try:
        with open(FICHIER, encoding="utf-8") as f:
            config.update(json.load(f))
    except (OSError, ValueError):
        pass
    return config


def ecrire(config: dict):
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    temporaire = FICHIER.with_suffix(".tmp")
    with open(temporaire, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    os.replace(temporaire, FICHIER)  # le lecteur ne lit jamais un fichier à moitié écrit


def entree(config: dict, chemin: str) -> dict | None:
    for e in config["bibliotheque"]:
        if e["chemin"] == chemin:
            return e
    return None


def version_a_lire(config: dict, chemin: str) -> str:
    """La version optimisée si elle existe encore, sinon l'original."""
    e = entree(config, chemin)
    if e and e.get("optimise") and os.path.isfile(e["optimise"]):
        return e["optimise"]
    return chemin


def elements_a_jouer(config: dict) -> list[tuple[str, dict]]:
    """(fichier réellement lu, entrée de la bibliothèque) pour chaque fond à afficher."""
    if config.get("mode") == "diaporama":
        chemins = config.get("diaporama", [])
    else:
        chemins = [config["actuel"]] if config["actuel"] else []
    return [(version_a_lire(config, c), entree(config, c)) for c in chemins
            if entree(config, c) and os.path.isfile(c)]


def fichiers_a_jouer(config: dict) -> list[str]:
    return [fichier for fichier, _ in elements_a_jouer(config)]
