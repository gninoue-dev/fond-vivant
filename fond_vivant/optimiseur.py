"""Préparer une vidéo pour l'écran avec ffmpeg, et fabriquer les miniatures.

Optimiser = recadrer à la taille exacte de l'écran (sans bandes noires ni déformation)
et, si la vidéo a moins d'images par seconde que l'écran, créer les images manquantes
par interpolation de mouvement (minterpolate) : une vidéo à 24 ou 30 i/s devient une
vraie vidéo à 60 i/s. mpv n'a plus qu'à la lire telle quelle, sans redimensionner.
"""
import hashlib
import json
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

from .systeme import SANS_CONSOLE, dossier_cache, trouver_outil


def sonder(chemin: str) -> dict:
    """Durée, taille, images par seconde et présence de son, via ffprobe."""
    ffprobe = trouver_outil("ffprobe")
    infos = {"duree": 0.0, "largeur": 0, "hauteur": 0, "fps": 0.0, "son": False}
    if not ffprobe:
        return infos
    try:
        sortie = subprocess.run([ffprobe, "-v", "error", "-print_format", "json", "-show_streams",
                                 "-show_format", chemin], capture_output=True, timeout=20,
                                creationflags=SANS_CONSOLE).stdout
        donnees = json.loads(sortie or b"{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return infos
    infos["duree"] = float(donnees.get("format", {}).get("duration") or 0)
    for flux in donnees.get("streams", []):
        if flux.get("codec_type") == "audio":
            infos["son"] = True
        elif flux.get("codec_type") == "video" and not infos["largeur"]:
            infos["largeur"] = int(flux.get("width") or 0)
            infos["hauteur"] = int(flux.get("height") or 0)
            num, _, den = (flux.get("avg_frame_rate") or flux.get("r_frame_rate") or "0/1").partition("/")
            try:
                infos["fps"] = float(num) / float(den or 1)
            except (ValueError, ZeroDivisionError):
                pass
    return infos


def _empreinte(chemin: str) -> str:
    stat = os.stat(chemin)
    return hashlib.sha1(f"{os.path.abspath(chemin)}|{stat.st_size}|{stat.st_mtime_ns}".encode()).hexdigest()[:12]


def chemin_optimise(source: str, largeur: int, hauteur: int, fps: int, interpolation: bool) -> Path:
    suffixe = "_mi" if interpolation else ""
    return dossier_cache() / "optimisees" / f"{Path(source).stem[:40]}_{_empreinte(source)}_{largeur}x{hauteur}_{fps}{suffixe}.mp4"


def commande_ffmpeg(source, sortie, largeur, hauteur, fps, interpolation, infos) -> list[str]:
    largeur, hauteur = largeur - largeur % 2, hauteur - hauteur % 2  # exigé par le H.264 en 4:2:0
    filtres = [
        f"scale={largeur}:{hauteur}:force_original_aspect_ratio=increase:flags=lanczos",
        f"crop={largeur}:{hauteur}",
        "setsar=1",
    ]
    fps_source = infos["fps"]
    if fps_source and fps_source < fps - 0.5 and interpolation:
        # images intermédiaires calculées à partir du mouvement : vraie fluidité
        filtres.append(f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1")
    elif fps_source > fps + 0.5:
        filtres.append(f"fps={fps}")  # 120 i/s sur un écran 60 Hz : inutile à décoder
    commande = [
        trouver_outil("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1",
        "-y", "-i", source, "-map", "0:v:0", "-vf", ",".join(filtres),
        "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-g", str(fps * 2),
    ]
    if infos["son"]:
        commande += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "160k"]
    return commande + ["-movflags", "+faststart", str(sortie)]


class Optimisation(QObject):
    """Une conversion ffmpeg en arrière-plan, avec sa progression (0 à 1)."""

    progression = Signal(float)
    terminee = Signal(bool, str)  # réussite, chemin de sortie ou message d'erreur

    def __init__(self, source, largeur, hauteur, fps, interpolation, parent=None):
        super().__init__(parent)
        self.source = source
        self.infos = sonder(source)
        self.sortie = chemin_optimise(source, largeur, hauteur, fps, interpolation)
        self.partiel = self.sortie.with_suffix(".partiel.mp4")
        self.commande = commande_ffmpeg(source, self.partiel, largeur, hauteur, fps, interpolation, self.infos)
        self.processus = QProcess(self)
        self.processus.readyReadStandardOutput.connect(self._lire)
        self.processus.finished.connect(self._fin)
        self.annulee = False

    def lancer(self):
        if self.sortie.is_file():
            self.terminee.emit(True, str(self.sortie))
            return
        if not self.commande[0]:
            self.terminee.emit(False, "ffmpeg est introuvable")
            return
        self.sortie.parent.mkdir(parents=True, exist_ok=True)
        self.processus.start(self.commande[0], self.commande[1:])

    def annuler(self):
        self.annulee = True
        self.processus.kill()

    def _lire(self):
        for ligne in bytes(self.processus.readAllStandardOutput()).decode(errors="replace").splitlines():
            cle, _, valeur = ligne.partition("=")
            if cle == "out_time_us" and self.infos["duree"] > 0:
                try:
                    self.progression.emit(min(1.0, int(valeur) / 1e6 / self.infos["duree"]))
                except ValueError:
                    pass

    def _fin(self, code, _statut):
        if code == 0 and not self.annulee:
            os.replace(self.partiel, self.sortie)
            self.terminee.emit(True, str(self.sortie))
            return
        self.partiel.unlink(missing_ok=True)
        if self.annulee:
            self.terminee.emit(False, "annulée")
        else:
            erreur = bytes(self.processus.readAllStandardError()).decode(errors="replace").strip()
            self.terminee.emit(False, erreur.splitlines()[-1] if erreur else f"ffmpeg a échoué ({code})")


def miniature(source: str) -> Path | None:
    """Image d'aperçu (480 px de large), mise en cache."""
    try:
        cible = dossier_cache() / "miniatures" / f"{_empreinte(source)}.jpg"
    except OSError:
        return None
    if cible.is_file():
        return cible
    ffmpeg = trouver_outil("ffmpeg")
    if not ffmpeg:
        return None
    cible.parent.mkdir(parents=True, exist_ok=True)
    duree = sonder(source)["duree"]
    debut = ["-ss", f"{min(1.0, duree / 3):.2f}"] if duree > 0.5 else []
    try:
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", *debut, "-i", source, "-frames:v", "1",
                        "-vf", "scale=480:-2", "-y", str(cible)], timeout=30, creationflags=SANS_CONSOLE)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return cible if cible.is_file() else None
