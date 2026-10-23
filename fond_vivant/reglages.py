"""La fenêtre de réglage : bibliothèque de fonds, aperçu, optimisation et réglages."""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImageReader, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QProgressBar, QPushButton, QSlider, QVBoxLayout, QWidget)

from . import __version__, canal
from . import config as cfg
from .lecteur import lister_ecrans
from .optimiseur import Optimisation, miniature, sonder
from .systeme import (EXTENSIONS_IMAGE, EXTENSIONS_VIDEO, WINDOWS, autostart_actif, commande_application,
                      lancer_detache, regler_autostart, trouver_outil, type_fichier)

TAILLE_ICONE = QSize(208, 117)

STYLE = """
QWidget { font-size: 10pt; }
QMainWindow, #fond { background: #121218; }
#panneau { background: #1b1b24; border-left: 1px solid #2a2a36; }
QLabel#titre { font-size: 15pt; font-weight: 600; }
QLabel#sous-titre { color: #9a9ab0; }
QLabel#section { color: #9a9ab0; font-size: 9pt; font-weight: 600; letter-spacing: 1px; margin-top: 8px; }
QLabel#apercu { background: #0b0b10; border-radius: 10px; }
QLabel#vide { color: #6c6c80; font-size: 11pt; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { color: #d8d8e6; border-radius: 10px; padding: 6px; margin: 4px; }
QListWidget::item:hover { background: #1f1f2b; }
QListWidget::item:selected { background: #2a2540; color: white; }
QPushButton { background: #262633; color: #e8e8f2; border: 1px solid #33334a; border-radius: 8px;
              padding: 7px 14px; }
QPushButton:hover { background: #2f2f40; }
QPushButton:disabled { color: #5c5c70; background: #1d1d27; }
QPushButton#principal { background: #7c5cff; border: none; color: white; font-weight: 600; padding: 9px 14px; }
QPushButton#principal:hover { background: #8d71ff; }
QPushButton#principal:disabled { background: #3a3360; color: #9a93c0; }
QPushButton#danger { color: #ff8a8a; }
QComboBox { background: #262633; border: 1px solid #33334a; border-radius: 8px; padding: 6px 10px; }
QProgressBar { background: #262633; border: none; border-radius: 4px; height: 8px; text-align: center; }
QProgressBar::chunk { background: #7c5cff; border-radius: 4px; }
QSlider::groove:horizontal { height: 4px; background: #33334a; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #7c5cff; border-radius: 2px; }
QSlider::handle:horizontal { background: white; width: 14px; margin: -5px 0; border-radius: 7px; }
#bandeau { background: #3b2a12; color: #ffcf8a; border-radius: 8px; padding: 8px; }
"""


def palette_sombre(app):
    app.setStyle("Fusion")
    p = QPalette()
    for role, couleur in ((QPalette.Window, "#121218"), (QPalette.WindowText, "#e8e8f2"),
                          (QPalette.Base, "#1b1b24"), (QPalette.AlternateBase, "#22222e"),
                          (QPalette.Text, "#e8e8f2"), (QPalette.Button, "#262633"),
                          (QPalette.ButtonText, "#e8e8f2"), (QPalette.Highlight, "#7c5cff"),
                          (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, "#262633"),
                          (QPalette.ToolTipText, "#e8e8f2"), (QPalette.PlaceholderText, "#6c6c80")):
        p.setColor(role, QColor(couleur))
    app.setPalette(p)
    app.setStyleSheet(STYLE)


def duree_lisible(secondes: float) -> str:
    s = int(round(secondes))
    return f"{s // 60}:{s % 60:02d}"


class Messager(QObject):
    """Ramène les résultats des fils de travail dans le fil de l'interface."""
    miniature_prete = Signal(str, str)


class Bibliotheque(QListWidget):
    fichiers_deposes = Signal(list)

    def __init__(self):
        super().__init__()
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(TAILLE_ICONE)
        self.setGridSize(QSize(TAILLE_ICONE.width() + 24, TAILLE_ICONE.height() + 44))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setAcceptDrops(True)
        self.setUniformItemSizes(True)

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        chemins = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        self.fichiers_deposes.emit(chemins)
        ev.acceptProposedAction()


class FenetreReglages(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Fond Vivant")
        self.resize(1080, 680)
        self.config = cfg.lire()
        self.optimisation = None
        self.travail = ThreadPoolExecutor(max_workers=2)
        self.messager = Messager()
        self.messager.miniature_prete.connect(self._miniature_prete)
        self.icone_attente = self._icone_vide()

        fond = QWidget(objectName="fond")
        disposition = QHBoxLayout(fond)
        disposition.setContentsMargins(0, 0, 0, 0)
        disposition.setSpacing(0)
        disposition.addWidget(self._zone_bibliotheque(), 1)
        disposition.addWidget(self._panneau())
        self.setCentralWidget(fond)

        self._remplir_bibliotheque()
        self._maj_etat()
        self.minuteur = QTimer(self, interval=2000)
        self.minuteur.timeout.connect(self._maj_etat)
        self.minuteur.start()

    # --- construction ----------------------------------------------------------

    def _zone_bibliotheque(self):
        zone = QWidget()
        v = QVBoxLayout(zone)
        v.setContentsMargins(24, 20, 16, 16)
        entete = QHBoxLayout()
        titres = QVBoxLayout()
        titres.addWidget(QLabel("Ma bibliothèque", objectName="titre"))
        titres.addWidget(QLabel("Vidéos et photos · glisse tes fichiers ici", objectName="sous-titre"))
        entete.addLayout(titres, 1)
        ajouter = QPushButton("＋  Ajouter", objectName="principal")
        ajouter.clicked.connect(self._choisir_fichiers)
        entete.addWidget(ajouter, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(entete)

        if not WINDOWS and os.environ.get("XDG_SESSION_TYPE") == "wayland":
            v.addWidget(QLabel("Session Wayland : choisis « Ubuntu sur Xorg » sur l'écran de connexion "
                               "pour que le fond animé s'affiche derrière le bureau.",
                               objectName="bandeau", wordWrap=True))
        manquants = [o for o in ("mpv", "fv-bureau", "ffmpeg") if not trouver_outil(o)]
        if manquants:
            v.addWidget(QLabel("Outils introuvables : " + ", ".join(manquants)
                               + ". Voir le README pour les installer.", objectName="bandeau", wordWrap=True))

        self.liste = Bibliotheque()
        self.liste.currentItemChanged.connect(lambda *_: self._maj_selection())
        self.liste.itemDoubleClicked.connect(lambda *_: self._appliquer())
        self.liste.fichiers_deposes.connect(self._ajouter)
        self.vide = QLabel("Ta bibliothèque est vide.\nAjoute une vidéo ou une photo pour commencer.",
                           objectName="vide", alignment=Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.liste, 1)
        v.addWidget(self.vide, 1)
        return zone

    def _panneau(self):
        panneau = QWidget(objectName="panneau")
        panneau.setFixedWidth(340)
        v = QVBoxLayout(panneau)
        v.setContentsMargins(20, 20, 20, 16)
        v.setSpacing(8)

        self.apercu = QLabel(objectName="apercu", alignment=Qt.AlignmentFlag.AlignCenter)
        self.apercu.setFixedSize(300, 169)
        v.addWidget(self.apercu)
        self.nom = QLabel(wordWrap=True)
        self.nom.setStyleSheet("font-weight: 600; font-size: 11pt;")
        v.addWidget(self.nom)
        self.infos = QLabel(objectName="sous-titre", wordWrap=True)
        v.addWidget(self.infos)

        self.bouton_appliquer = QPushButton("Mettre en fond d'écran", objectName="principal")
        self.bouton_appliquer.clicked.connect(self._appliquer)
        v.addWidget(self.bouton_appliquer)

        ligne = QHBoxLayout()
        self.bouton_optimiser = QPushButton("Optimiser pour mon écran")
        self.bouton_optimiser.setToolTip("Recadre la vidéo à la taille exacte de ton écran et l'encode "
                                         "pour une lecture parfaitement fluide.")
        self.bouton_optimiser.clicked.connect(self._optimiser)
        ligne.addWidget(self.bouton_optimiser, 1)
        self.bouton_retirer = QPushButton("Retirer", objectName="danger")
        self.bouton_retirer.clicked.connect(self._retirer)
        ligne.addWidget(self.bouton_retirer)
        v.addLayout(ligne)
        self.case_interpolation = QCheckBox("Créer les images manquantes (60 i/s réels)")
        self.case_interpolation.setToolTip("Interpolation de mouvement : une vidéo à 24 ou 30 i/s devient "
                                           "une vraie vidéo à 60 i/s. Bien plus lent à préparer.")
        self.case_interpolation.setChecked(True)
        v.addWidget(self.case_interpolation)
        ligne = QHBoxLayout()
        self.barre = QProgressBar(textVisible=False, maximum=1000)
        ligne.addWidget(self.barre, 1)
        self.bouton_annuler = QPushButton("Annuler")
        self.bouton_annuler.clicked.connect(lambda: self.optimisation and self.optimisation.annuler())
        ligne.addWidget(self.bouton_annuler)
        v.addLayout(ligne)
        self.texte_optimisation = QLabel(objectName="sous-titre")
        v.addWidget(self.texte_optimisation)
        self._montrer_progression(False)

        trait = QFrame(frameShape=QFrame.Shape.HLine)
        trait.setStyleSheet("color: #2a2a36;")
        v.addWidget(trait)
        v.addWidget(QLabel("RÉGLAGES", objectName="section"))

        v.addWidget(QLabel("Cadrage"))
        self.cadrage = QComboBox()
        self.cles_cadrage = list(cfg.CADRAGES)
        self.cadrage.addItems([cfg.CADRAGES[c] for c in self.cles_cadrage])
        if self.config["cadrage"] in self.cles_cadrage:
            self.cadrage.setCurrentIndex(self.cles_cadrage.index(self.config["cadrage"]))
        self.cadrage.currentIndexChanged.connect(self._reglage_modifie)
        v.addWidget(self.cadrage)

        self.fluidite = QCheckBox("Fluidité maximale (calée sur l'écran)", checked=self.config["fluidite"])
        self.fluidite.setToolTip("mpv cale la lecture sur la fréquence de l'écran et lisse les images.")
        self.fluidite.toggled.connect(self._reglage_modifie)
        v.addWidget(self.fluidite)

        ligne = QHBoxLayout()
        self.son = QCheckBox("Son", checked=self.config["son"])
        self.son.toggled.connect(self._reglage_modifie)
        ligne.addWidget(self.son)
        self.volume = QSlider(Qt.Orientation.Horizontal, minimum=0, maximum=100, value=self.config["volume"])
        self.volume.setEnabled(self.config["son"])
        self.volume.valueChanged.connect(self._reglage_modifie)
        ligne.addWidget(self.volume, 1)
        v.addLayout(ligne)

        self.autostart = QCheckBox("Lancer à l'ouverture de session", checked=autostart_actif())
        self.autostart.toggled.connect(regler_autostart)
        v.addWidget(self.autostart)

        v.addStretch(1)
        ligne = QHBoxLayout()
        self.bouton_pause = QPushButton()
        self.bouton_pause.clicked.connect(self._basculer_pause)
        ligne.addWidget(self.bouton_pause, 1)
        self.bouton_arreter = QPushButton("Arrêter le fond", objectName="danger")
        self.bouton_arreter.clicked.connect(self._arreter)
        ligne.addWidget(self.bouton_arreter, 1)
        v.addLayout(ligne)
        self.etat = QLabel(objectName="sous-titre", wordWrap=True)
        v.addWidget(self.etat)
        return panneau

    def _icone_vide(self):
        pixmap = QPixmap(TAILLE_ICONE)
        pixmap.fill(QColor("#1f1f2b"))
        return QIcon(pixmap)

    # --- bibliothèque ------------------------------------------------------------

    def _remplir_bibliotheque(self):
        self.liste.clear()
        for e in self.config["bibliotheque"]:
            self._ajouter_element(e)
        actuel = self._element(self.config["actuel"])
        self.liste.setCurrentItem(actuel or self.liste.item(0))
        self._maj_vide()

    def _ajouter_element(self, entree):
        nom = Path(entree["chemin"]).name
        element = QListWidgetItem(self.icone_attente, nom)
        element.setData(Qt.ItemDataRole.UserRole, entree["chemin"])
        element.setToolTip(entree["chemin"])
        self.liste.addItem(element)
        self.travail.submit(self._fabriquer_miniature, entree["chemin"])
        return element

    def _fabriquer_miniature(self, chemin):
        image = miniature(chemin)
        self.messager.miniature_prete.emit(chemin, str(image) if image else "")

    def _miniature_prete(self, chemin, image):
        element = self._element(chemin)
        if not element:
            return
        pixmap = QPixmap(image) if image else QPixmap(chemin)
        if pixmap.isNull():
            return
        element.setData(Qt.ItemDataRole.UserRole + 1, pixmap)
        element.setIcon(QIcon(self._recadrer(pixmap, TAILLE_ICONE, self._badge(chemin))))
        if element is self.liste.currentItem():
            self._maj_selection()

    def _badge(self, chemin):
        e = cfg.entree(self.config, chemin)
        if e and e["type"] == "image":
            return "PHOTO"
        if e and e.get("optimise") and os.path.isfile(e["optimise"]):
            return "OPTIMISÉE"
        return None

    def _recadrer(self, pixmap, taille, badge=None):
        """Remplit le cadre comme le fera le fond d'écran, coins arrondis, petit badge."""
        rendu = pixmap.scaled(taille, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                              Qt.TransformationMode.SmoothTransformation)
        x = (rendu.width() - taille.width()) // 2
        y = (rendu.height() - taille.height()) // 2
        rendu = rendu.copy(x, y, taille.width(), taille.height())
        if badge:
            peintre = QPainter(rendu)
            peintre.setRenderHint(QPainter.RenderHint.Antialiasing)
            police = peintre.font()
            police.setPointSize(7)
            police.setBold(True)
            peintre.setFont(police)
            largeur = peintre.fontMetrics().horizontalAdvance(badge) + 12
            peintre.setPen(Qt.PenStyle.NoPen)
            peintre.setBrush(QColor(124, 92, 255, 220) if badge == "OPTIMISÉE" else QColor(0, 0, 0, 170))
            peintre.drawRoundedRect(6, 6, largeur, 16, 5, 5)
            peintre.setPen(QColor("white"))
            peintre.drawText(6, 6, largeur, 16, Qt.AlignmentFlag.AlignCenter, badge)
            peintre.end()
        return rendu

    def _element(self, chemin):
        for i in range(self.liste.count()):
            if self.liste.item(i).data(Qt.ItemDataRole.UserRole) == chemin:
                return self.liste.item(i)
        return None

    def _selection(self):
        element = self.liste.currentItem()
        return element.data(Qt.ItemDataRole.UserRole) if element else None

    def _choisir_fichiers(self):
        motifs = " ".join("*" + e for e in sorted(EXTENSIONS_VIDEO | EXTENSIONS_IMAGE))
        chemins, _ = QFileDialog.getOpenFileNames(self, "Ajouter des fonds d'écran", str(Path.home()),
                                                  f"Vidéos et photos ({motifs});;Tous les fichiers (*)")
        self._ajouter(chemins)

    def _ajouter(self, chemins):
        dernier = None
        refuses = []
        for chemin in chemins:
            chemin = os.path.abspath(chemin)
            type_ = type_fichier(chemin)
            if not type_ or not os.path.isfile(chemin):
                refuses.append(Path(chemin).name)
                continue
            if not cfg.entree(self.config, chemin):
                entree = {"chemin": chemin, "type": type_, "optimise": ""}
                self.config["bibliotheque"].append(entree)
                self._ajouter_element(entree)
            dernier = chemin
        cfg.ecrire(self.config)
        if dernier:
            self.liste.setCurrentItem(self._element(dernier))
        if refuses:
            QMessageBox.warning(self, "Fichiers ignorés", "Ce ne sont ni des vidéos ni des photos :\n"
                                + "\n".join(refuses))
        self._maj_vide()

    def _retirer(self):
        chemin = self._selection()
        if not chemin:
            return
        e = cfg.entree(self.config, chemin)
        if e.get("optimise"):
            Path(e["optimise"]).unlink(missing_ok=True)
        self.config["bibliotheque"].remove(e)
        if self.config["actuel"] == chemin:
            self.config["actuel"] = ""
        cfg.ecrire(self.config)
        self.liste.takeItem(self.liste.row(self.liste.currentItem()))
        canal.envoyer("recharger")
        self._maj_vide()
        self._maj_selection()

    def _maj_vide(self):
        vide = self.liste.count() == 0
        self.liste.setVisible(not vide)
        self.vide.setVisible(vide)

    # --- aperçu ------------------------------------------------------------------

    def _maj_selection(self):
        chemin = self._selection()
        e = cfg.entree(self.config, chemin) if chemin else None
        for bouton in (self.bouton_appliquer, self.bouton_retirer):
            bouton.setEnabled(e is not None)
        self.bouton_optimiser.setEnabled(e is not None and e["type"] == "video" and self.optimisation is None)
        self.case_interpolation.setVisible(e is not None and e["type"] == "video")
        if not e:
            self.apercu.clear()
            self.nom.setText("")
            self.infos.setText("Choisis un fond dans ta bibliothèque.")
            return
        element = self.liste.currentItem()
        pixmap = element.data(Qt.ItemDataRole.UserRole + 1)
        if pixmap:
            self.apercu.setPixmap(self._recadrer(pixmap, self.apercu.size()))
        else:
            self.apercu.clear()
        self.nom.setText(Path(chemin).name)
        self.infos.setText(self._description(e))
        self.bouton_appliquer.setText("Fond d'écran actuel ✓" if chemin == self.config["actuel"]
                                      and canal.lecteur_actif() else "Mettre en fond d'écran")

    def _description(self, e):
        if e["type"] == "image":
            taille = QImageReader(e["chemin"]).size()
            return f"Photo · {taille.width()}×{taille.height()}" if taille.isValid() else "Photo"
        infos = sonder(e["chemin"])
        morceaux = ["Vidéo"]
        if infos["largeur"]:
            morceaux.append(f"{infos['largeur']}×{infos['hauteur']}")
        if infos["fps"]:
            morceaux.append(f"{infos['fps']:.0f} i/s")
        if infos["duree"]:
            morceaux.append(duree_lisible(infos["duree"]))
        texte = " · ".join(morceaux)
        if e.get("optimise") and os.path.isfile(e["optimise"]):
            opt = sonder(e["optimise"])
            texte += f"\nVersion optimisée : {opt['largeur']}×{opt['hauteur']} · {opt['fps']:.0f} i/s"
        return texte

    # --- actions -----------------------------------------------------------------

    def _appliquer(self):
        chemin = self._selection()
        if not chemin:
            return
        self.config["actuel"] = chemin
        self.config["pause"] = False
        cfg.ecrire(self.config)
        if canal.envoyer("recharger") is None:
            lancer_detache(commande_application("--lecteur"))
        QTimer.singleShot(800, self._maj_etat)

    def _reglage_modifie(self, *_):
        self.config["cadrage"] = self.cles_cadrage[self.cadrage.currentIndex()]
        self.config["fluidite"] = self.fluidite.isChecked()
        self.config["son"] = self.son.isChecked()
        self.config["volume"] = self.volume.value()
        self.volume.setEnabled(self.config["son"])
        cfg.ecrire(self.config)
        canal.envoyer("recharger")

    def _basculer_pause(self):
        self.config["pause"] = not self.config["pause"]
        cfg.ecrire(self.config)
        canal.envoyer("recharger")
        self._maj_etat()

    def _arreter(self):
        canal.envoyer("arreter")
        QTimer.singleShot(500, self._maj_etat)

    def _maj_etat(self):
        actif = canal.lecteur_actif()
        self.bouton_pause.setEnabled(actif)
        self.bouton_arreter.setEnabled(actif)
        self.bouton_pause.setText("Reprendre" if self.config["pause"] else "Pause")
        if not actif:
            self.etat.setText("Le fond animé est arrêté.")
        elif self.config["actuel"]:
            pause = " (en pause)" if self.config["pause"] else ""
            self.etat.setText(f"En fond d'écran{pause} : {Path(self.config['actuel']).name}")
        else:
            self.etat.setText("Le lecteur tourne, aucun fond choisi.")
        if self.liste.currentItem() and self.optimisation is None:
            chemin = self._selection()
            self.bouton_appliquer.setText("Fond d'écran actuel ✓" if actif and chemin == self.config["actuel"]
                                          else "Mettre en fond d'écran")

    # --- optimisation --------------------------------------------------------------

    def _optimiser(self):
        chemin = self._selection()
        if not chemin or self.optimisation:
            return
        ecrans = lister_ecrans()
        x, y, largeur, hauteur, hz = max(ecrans, key=lambda e: e[2] * e[3]) if ecrans else (0, 0, 1920, 1080, 60)
        fps = max(24, round(hz))
        self.optimisation = Optimisation(chemin, largeur, hauteur, fps, self.case_interpolation.isChecked(), self)
        self.optimisation.progression.connect(lambda p: self.barre.setValue(int(p * 1000)))
        self.optimisation.terminee.connect(lambda ok, r: self._optimisation_finie(chemin, ok, r))
        self.texte_optimisation.setText(f"Préparation en {largeur}×{hauteur} à {fps} i/s…")
        self.barre.setValue(0)
        self._montrer_progression(True)
        self.bouton_optimiser.setEnabled(False)
        self.optimisation.lancer()

    def _optimisation_finie(self, chemin, reussi, resultat):
        self.optimisation = None
        self._montrer_progression(False)
        e = cfg.entree(self.config, chemin)
        if reussi and e:
            e["optimise"] = resultat
            cfg.ecrire(self.config)
            element = self._element(chemin)
            pixmap = element.data(Qt.ItemDataRole.UserRole + 1) if element else None
            if pixmap:
                element.setIcon(QIcon(self._recadrer(pixmap, TAILLE_ICONE, self._badge(chemin))))
            if self.config["actuel"] == chemin:
                canal.envoyer("recharger")
            self.etat.setText("Vidéo optimisée pour ton écran.")
        elif resultat != "annulée":
            QMessageBox.warning(self, "Optimisation impossible", resultat)
        self._maj_selection()

    def _montrer_progression(self, visible):
        for w in (self.barre, self.bouton_annuler, self.texte_optimisation):
            w.setVisible(visible)

    def closeEvent(self, ev):
        if self.optimisation:
            self.optimisation.annuler()
        self.travail.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(ev)


def principal() -> int:
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Fond Vivant")
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("fond-vivant")
    palette_sombre(app)
    fenetre = FenetreReglages()
    fenetre.show()
    return app.exec()
