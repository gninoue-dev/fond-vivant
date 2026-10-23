"""Point d'entrée.

  (sans argument)  fenêtre de réglage
  --lecteur        le lecteur qui affiche le fond derrière le bureau
  --arreter        arrête le lecteur
"""
import sys


def main() -> int:
    if "--lecteur" in sys.argv:
        from .lecteur import principal
        return principal()
    if "--arreter" in sys.argv:
        from PySide6.QtCore import QCoreApplication

        from . import canal
        QCoreApplication(sys.argv[:1])
        return 0 if canal.envoyer("arreter") is not None else 1
    from .reglages import principal
    return principal()


if __name__ == "__main__":
    sys.exit(main())
