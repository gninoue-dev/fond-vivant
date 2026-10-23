"""Tout ce qui dépend du système : dossiers, outils externes, lancement automatique."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"
NOM_SERVEUR = "fond-vivant-" + (os.environ.get("USERNAME") or os.environ.get("USER") or "moi")

# évite qu'une console noire s'ouvre à chaque appel de mpv ou ffmpeg sous Windows
SANS_CONSOLE = subprocess.CREATE_NO_WINDOW if WINDOWS else 0

EXTENSIONS_VIDEO = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".gif", ".wmv", ".flv", ".ogv"}
EXTENSIONS_IMAGE = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".avif", ".jxl"}


def dossier_config() -> Path:
    if WINDOWS:
        base = Path(os.environ.get("APPDATA", Path.home()))
        return base / "FondVivant"
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "fond-vivant"


def dossier_cache() -> Path:
    if WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        return base / "FondVivant" / "cache"
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "fond-vivant"


def dossier_programme() -> Path:
    """Dossier de l'application (celui de l'exécutable une fois empaqueté)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def trouver_outil(nom: str) -> str | None:
    """mpv, ffmpeg, ffprobe : d'abord à côté de l'application, puis dans le PATH."""
    exe = nom + ".exe" if WINDOWS else nom
    for dossier in (dossier_programme() / "outils", dossier_programme()):
        if (dossier / exe).is_file():
            return str(dossier / exe)
    return shutil.which(nom)


def type_fichier(chemin: str) -> str | None:
    ext = Path(chemin).suffix.lower()
    if ext in EXTENSIONS_VIDEO:
        return "video"
    if ext in EXTENSIONS_IMAGE:
        return "image"
    return None


def commande_application(*arguments: str) -> list[str]:
    """Commande qui relance cette application (pour le lecteur et le démarrage auto)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *arguments]
    python = sys.executable
    if WINDOWS and python.lower().endswith("python.exe"):
        sans_fenetre = python[:-10] + "pythonw.exe"
        if os.path.isfile(sans_fenetre):
            python = sans_fenetre
    return [python, str(dossier_programme() / "lancer.py"), *arguments]


def lancer_detache(commande: list[str]):
    if WINDOWS:
        options = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                   | SANS_CONSOLE}
    else:
        options = {"start_new_session": True}
    subprocess.Popen(commande, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True, **options)


# --- lancement à l'ouverture de session ---------------------------------------

_CLE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
_FICHIER_AUTOSTART = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) \
    / "autostart" / "fond-vivant.desktop"


def autostart_actif() -> bool:
    if WINDOWS:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CLE_RUN) as cle:
                winreg.QueryValueEx(cle, "FondVivant")
            return True
        except OSError:
            return False
    return _FICHIER_AUTOSTART.exists()


def regler_autostart(actif: bool):
    commande = commande_application("--lecteur")
    if WINDOWS:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CLE_RUN, 0, winreg.KEY_SET_VALUE) as cle:
            if actif:
                winreg.SetValueEx(cle, "FondVivant", 0, winreg.REG_SZ, subprocess.list2cmdline(commande))
            else:
                try:
                    winreg.DeleteValue(cle, "FondVivant")
                except OSError:
                    pass
        return
    if not actif:
        _FICHIER_AUTOSTART.unlink(missing_ok=True)
        return
    _FICHIER_AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
    exec_ = " ".join(f'"{c}"' if " " in c else c for c in commande)
    _FICHIER_AUTOSTART.write_text("[Desktop Entry]\n"
                                  "Type=Application\n"
                                  "Name=Fond Vivant (lecteur)\n"
                                  f"Exec={exec_}\n"
                                  "X-GNOME-Autostart-Delay=3\n"
                                  "NoDisplay=true\n", encoding="utf-8")
