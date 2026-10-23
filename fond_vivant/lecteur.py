"""Le lecteur : une fenêtre « fond d'écran » (fv-bureau, en C) et un mpv par écran.

mpv fait tout le travail d'image : décodage matériel, cadence calée sur la fréquence
de l'écran (display-resample) et interpolation entre les images pour un rendu fluide.
"""
import json
import os
import sys
import tempfile

from PySide6.QtCore import QCoreApplication, QObject, QProcess, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from . import config as cfg
from .systeme import NOM_SERVEUR, WINDOWS, trouver_outil


def journal(*texte):
    print("[fond-vivant]", *texte, file=sys.stderr, flush=True)


def lister_ecrans() -> list[tuple[int, int, int, int, float]]:
    """(x, y, largeur, hauteur, hz) en pixels réels, écran principal en premier."""
    fv = trouver_outil("fv-bureau")
    if fv:
        p = QProcess()
        p.start(fv, ["--ecrans"])
        if p.waitForFinished(3000) and p.exitCode() == 0:
            ecrans = []
            for ligne in bytes(p.readAllStandardOutput()).decode().splitlines():
                try:
                    x, y, l, h, hz = ligne.split()
                    ecrans.append((int(x), int(y), int(l), int(h), float(hz)))
                except ValueError:
                    pass
            if ecrans:
                return ecrans
    # repli : ce que Qt sait des écrans (seulement dans la fenêtre de réglage)
    from PySide6.QtGui import QGuiApplication
    if not isinstance(QCoreApplication.instance(), QGuiApplication):
        return []
    ecrans = []
    principal = QGuiApplication.primaryScreen()
    for s in sorted(QGuiApplication.screens(), key=lambda s: s is not principal):
        g, r = s.geometry(), s.devicePixelRatio()
        ecrans.append((round(g.x() * r), round(g.y() * r), round(g.width() * r), round(g.height() * r),
                       s.refreshRate() or 60.0))
    return ecrans


def proprietes(config: dict, avec_son: bool) -> dict:
    """Réglages mpv qui découlent de la configuration (modifiables à chaud)."""
    cadrage = config.get("cadrage", "remplir")
    fluide = bool(config.get("fluidite", True))
    return {
        "keepaspect": cadrage != "etirer",
        "panscan": 1.0 if cadrage == "remplir" else 0.0,  # 1.0 = rogner pour remplir tout l'écran
        "video-sync": "display-resample" if fluide else "audio",
        "interpolation": fluide,
        "mute": not (avec_son and config.get("son")),
        "volume": int(config.get("volume", 50)),
        "pause": bool(config.get("pause")),
    }


def en_argument(valeur) -> str:
    if isinstance(valeur, bool):
        return "yes" if valeur else "no"
    return str(valeur)


class Ecran(QObject):
    """Un écran : sa fenêtre de fond (fv-bureau) et son mpv."""

    def __init__(self, parent, numero, geometrie, quand_perdu):
        super().__init__(parent)
        self.numero = numero
        self.x, self.y, self.largeur, self.hauteur, self.hz = geometrie
        self.quand_perdu = quand_perdu
        self.fichier = None
        self.arret_volontaire = False
        self.tampon = b""

        if WINDOWS:
            self.nom_ipc = f"fond-vivant-mpv-{os.getpid()}-{numero}"
            self.chemin_ipc = r"\\.\pipe" + "\\" + self.nom_ipc
        else:
            dossier = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
            self.chemin_ipc = self.nom_ipc = os.path.join(dossier, f"fond-vivant-mpv-{numero}.sock")

        self.hote = QProcess(self)
        self.hote.readyReadStandardOutput.connect(self._lire_hote)
        self.hote.finished.connect(self._hote_termine)
        self.mpv = QProcess(self)
        self.mpv.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedErrorChannel)
        self.mpv.finished.connect(self._mpv_termine)
        self.ipc = QLocalSocket(self)
        self.ipc.readyRead.connect(lambda: self.ipc.readAll())  # réponses de mpv ignorées

    def demarrer(self):
        fv = trouver_outil("fv-bureau")
        self.hote.start(fv, [str(self.x), str(self.y), str(self.largeur), str(self.hauteur)])

    def _lire_hote(self):
        self.tampon += bytes(self.hote.readAllStandardOutput())
        if b"\n" not in self.tampon or self.mpv.state() != QProcess.ProcessState.NotRunning:
            return
        ligne = self.tampon.split(b"\n", 1)[0].decode().strip()
        if ligne.startswith("WID "):
            self._lancer_mpv(ligne[4:])

    def _lancer_mpv(self, wid):
        config = cfg.lire()
        self.fichier = cfg.fichier_a_jouer(config)
        options = {
            "wid": wid,
            "config": False,                 # ignore le mpv.conf de l'utilisateur
            "load-scripts": False,
            "idle": True,
            "force-window": True,
            "keep-open": True,
            "loop-file": "inf",
            "image-display-duration": "inf",
            "hwdec": "auto-safe",            # décodage par la carte graphique
            "vo": "gpu",
            "tscale": "oversample",          # interpolation nette, sans flou
            "override-display-fps": f"{self.hz:.3f}",
            "osc": False,
            "osd-level": 0,
            "input-default-bindings": False,
            "input-vo-keyboard": False,
            "input-cursor": False,
            "cursor-autohide": "no",
            "stop-screensaver": False,       # la mise en veille de l'écran doit continuer à marcher
            "audio-display": False,
            "sub-auto": "no",
            "terminal": False,
            "input-ipc-server": self.chemin_ipc,
            **proprietes(config, avec_son=self.numero == 0),
        }
        arguments = [f"--{cle}={en_argument(v)}" for cle, v in options.items()]
        if self.fichier and os.path.isfile(self.fichier):
            arguments.append(self.fichier)
        self.mpv.start(trouver_outil("mpv"), arguments)
        QTimer.singleShot(300, self._connecter_ipc)

    def _connecter_ipc(self, essai=0):
        if self.mpv.state() == QProcess.ProcessState.NotRunning:
            return
        self.ipc.connectToServer(self.nom_ipc)
        if not self.ipc.waitForConnected(200) and essai < 30:
            QTimer.singleShot(200, lambda: self._connecter_ipc(essai + 1))

    def commande(self, *arguments):
        if self.ipc.state() == QLocalSocket.LocalSocketState.ConnectedState:
            self.ipc.write((json.dumps({"command": list(arguments)}) + "\n").encode())
            self.ipc.flush()

    def appliquer(self, config):
        fichier = cfg.fichier_a_jouer(config)
        if fichier != self.fichier:
            self.fichier = fichier
            if fichier and os.path.isfile(fichier):
                self.commande("loadfile", fichier, "replace")
            else:
                self.commande("stop")
        for nom, valeur in proprietes(config, avec_son=self.numero == 0).items():
            self.commande("set_property", nom, valeur)

    def arreter(self):
        self.arret_volontaire = True
        self.commande("quit")
        for processus in (self.mpv, self.hote):
            if processus.state() != QProcess.ProcessState.NotRunning:
                if processus is self.hote:
                    processus.write(b"quitter\n")
                    processus.closeWriteChannel()
                if not processus.waitForFinished(1500):
                    processus.kill()
                    processus.waitForFinished(500)

    def _hote_termine(self, *_):
        if not self.arret_volontaire:
            journal(f"écran {self.numero} : fenêtre de fond perdue, on recrée")
            self.quand_perdu()

    def _mpv_termine(self, *_):
        if not self.arret_volontaire:
            journal(f"écran {self.numero} : mpv s'est arrêté, on recrée")
            self.quand_perdu()


class Lecteur(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.ecrans = []
        self.serveur = QLocalServer(self)
        self.serveur.newConnection.connect(self._nouvelle_connexion)

        self.a_recreer = QTimer(self, singleShot=True, interval=1500)
        self.a_recreer.timeout.connect(self.recreer)
        # écran branché, débranché ou changement de résolution
        self.geometries = []
        self.surveillance = QTimer(self, interval=3000)
        self.surveillance.timeout.connect(self._verifier_ecrans)

    def demarrer(self) -> bool:
        if not trouver_outil("mpv"):
            journal("mpv est introuvable : installe-le (Linux : sudo apt install mpv)")
            return False
        if not trouver_outil("fv-bureau"):
            journal("fv-bureau est introuvable : compile-le (make -C natif)")
            return False
        if not self.serveur.listen(NOM_SERVEUR):
            # serveur orphelin d'un lecteur planté, ou lecteur déjà lancé
            socket = QLocalSocket()
            socket.connectToServer(NOM_SERVEUR)
            if socket.waitForConnected(300):
                journal("le lecteur tourne déjà")
                return False
            QLocalServer.removeServer(NOM_SERVEUR)
            if not self.serveur.listen(NOM_SERVEUR):
                journal("impossible d'ouvrir le canal de commande :", self.serveur.errorString())
                return False
        self.recreer()
        self.surveillance.start()
        return True

    def _verifier_ecrans(self):
        ecrans = lister_ecrans()
        if ecrans and [e[:4] for e in ecrans] != [g[:4] for g in self.geometries]:
            journal("les écrans ont changé")
            self.a_recreer.start()

    def recreer(self):
        for e in self.ecrans:
            e.arreter()
        self.geometries = lister_ecrans()
        self.ecrans = [Ecran(self, i, g, self.a_recreer.start) for i, g in enumerate(self.geometries)]
        for e in self.ecrans:
            e.demarrer()
        journal(f"{len(self.ecrans)} écran(s) :",
                ", ".join(f"{e.largeur}x{e.hauteur}@{e.hz:.2f}Hz" for e in self.ecrans))

    def recharger(self):
        config = cfg.lire()
        for e in self.ecrans:
            e.appliquer(config)

    def arreter(self):
        self.a_recreer.stop()
        self.surveillance.stop()
        for e in self.ecrans:
            e.arreter()
        self.ecrans = []
        self.serveur.close()
        self.app.quit()

    def _nouvelle_connexion(self):
        socket = self.serveur.nextPendingConnection()
        socket.readyRead.connect(lambda: self._commande(socket))

    def _commande(self, socket):
        while socket.canReadLine():
            commande = bytes(socket.readLine()).decode().strip()
            if commande == "recharger":
                self.recharger()
                socket.write(b"ok\n")
            elif commande == "arreter":
                socket.write(b"ok\n")
                socket.flush()
                QTimer.singleShot(0, self.arreter)
            elif commande == "etat":
                socket.write(f"actif {len(self.ecrans)}\n".encode())
            socket.flush()


def principal() -> int:
    app = QCoreApplication(sys.argv[:1])
    lecteur = Lecteur(app)
    if not lecteur.demarrer():
        return 1
    if not WINDOWS:
        import signal
        signal.signal(signal.SIGTERM, lambda *_: QTimer.singleShot(0, lecteur.arreter))
        signal.signal(signal.SIGINT, lambda *_: QTimer.singleShot(0, lecteur.arreter))
        # laisse Python traiter les signaux pendant la boucle Qt
        minuteur = QTimer(interval=500)
        minuteur.timeout.connect(lambda: None)
        minuteur.start()
    return app.exec()
