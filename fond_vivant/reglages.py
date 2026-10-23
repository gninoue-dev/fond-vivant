"""La fenêtre de Fond Vivant, pensée pour être simple : un clic sur une image et c'est fait."""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QProgressBar, QPushButton, QSlider, QVBoxLayout, QWidget)

from . import __version__, canal
from . import config as cfg
from .lecteur import lister_ecrans
from .optimiseur import Optimisation, miniature, sonder
from .systeme import (EXTENSIONS_IMAGE, EXTENSIONS_VIDEO, WINDOWS, autostart_actif, commande_application,
                      lancer_detache, regler_autostart, trouver_outil, type_fichier)

TAILLE_ICONE = QSize(220, 124)
AJOUTER = "__ajouter__"
ROLE_CHEMIN = Qt.ItemDataRole.UserRole
ROLE_IMAGE = Qt.ItemDataRole.UserRole + 1

INTERVALLES = [(15, "15 secondes"), (30, "30 secondes"), (60, "1 minute"), (300, "5 minutes"), (600, "10 minutes"),
               (900, "15 minutes"), (1800, "30 minutes"), (3600, "1 heure"), (10800, "3 heures"),
               (86400, "1 jour")]

VIOLET = "#7c5cff"

STYLE = f"""
QWidget {{ font-size: 10.5pt; }}
QMainWindow, #fond {{ background: #121218; }}
QLabel#titre {{ font-size: 18pt; font-weight: 700; }}
QLabel#etape {{ font-size: 12pt; font-weight: 600; margin-top: 6px; }}
QLabel#aide {{ color: #9a9ab0; }}
QLabel#etat-actif {{ color: #7ee2a8; font-weight: 600; }}
QLabel#etat-arret {{ color: #9a9ab0; font-weight: 600; }}
QPushButton {{ background: #262633; color: #e8e8f2; border: 1px solid #33334a; border-radius: 10px;
              padding: 8px 16px; }}
QPushButton:hover {{ background: #2f2f40; }}
QPushButton:disabled {{ color: #5c5c70; background: #1d1d27; }}
QPushButton#principal {{ background: {VIOLET}; border: none; color: white; font-weight: 600; }}
QPushButton#principal:hover {{ background: #8d71ff; }}
QPushButton#carte {{ text-align: left; padding: 14px 18px; border-radius: 14px; border: 2px solid #2a2a36;
                    background: #1b1b24; }}
QPushButton#carte:checked {{ border: 2px solid {VIOLET}; background: #221d38; }}
QPushButton#lien {{ background: transparent; border: none; color: #b9a8ff; padding: 4px 0; text-align: left; }}
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ color: #d8d8e6; border-radius: 12px; padding: 6px; margin: 4px; }}
QListWidget::item:hover {{ background: #1f1f2b; }}
QListWidget::item:selected {{ background: transparent; }}
QListWidget::indicator {{ width: 0; height: 0; }}
QComboBox {{ background: #262633; border: 1px solid #33334a; border-radius: 8px; padding: 6px 10px; }}
QProgressBar {{ background: #262633; border: none; border-radius: 4px; max-height: 8px; }}
QProgressBar::chunk {{ background: {VIOLET}; border-radius: 4px; }}
QSlider::groove:horizontal {{ height: 4px; background: #33334a; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {VIOLET}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 14px; margin: -5px 0; border-radius: 7px; }}
QSlider::sub-page:horizontal:disabled {{ background: #44445a; }}
QSlider::handle:horizontal:disabled {{ background: #6c6c80; }}
#options {{ background: #1b1b24; border-radius: 14px; }}
#bandeau {{ background: #3b2a12; color: #ffcf8a; border-radius: 10px; padding: 10px; }}
#barre-bas {{ background: #1b1b24; border-top: 1px solid #2a2a36; }}
"""


def palette_sombre(app):
    app.setStyle("Fusion")
    p = QPalette()
    for role, couleur in ((QPalette.Window, "#121218"), (QPalette.WindowText, "#e8e8f2"),
                          (QPalette.Base, "#1b1b24"), (QPalette.AlternateBase, "#22222e"),
                          (QPalette.Text, "#e8e8f2"), (QPalette.Button, "#262633"),
                          (QPalette.ButtonText, "#e8e8f2"), (QPalette.Highlight, VIOLET),
                          (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, "#262633"),
                          (QPalette.ToolTipText, "#e8e8f2"), (QPalette.PlaceholderText, "#6c6c80")):
        p.setColor(role, QColor(couleur))
    app.setPalette(p)
    app.setStyleSheet(STYLE)


class Messager(QObject):
    """Ramène les miniatures fabriquées en arrière-plan dans le fil de l'interface."""
    miniature_prete = Signal(str, str)


class Grille(QListWidget):
    fichiers_deposes = Signal(list)

    def __init__(self):
        super().__init__()
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(TAILLE_ICONE)
        self.setGridSize(QSize(TAILLE_ICONE.width() + 20, TAILLE_ICONE.height() + 46))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setUniformItemSizes(True)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        self.fichiers_deposes.emit([u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()])
        ev.acceptProposedAction()


def carte(titre, texte):
    bouton = QPushButton(f"{titre}\n{texte}", objectName="carte", checkable=True)
    bouton.setMinimumHeight(74)
    bouton.setCursor(Qt.CursorShape.PointingHandCursor)
    return bouton


class FenetreReglages(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Fond Vivant")
        self.resize(1040, 720)
        self.config = cfg.lire()
        self.optimisation = None
        self.travail = ThreadPoolExecutor(max_workers=2)
        self.messager = Messager()
        self.messager.miniature_prete.connect(self._miniature_prete)

        fond = QWidget(objectName="fond")
        v = QVBoxLayout(fond)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        contenu = QWidget()
        c = QVBoxLayout(contenu)
        c.setContentsMargins(28, 22, 28, 12)
        c.setSpacing(10)
        self._entete(c)
        self._bandeaux(c)
        self._etape_mode(c)
        self._etape_choix(c)
        self._options(c)
        v.addWidget(contenu, 1)
        v.addWidget(self._barre_bas())
        self.setCentralWidget(fond)

        self._remplir_grille()
        self._maj_mode()
        self._maj_etat()
        self.minuteur = QTimer(self, interval=2000)
        self.minuteur.timeout.connect(self._maj_etat)
        self.minuteur.start()

    # --- construction --------------------------------------------------------------

    def _entete(self, c):
        ligne = QHBoxLayout()
        titres = QVBoxLayout()
        titres.setSpacing(2)
        titres.addWidget(QLabel("Fond Vivant", objectName="titre"))
        self.etat = QLabel()
        titres.addWidget(self.etat)
        ligne.addLayout(titres, 1)
        self.bouton_pause = QPushButton()
        self.bouton_pause.clicked.connect(self._basculer_pause)
        ligne.addWidget(self.bouton_pause)
        self.bouton_marche = QPushButton(objectName="principal")
        self.bouton_marche.clicked.connect(self._marche_arret)
        ligne.addWidget(self.bouton_marche)
        c.addLayout(ligne)

    def _bandeaux(self, c):
        if not WINDOWS and os.environ.get("XDG_SESSION_TYPE") == "wayland":
            c.addWidget(QLabel("Tu es en session Wayland : déconnecte-toi et choisis « Ubuntu sur Xorg » "
                               "(roue en bas à droite de l'écran de connexion) pour que le fond animé s'affiche.",
                               objectName="bandeau", wordWrap=True))
        manquants = [o for o in ("mpv", "fv-bureau", "ffmpeg") if not trouver_outil(o)]
        if manquants:
            c.addWidget(QLabel("Il manque : " + ", ".join(manquants) + ". Le README explique comment les installer.",
                               objectName="bandeau", wordWrap=True))

    def _etape_mode(self, c):
        c.addWidget(QLabel("1.  Comment veux-tu ton fond d'écran ?", objectName="etape"))
        ligne = QHBoxLayout()
        ligne.setSpacing(12)
        self.carte_unique = carte("🖼   Un seul fond", "Une vidéo ou une photo, toujours la même")
        self.carte_diapo = carte("🔁   Diaporama", "Tes photos changent toutes seules")
        self.carte_unique.clicked.connect(lambda: self._choisir_mode("unique"))
        self.carte_diapo.clicked.connect(lambda: self._choisir_mode("diaporama"))
        ligne.addWidget(self.carte_unique)
        ligne.addWidget(self.carte_diapo)
        c.addLayout(ligne)

    def _etape_choix(self, c):
        ligne = QHBoxLayout()
        self.titre_choix = QLabel(objectName="etape")
        ligne.addWidget(self.titre_choix, 1)
        self.bouton_dossier = QPushButton("📁  Ajouter un dossier")
        self.bouton_dossier.clicked.connect(self._choisir_dossier)
        ligne.addWidget(self.bouton_dossier)
        c.addLayout(ligne)
        self.aide_choix = QLabel(objectName="aide")
        c.addWidget(self.aide_choix)

        # réglages du diaporama, visibles seulement dans ce mode
        self.zone_diapo = QWidget()
        d = QHBoxLayout(self.zone_diapo)
        d.setContentsMargins(0, 0, 0, 0)
        d.addWidget(QLabel("Changer d'image toutes les"))
        self.intervalle = QComboBox()
        for secondes, texte in INTERVALLES:
            self.intervalle.addItem(texte, secondes)
        index = self.intervalle.findData(self.config["intervalle"])
        self.intervalle.setCurrentIndex(index if index >= 0 else 3)
        self.intervalle.currentIndexChanged.connect(self._diapo_modifie)
        d.addWidget(self.intervalle)
        self.aleatoire = QCheckBox("Ordre au hasard", checked=self.config["aleatoire"])
        self.aleatoire.toggled.connect(self._diapo_modifie)
        d.addWidget(self.aleatoire)
        d.addStretch(1)
        self.bouton_tout = QPushButton("Tout cocher")
        self.bouton_tout.clicked.connect(self._tout_cocher)
        d.addWidget(self.bouton_tout)
        self.bouton_suivant = QPushButton("Image suivante  ⏭")
        self.bouton_suivant.clicked.connect(lambda: canal.envoyer("suivant"))
        d.addWidget(self.bouton_suivant)
        c.addWidget(self.zone_diapo)

        self.grille = Grille()
        self.grille.itemClicked.connect(self._clic)
        self.grille.itemChanged.connect(self._coche_modifiee)
        self.grille.fichiers_deposes.connect(self._ajouter)
        self.grille.customContextMenuRequested.connect(self._menu)
        c.addWidget(self.grille, 1)

    def _options(self, c):
        self.bouton_options = QPushButton("⚙   Plus d'options", objectName="lien")
        self.bouton_options.setCheckable(True)
        self.bouton_options.toggled.connect(lambda ouvert: self.zone_options.setVisible(ouvert))
        c.addWidget(self.bouton_options)

        self.zone_options = QWidget(objectName="options")
        o = QVBoxLayout(self.zone_options)
        o.setContentsMargins(18, 14, 18, 14)
        ligne = QHBoxLayout()
        ligne.addWidget(QLabel("Taille de l'image :"))
        self.cadrage = QComboBox()
        self.cles_cadrage = list(cfg.CADRAGES)
        self.cadrage.addItems([cfg.CADRAGES[k] for k in self.cles_cadrage])
        if self.config["cadrage"] in self.cles_cadrage:
            self.cadrage.setCurrentIndex(self.cles_cadrage.index(self.config["cadrage"]))
        self.cadrage.currentIndexChanged.connect(self._reglage_modifie)
        ligne.addWidget(self.cadrage)
        ligne.addSpacing(20)
        self.son = QCheckBox("Son des vidéos", checked=self.config["son"])
        self.son.toggled.connect(self._reglage_modifie)
        ligne.addWidget(self.son)
        self.volume = QSlider(Qt.Orientation.Horizontal, minimum=0, maximum=100, value=self.config["volume"])
        self.volume.setFixedWidth(140)
        self.volume.setEnabled(self.config["son"])
        self.volume.valueChanged.connect(self._reglage_modifie)
        ligne.addWidget(self.volume)
        ligne.addStretch(1)
        o.addLayout(ligne)
        ligne = QHBoxLayout()
        self.fluidite = QCheckBox("Lecture ultra fluide (calée sur ton écran)", checked=self.config["fluidite"])
        self.fluidite.toggled.connect(self._reglage_modifie)
        ligne.addWidget(self.fluidite)
        ligne.addSpacing(20)
        self.autostart = QCheckBox("Démarrer avec l'ordinateur", checked=autostart_actif())
        self.autostart.toggled.connect(regler_autostart)
        ligne.addWidget(self.autostart)
        ligne.addStretch(1)
        o.addLayout(ligne)
        o.addWidget(QLabel("Astuce : clic droit sur une vidéo → « Rendre plus fluide (60 i/s) » pour la préparer "
                           "à la taille exacte de ton écran.", objectName="aide", wordWrap=True))
        self.zone_options.setVisible(False)
        c.addWidget(self.zone_options)

    def _barre_bas(self):
        self.zone_progression = QWidget(objectName="barre-bas")
        b = QHBoxLayout(self.zone_progression)
        b.setContentsMargins(28, 10, 28, 10)
        self.texte_progression = QLabel()
        b.addWidget(self.texte_progression)
        self.barre = QProgressBar(textVisible=False, maximum=1000)
        b.addWidget(self.barre, 1)
        annuler = QPushButton("Annuler")
        annuler.clicked.connect(lambda: self.optimisation and self.optimisation.annuler())
        b.addWidget(annuler)
        self.zone_progression.setVisible(False)
        return self.zone_progression

    # --- grille ------------------------------------------------------------------------

    def _remplir_grille(self):
        self.grille.blockSignals(True)
        self.grille.clear()
        tuile = QListWidgetItem(QIcon(self._tuile_ajouter()), "Ajouter des fichiers")
        tuile.setData(ROLE_CHEMIN, AJOUTER)
        tuile.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.grille.addItem(tuile)
        for e in self.config["bibliotheque"]:
            self._ajouter_element(e)
        self.grille.blockSignals(False)

    def _ajouter_element(self, entree):
        element = QListWidgetItem(QIcon(self._vignette(None, entree["chemin"])), Path(entree["chemin"]).name)
        element.setData(ROLE_CHEMIN, entree["chemin"])
        element.setToolTip(entree["chemin"])
        self.grille.addItem(element)
        self._maj_element(element)
        self.travail.submit(self._fabriquer_miniature, entree["chemin"])
        return element

    def _fabriquer_miniature(self, chemin):
        image = miniature(chemin)
        self.messager.miniature_prete.emit(chemin, str(image) if image else "")

    def _miniature_prete(self, chemin, image):
        element = self._element(chemin)
        pixmap = QPixmap(image) if image else QPixmap(chemin)
        if element and not pixmap.isNull():
            element.setData(ROLE_IMAGE, pixmap)
            self._maj_element(element)

    def _maj_element(self, element):
        """Vignette, coche et cadre « actuel » selon le mode."""
        chemin = element.data(ROLE_CHEMIN)
        if chemin == AJOUTER:
            return
        self.grille.blockSignals(True)
        diapo = self.config["mode"] == "diaporama"
        if diapo:
            element.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            element.setCheckState(Qt.CheckState.Checked if chemin in self.config["diaporama"]
                                  else Qt.CheckState.Unchecked)
        else:
            element.setFlags(Qt.ItemFlag.ItemIsEnabled)
            element.setData(Qt.ItemDataRole.CheckStateRole, None)
        actuel = (not diapo and chemin == self.config["actuel"]) or (diapo and chemin in self.config["diaporama"])
        element.setIcon(QIcon(self._vignette(element.data(ROLE_IMAGE), chemin, actuel)))
        self.grille.blockSignals(False)

    def _vignette(self, pixmap, chemin, actuel=False):
        taille = TAILLE_ICONE
        rendu = QPixmap(taille)
        rendu.fill(Qt.GlobalColor.transparent)
        peintre = QPainter(rendu)
        peintre.setRenderHint(QPainter.RenderHint.Antialiasing)
        peintre.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if pixmap and not pixmap.isNull():
            image = pixmap.scaled(taille, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
            image = image.copy((image.width() - taille.width()) // 2, (image.height() - taille.height()) // 2,
                               taille.width(), taille.height())
            peintre.setBrush(image)
        else:
            peintre.setBrush(QColor("#1f1f2b"))
        peintre.setPen(Qt.PenStyle.NoPen)
        peintre.drawRoundedRect(rendu.rect(), 10, 10)

        e = cfg.entree(self.config, chemin)
        badges = []
        if e and e["type"] == "video":
            badges.append(("▶ VIDÉO", QColor(0, 0, 0, 170)))
        if e and e.get("optimise") and os.path.isfile(e["optimise"]):
            badges.append(("60 i/s", QColor(124, 92, 255, 230)))
        police = peintre.font()
        police.setPointSize(7)
        police.setBold(True)
        peintre.setFont(police)
        x = 8
        for texte, couleur in badges:
            largeur = peintre.fontMetrics().horizontalAdvance(texte) + 12
            peintre.setPen(Qt.PenStyle.NoPen)
            peintre.setBrush(couleur)
            peintre.drawRoundedRect(x, 8, largeur, 17, 5, 5)
            peintre.setPen(QColor("white"))
            peintre.drawText(x, 8, largeur, 17, Qt.AlignmentFlag.AlignCenter, texte)
            x += largeur + 5
        if actuel:
            peintre.setPen(QPen(QColor(VIOLET), 4))
            peintre.setBrush(Qt.BrushStyle.NoBrush)
            peintre.drawRoundedRect(rendu.rect().adjusted(2, 2, -2, -2), 9, 9)
            peintre.setPen(Qt.PenStyle.NoPen)
            peintre.setBrush(QColor(VIOLET))
            peintre.drawEllipse(taille.width() - 32, 8, 24, 24)
            peintre.setPen(QColor("white"))
            police.setPointSize(10)
            peintre.setFont(police)
            peintre.drawText(taille.width() - 32, 8, 24, 24, Qt.AlignmentFlag.AlignCenter, "✓")
        peintre.end()
        return rendu

    def _tuile_ajouter(self):
        rendu = QPixmap(TAILLE_ICONE)
        rendu.fill(Qt.GlobalColor.transparent)
        peintre = QPainter(rendu)
        peintre.setRenderHint(QPainter.RenderHint.Antialiasing)
        stylo = QPen(QColor("#4a4a66"), 2, Qt.PenStyle.DashLine)
        peintre.setPen(stylo)
        peintre.setBrush(QColor("#17171f"))
        peintre.drawRoundedRect(rendu.rect().adjusted(1, 1, -1, -1), 10, 10)
        police = peintre.font()
        police.setPointSize(30)
        peintre.setFont(police)
        peintre.setPen(QColor("#b9a8ff"))
        peintre.drawText(rendu.rect(), Qt.AlignmentFlag.AlignCenter, "+")
        peintre.end()
        return rendu

    def _element(self, chemin):
        for i in range(self.grille.count()):
            if self.grille.item(i).data(ROLE_CHEMIN) == chemin:
                return self.grille.item(i)
        return None

    def _tout_maj(self):
        for i in range(self.grille.count()):
            self._maj_element(self.grille.item(i))

    # --- actions -------------------------------------------------------------------------

    def _clic(self, element):
        chemin = element.data(ROLE_CHEMIN)
        if chemin == AJOUTER:
            self._choisir_fichiers()
        elif self.config["mode"] == "diaporama":
            coche = element.checkState() == Qt.CheckState.Checked
            element.setCheckState(Qt.CheckState.Unchecked if coche else Qt.CheckState.Checked)
        else:
            self.config["actuel"] = chemin
            self.config["pause"] = False
            self._enregistrer_et_lancer()
            self._tout_maj()

    def _coche_modifiee(self, element):
        chemin = element.data(ROLE_CHEMIN)
        if self.config["mode"] != "diaporama" or chemin == AJOUTER:
            return
        coche = element.checkState() == Qt.CheckState.Checked
        liste = self.config["diaporama"]
        if coche and chemin not in liste:
            liste.append(chemin)
        elif not coche and chemin in liste:
            liste.remove(chemin)
        self._maj_element(element)
        self._maj_aide()
        self._enregistrer_et_lancer()

    def _tout_cocher(self):
        tout = [e["chemin"] for e in self.config["bibliotheque"]]
        self.config["diaporama"] = [] if set(self.config["diaporama"]) >= set(tout) else tout
        self._tout_maj()
        self._maj_aide()
        self._enregistrer_et_lancer()

    def _choisir_mode(self, mode):
        self.config["mode"] = mode
        if mode == "diaporama" and not self.config["diaporama"]:
            # par défaut, toutes les photos de la bibliothèque
            self.config["diaporama"] = [e["chemin"] for e in self.config["bibliotheque"] if e["type"] == "image"]
        self.config["pause"] = False
        self._maj_mode()
        self._enregistrer_et_lancer()

    def _maj_mode(self):
        diapo = self.config["mode"] == "diaporama"
        self.carte_unique.setChecked(not diapo)
        self.carte_diapo.setChecked(diapo)
        self.zone_diapo.setVisible(diapo)
        self.bouton_dossier.setVisible(True)
        self.titre_choix.setText("2.  Coche les images du diaporama" if diapo
                                 else "2.  Clique sur le fond que tu veux")
        self._tout_maj()
        self._maj_aide()

    def _maj_aide(self):
        if len(self.config["bibliotheque"]) == 0:
            texte = "Commence par ajouter des vidéos ou des photos avec la case « + » (ou glisse-les ici)."
        elif self.config["mode"] == "diaporama":
            n = len(self.config["diaporama"])
            texte = (f"{n} image{'s' if n > 1 else ''} dans le diaporama. Clique sur une image pour l'ajouter "
                     "ou la retirer." if n else "Coche au moins une image pour lancer le diaporama.")
        else:
            texte = "Un seul clic suffit : le fond change tout de suite. Clic droit pour plus de choix."
        self.aide_choix.setText(texte)

    def _diapo_modifie(self, *_):
        self.config["intervalle"] = self.intervalle.currentData()
        self.config["aleatoire"] = self.aleatoire.isChecked()
        self._enregistrer_et_lancer()

    def _reglage_modifie(self, *_):
        self.config["cadrage"] = self.cles_cadrage[self.cadrage.currentIndex()]
        self.config["fluidite"] = self.fluidite.isChecked()
        self.config["son"] = self.son.isChecked()
        self.config["volume"] = self.volume.value()
        self.volume.setEnabled(self.config["son"])
        cfg.ecrire(self.config)
        canal.envoyer("recharger")

    def _enregistrer_et_lancer(self):
        cfg.ecrire(self.config)
        if not cfg.fichiers_a_jouer(self.config):
            canal.envoyer("recharger")
        elif canal.envoyer("recharger") is None:
            lancer_detache(commande_application("--lecteur"))
        QTimer.singleShot(900, self._maj_etat)

    def _marche_arret(self):
        if canal.lecteur_actif():
            canal.envoyer("arreter")
        elif cfg.fichiers_a_jouer(self.config):
            self.config["pause"] = False
            self._enregistrer_et_lancer()
        else:
            QMessageBox.information(self, "Fond Vivant", "Choisis d'abord un fond dans ta bibliothèque.")
        QTimer.singleShot(700, self._maj_etat)

    def _basculer_pause(self):
        self.config["pause"] = not self.config["pause"]
        cfg.ecrire(self.config)
        canal.envoyer("recharger")
        self._maj_etat()

    def _maj_etat(self):
        actif = canal.lecteur_actif()
        self.bouton_marche.setText("■  Arrêter" if actif else "▶  Démarrer")
        self.bouton_pause.setVisible(actif)
        self.bouton_pause.setText("▶  Reprendre" if self.config["pause"] else "❚❚  Pause")
        if not actif:
            self.etat.setObjectName("etat-arret")
            self.etat.setText("○  Arrêté : ton fond d'écran habituel est affiché")
        elif self.config["pause"]:
            self.etat.setObjectName("etat-arret")
            self.etat.setText("❚❚  En pause")
        elif self.config["mode"] == "diaporama":
            self.etat.setObjectName("etat-actif")
            self.etat.setText(f"●  Diaporama en cours ({self.intervalle.currentText()} par image)")
        else:
            self.etat.setObjectName("etat-actif")
            self.etat.setText(f"●  En fond d'écran : {Path(self.config['actuel']).name}")
        self.etat.style().unpolish(self.etat)
        self.etat.style().polish(self.etat)

    # --- ajout / retrait -------------------------------------------------------------------

    def _choisir_fichiers(self):
        motifs = " ".join("*" + e for e in sorted(EXTENSIONS_VIDEO | EXTENSIONS_IMAGE))
        chemins, _ = QFileDialog.getOpenFileNames(self, "Ajouter des vidéos ou des photos", str(Path.home()),
                                                  f"Vidéos et photos ({motifs});;Tous les fichiers (*)")
        self._ajouter(chemins)

    def _choisir_dossier(self):
        dossier = QFileDialog.getExistingDirectory(self, "Ajouter toutes les images d'un dossier", str(Path.home()))
        if dossier:
            fichiers = sorted(str(p) for p in Path(dossier).iterdir() if p.is_file() and type_fichier(str(p)))
            if not fichiers:
                QMessageBox.information(self, "Dossier vide", "Ce dossier ne contient ni photo ni vidéo.")
            self._ajouter(fichiers)

    def _ajouter(self, chemins):
        refuses = []
        nouveaux = []
        for chemin in chemins:
            chemin = os.path.abspath(chemin)
            type_ = type_fichier(chemin)
            if not type_ or not os.path.isfile(chemin):
                refuses.append(Path(chemin).name)
            elif not cfg.entree(self.config, chemin):
                entree = {"chemin": chemin, "type": type_, "optimise": ""}
                self.config["bibliotheque"].append(entree)
                nouveaux.append(chemin)
                self._ajouter_element(entree)
        if self.config["mode"] == "diaporama":
            self.config["diaporama"] += nouveaux  # ce qu'on ajoute en mode diaporama y entre directement
            self._tout_maj()
        cfg.ecrire(self.config)
        self._maj_aide()
        if refuses:
            QMessageBox.warning(self, "Fichiers ignorés",
                                "Ce ne sont ni des vidéos ni des photos :\n" + "\n".join(refuses[:15]))
        if nouveaux and self.config["mode"] == "diaporama":
            self._enregistrer_et_lancer()

    def _menu(self, position):
        element = self.grille.itemAt(position)
        chemin = element.data(ROLE_CHEMIN) if element else None
        if not chemin or chemin == AJOUTER:
            return
        e = cfg.entree(self.config, chemin)
        menu = QMenu(self)
        if self.config["mode"] == "unique":
            menu.addAction("Mettre en fond d'écran", lambda: self._clic(element))
        if e["type"] == "video":
            action = QAction("Rendre plus fluide (60 i/s, taille de mon écran)", menu)
            action.setEnabled(self.optimisation is None)
            action.triggered.connect(lambda: self._optimiser(chemin))
            menu.addAction(action)
        menu.addAction("Infos", lambda: self._infos(e))
        menu.addSeparator()
        menu.addAction("Retirer de la bibliothèque", lambda: self._retirer(chemin))
        menu.exec(self.grille.viewport().mapToGlobal(position))

    def _infos(self, e):
        infos = sonder(e["chemin"])
        lignes = [e["chemin"]]
        if infos["largeur"]:
            lignes.append(f"{infos['largeur']} × {infos['hauteur']} pixels")
        if e["type"] == "video":
            lignes.append(f"{infos['fps']:.0f} images par seconde, {infos['duree']:.0f} secondes")
        if e.get("optimise") and os.path.isfile(e["optimise"]):
            o = sonder(e["optimise"])
            lignes.append(f"Version fluide prête : {o['largeur']} × {o['hauteur']} à {o['fps']:.0f} i/s")
        QMessageBox.information(self, Path(e["chemin"]).name, "\n".join(lignes))

    def _retirer(self, chemin):
        e = cfg.entree(self.config, chemin)
        if e.get("optimise"):
            Path(e["optimise"]).unlink(missing_ok=True)
        self.config["bibliotheque"].remove(e)
        if self.config["actuel"] == chemin:
            self.config["actuel"] = ""
        if chemin in self.config["diaporama"]:
            self.config["diaporama"].remove(chemin)
        cfg.ecrire(self.config)
        self.grille.takeItem(self.grille.row(self._element(chemin)))
        canal.envoyer("recharger")
        self._maj_aide()

    # --- rendre une vidéo plus fluide ------------------------------------------------------

    def _optimiser(self, chemin):
        ecrans = lister_ecrans()
        _x, _y, largeur, hauteur, hz = max(ecrans, key=lambda e: e[2] * e[3]) if ecrans else (0, 0, 1920, 1080, 60)
        fps = max(24, round(hz))
        self.optimisation = Optimisation(chemin, largeur, hauteur, fps, True, self)
        self.optimisation.progression.connect(lambda p: self.barre.setValue(int(p * 1000)))
        self.optimisation.terminee.connect(lambda ok, r: self._optimisation_finie(chemin, ok, r))
        self.texte_progression.setText(f"Préparation de « {Path(chemin).name} » en {largeur}×{hauteur} à {fps} i/s…")
        self.barre.setValue(0)
        self.zone_progression.setVisible(True)
        self.optimisation.lancer()

    def _optimisation_finie(self, chemin, reussi, resultat):
        self.optimisation = None
        self.zone_progression.setVisible(False)
        e = cfg.entree(self.config, chemin)
        if reussi and e:
            e["optimise"] = resultat
            cfg.ecrire(self.config)
            element = self._element(chemin)
            if element:
                self._maj_element(element)
            canal.envoyer("recharger")
        elif resultat != "annulée":
            QMessageBox.warning(self, "Impossible de préparer la vidéo", resultat)

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
