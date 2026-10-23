"""Recadrer une image ou une vidéo au format de l'écran, à la souris.

Le recadrage est rangé dans la bibliothèque en fractions de l'image d'origine :
{"x", "y", "l", "h"} (coin haut-gauche, largeur, hauteur) plus la taille d'origine.
Le cadre a toujours exactement les proportions de l'écran.
"""
from math import gcd

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget)

ZOOM_MAX = 4.0  # le cadre peut descendre au quart de sa taille maximale


def nom_format(largeur: int, hauteur: int) -> str:
    """16:9, 4:3, 21:9… ou un rapport arrondi."""
    if not largeur or not hauteur:
        return "?"
    rapport = largeur / hauteur
    connus = {"16:9": 16 / 9, "16:10": 16 / 10, "4:3": 4 / 3, "3:2": 3 / 2, "21:9": 64 / 27, "32:9": 32 / 9,
              "1:1": 1, "9:16": 9 / 16, "3:4": 3 / 4, "2:3": 2 / 3}
    for nom, valeur in connus.items():
        if abs(rapport - valeur) / valeur < 0.02:
            return nom
    d = gcd(largeur, hauteur)
    return f"{largeur // d}:{hauteur // d}" if largeur // d < 50 else f"{rapport:.2f}:1"


def meme_format(l1, h1, l2, h2, tolerance=0.02) -> bool:
    return bool(l1 and h1 and l2 and h2) and abs((l1 / h1) / (l2 / h2) - 1) < tolerance


def cadre_plein(largeur_img, hauteur_img, largeur_ecran, hauteur_ecran):
    """Le plus grand cadre au format de l'écran, centré (ce que fait « Remplir l'écran »)."""
    rapport = (largeur_ecran / hauteur_ecran) * hauteur_img / largeur_img  # l / h en fractions
    if rapport <= 1:
        l, h = rapport, 1.0
    else:
        l, h = 1.0, 1 / rapport
    return {"x": (1 - l) / 2, "y": (1 - h) / 2, "l": l, "h": h}


class ZoneRecadrage(QWidget):
    modifie = Signal()

    def __init__(self, pixmap, largeur_img, hauteur_img, largeur_ecran, hauteur_ecran, cadre=None):
        super().__init__()
        self.pixmap = pixmap
        self.li, self.hi = largeur_img, hauteur_img
        self.le, self.he = largeur_ecran, hauteur_ecran
        self.plein = cadre_plein(largeur_img, hauteur_img, largeur_ecran, hauteur_ecran)
        self.cadre = dict(cadre) if cadre else dict(self.plein)
        self.depart = None
        self.setMinimumSize(640, 380)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setMouseTracking(True)

    # zoom = taille du cadre plein / taille du cadre (1 = tout ce qui peut tenir)
    def zoom(self) -> float:
        return self.plein["l"] / self.cadre["l"]

    def regler_zoom(self, zoom: float):
        zoom = min(ZOOM_MAX, max(1.0, zoom))
        cx = self.cadre["x"] + self.cadre["l"] / 2
        cy = self.cadre["y"] + self.cadre["h"] / 2
        self.cadre["l"] = self.plein["l"] / zoom
        self.cadre["h"] = self.plein["h"] / zoom
        self._placer(cx - self.cadre["l"] / 2, cy - self.cadre["h"] / 2)

    def recentrer(self):
        self.cadre = dict(self.plein)
        self.update()
        self.modifie.emit()

    def _placer(self, x, y):
        self.cadre["x"] = min(max(0.0, x), 1 - self.cadre["l"])
        self.cadre["y"] = min(max(0.0, y), 1 - self.cadre["h"])
        self.update()
        self.modifie.emit()

    def _zone_image(self) -> QRectF:
        """Où l'image est dessinée dans le widget (ajustée, centrée)."""
        echelle = min(self.width() / self.li, self.height() / self.hi)
        l, h = self.li * echelle, self.hi * echelle
        return QRectF((self.width() - l) / 2, (self.height() - h) / 2, l, h)

    def _zone_cadre(self) -> QRectF:
        z = self._zone_image()
        c = self.cadre
        return QRectF(z.x() + c["x"] * z.width(), z.y() + c["y"] * z.height(), c["l"] * z.width(), c["h"] * z.height())

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#0b0b10"))
        p.drawPixmap(self._zone_image(), self.pixmap, QRectF(self.pixmap.rect()))
        cadre = self._zone_cadre()
        # ce qui sera coupé est assombri
        masque = QPainterPath()
        masque.addRect(self._zone_image())
        trou = QPainterPath()
        trou.addRect(cadre)
        p.fillPath(masque.subtracted(trou), QColor(0, 0, 0, 170))
        # tiers, pour aider à placer le sujet
        p.setPen(QPen(QColor(255, 255, 255, 70), 1))
        for i in (1, 2):
            x = cadre.x() + cadre.width() * i / 3
            y = cadre.y() + cadre.height() * i / 3
            p.drawLine(QPointF(x, cadre.top()), QPointF(x, cadre.bottom()))
            p.drawLine(QPointF(cadre.left(), y), QPointF(cadre.right(), y))
        p.setPen(QPen(QColor("#7c5cff"), 3))
        p.drawRect(cadre)
        p.end()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.depart = (ev.position(), self.cadre["x"], self.cadre["y"])
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, ev):
        if not self.depart:
            return
        position, x0, y0 = self.depart
        z = self._zone_image()
        d = ev.position() - position
        self._placer(x0 + d.x() / z.width(), y0 + d.y() / z.height())

    def mouseReleaseEvent(self, _ev):
        self.depart = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, ev):
        self.regler_zoom(self.zoom() * (1.1 if ev.angleDelta().y() > 0 else 1 / 1.1))


class DialogueRecadrage(QDialog):
    def __init__(self, parent, nom, pixmap, largeur_img, hauteur_img, largeur_ecran, hauteur_ecran, cadre=None):
        super().__init__(parent)
        self.setWindowTitle(f"Recadrer « {nom} »")
        self.resize(900, 640)
        self.li, self.hi, self.le, self.he = largeur_img, hauteur_img, largeur_ecran, hauteur_ecran
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(10)

        titre = QLabel("Choisis la partie de l'image qui sera affichée sur ton écran")
        titre.setStyleSheet("font-size: 13pt; font-weight: 600;")
        v.addWidget(titre)
        v.addWidget(QLabel("Fais glisser le cadre avec la souris. La molette (ou le curseur) zoome. "
                           "Tout ce qui est dans le cadre violet s'affichera, le reste sera coupé.",
                           objectName="aide", wordWrap=True))

        self.zone = ZoneRecadrage(pixmap, largeur_img, hauteur_img, largeur_ecran, hauteur_ecran, cadre)
        v.addWidget(self.zone, 1)

        ligne = QHBoxLayout()
        ligne.addWidget(QLabel("Zoom"))
        self.curseur = QSlider(Qt.Orientation.Horizontal, minimum=100, maximum=int(ZOOM_MAX * 100))
        self.curseur.setValue(int(self.zone.zoom() * 100))
        self.curseur.valueChanged.connect(lambda val: self.zone.regler_zoom(val / 100))
        ligne.addWidget(self.curseur, 1)
        recentrer = QPushButton("Tout l'écran, centré")
        recentrer.clicked.connect(self.zone.recentrer)
        ligne.addWidget(recentrer)
        v.addLayout(ligne)

        self.conseil = QLabel(wordWrap=True)
        self.conseil.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.conseil)

        boutons = QHBoxLayout()
        boutons.addStretch(1)
        annuler = QPushButton("Annuler")
        annuler.clicked.connect(self.reject)
        boutons.addWidget(annuler)
        enregistrer = QPushButton("Enregistrer ce cadrage", objectName="principal")
        enregistrer.clicked.connect(self.accept)
        boutons.addWidget(enregistrer)
        v.addLayout(boutons)

        self.zone.modifie.connect(self._maj)
        self._maj()

    def _maj(self):
        self.curseur.blockSignals(True)
        self.curseur.setValue(int(round(self.zone.zoom() * 100)))
        self.curseur.blockSignals(False)
        largeur_utile = self.zone.cadre["l"] * self.li
        agrandissement = self.le / largeur_utile if largeur_utile else 1
        lignes = [f"Ton écran : <b>{self.le} × {self.he}</b> ({nom_format(self.le, self.he)}) · "
                  f"cette image : <b>{self.li} × {self.hi}</b> ({nom_format(self.li, self.hi)})"]
        if agrandissement > 1.15:
            lignes.append(f"<span style='color:#ffcf8a'>⚠ La partie choisie sera agrandie ×{agrandissement:.1f} : "
                          "elle risque d'être floue. Dézoome, ou prends une image plus grande.</span>")
        elif not meme_format(self.li, self.hi, self.le, self.he):
            lignes.append("<span style='color:#9a9ab0'>L'image n'a pas le même format que ton écran : "
                          "une partie est forcément coupée, c'est toi qui choisis laquelle.</span>")
        else:
            lignes.append("<span style='color:#7ee2a8'>✓ Qualité parfaite pour ton écran.</span>")
        lignes.append(f"<span style='color:#9a9ab0'>Conseil : pour un résultat parfait sans rien couper, choisis des "
                      f"images de <b>{self.le} × {self.he}</b> pixels ou plus grandes, au format "
                      f"<b>{nom_format(self.le, self.he)}</b>.</span>")
        self.conseil.setText("<br>".join(lignes))

    def resultat(self) -> dict:
        c = self.zone.cadre
        plein = self.zone.plein
        if self.zone.zoom() < 1.001 and abs(c["x"] - plein["x"]) < 1e-3 and abs(c["y"] - plein["y"]) < 1e-3:
            return {}  # identique au remplissage automatique : rien à retenir
        return {**{k: round(v, 5) for k, v in c.items()}, "largeur": self.li, "hauteur": self.hi}
