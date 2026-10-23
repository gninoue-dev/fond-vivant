// Fond Vivant pour GNOME Shell.
//
// GNOME ne laisse aucune fenêtre passer sous celle des icônes du bureau (DING).
// L'extension prend donc l'image de la fenêtre de Fond Vivant (classe « fond-vivant »)
// et l'affiche dans la couche du fond d'écran, sous les icônes et sous toutes les
// fenêtres. La fenêtre d'origine est rendue invisible ; les clics la traversent déjà.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const CLASSE = 'fond-vivant';

export default class FondVivant extends Extension {
    enable() {
        this._clones = new Map(); // MetaWindow -> {clone, signaux}
        this._idCreation = global.display.connect('window-created', (_d, fenetre) => {
            // l'acteur de la fenêtre n'existe pas encore à cet instant
            GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                this._prendre(fenetre);
                return GLib.SOURCE_REMOVE;
            });
        });
        for (const acteur of global.get_window_actors())
            this._prendre(acteur.get_meta_window());
    }

    disable() {
        global.display.disconnect(this._idCreation);
        for (const fenetre of [...this._clones.keys()])
            this._lacher(fenetre);
        this._clones = null;
    }

    _prendre(fenetre) {
        if (!fenetre || this._clones?.has(fenetre) || fenetre.get_wm_class_instance() !== CLASSE)
            return;
        const acteur = fenetre.get_compositor_private();
        if (!acteur)
            return;

        const clone = new Clutter.Clone({source: acteur, reactive: false});
        const placer = () => {
            const cadre = fenetre.get_buffer_rect();
            clone.set_position(cadre.x, cadre.y);
        };
        placer();
        // au-dessus de l'image de fond de GNOME, sous tout le reste
        Main.layoutManager._backgroundGroup.add_child(clone);
        acteur.opacity = 0;

        const signaux = [
            [fenetre, fenetre.connect('position-changed', placer)],
            [fenetre, fenetre.connect('size-changed', placer)],
            [fenetre, fenetre.connect('unmanaged', () => this._lacher(fenetre))],
            // GNOME peut remettre l'opacité (animations) : on la garde à zéro
            [acteur, acteur.connect('notify::opacity', () => {
                if (acteur.opacity !== 0)
                    acteur.opacity = 0;
            })],
        ];
        this._clones.set(fenetre, {clone, acteur, signaux});
    }

    _lacher(fenetre) {
        const info = this._clones?.get(fenetre);
        if (!info)
            return;
        for (const [objet, id] of info.signaux) {
            try {
                objet.disconnect(id);
            } catch {
                // objet déjà détruit
            }
        }
        info.clone.destroy();
        try {
            info.acteur.opacity = 255;
        } catch {
            // fenêtre déjà détruite
        }
        this._clones.delete(fenetre);
    }
}
