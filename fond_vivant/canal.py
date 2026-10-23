"""Petit canal local entre la fenêtre de réglage et le lecteur (socket Unix / tube nommé Windows)."""
from PySide6.QtNetwork import QLocalSocket

from .systeme import NOM_SERVEUR


def envoyer(commande: str, delai_ms: int = 400) -> str | None:
    """Envoie une commande au lecteur et rend sa réponse, ou None s'il ne tourne pas."""
    socket = QLocalSocket()
    socket.connectToServer(NOM_SERVEUR)
    if not socket.waitForConnected(delai_ms):
        return None
    socket.write((commande + "\n").encode())
    socket.flush()
    reponse = b""
    if socket.waitForReadyRead(delai_ms):
        reponse = bytes(socket.readAll())
    socket.disconnectFromServer()
    return reponse.decode(errors="replace").strip()


def lecteur_actif() -> bool:
    return envoyer("etat") is not None
