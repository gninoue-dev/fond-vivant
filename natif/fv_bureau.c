/*
 * fv-bureau : crée la fenêtre « fond d'écran » dans laquelle mpv dessine.
 *
 *   fv-bureau --ecrans          liste les écrans : "x y largeur hauteur hz" (pixels réels)
 *   fv-bureau X Y LARGEUR HAUTEUR
 *       crée la fenêtre derrière les icônes du bureau, écrit "WID <identifiant>"
 *       sur la sortie standard puis attend. Elle se ferme quand l'entrée standard
 *       est fermée (le lecteur s'est arrêté) ou quand on lui écrit "quitter".
 *
 * Linux : fenêtre X11 de type _NET_WM_WINDOW_TYPE_DESKTOP, que les clics traversent.
 * Windows : fenêtre enfant du WorkerW situé sous les icônes (méthode de Wallpaper Engine).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int lire_geometrie(char **argv, int *x, int *y, int *l, int *h)
{
    *x = atoi(argv[1]);
    *y = atoi(argv[2]);
    *l = atoi(argv[3]);
    *h = atoi(argv[4]);
    return *l > 0 && *h > 0;
}

#ifdef _WIN32
/* ======================================================================== */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

static HWND fenetre;

static void rendre_dpi_conscient(void)
{
    /* coordonnées en pixels réels, même avec une mise à l'échelle à 125 % ou 150 % */
    typedef BOOL(WINAPI * Fonction)(HANDLE);
    HMODULE user32 = GetModuleHandleW(L"user32.dll");
    Fonction f = (Fonction)(void *)GetProcAddress(user32, "SetProcessDpiAwarenessContext");
    if (f)
        f((HANDLE)-4); /* DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 */
    else
        SetProcessDPIAware();
}

static BOOL CALLBACK ecran_trouve(HMONITOR moniteur, HDC dc, LPRECT r, LPARAM principal)
{
    (void)dc;
    (void)r;
    MONITORINFOEXW info;
    DEVMODEW mode;
    info.cbSize = sizeof info;
    GetMonitorInfoW(moniteur, (MONITORINFO *)&info);
    int est_principal = (info.dwFlags & MONITORINFOF_PRIMARY) != 0;
    if (est_principal != (int)principal)
        return TRUE;
    memset(&mode, 0, sizeof mode);
    mode.dmSize = sizeof mode;
    DWORD hz = 60;
    if (EnumDisplaySettingsW(info.szDevice, ENUM_CURRENT_SETTINGS, &mode) && mode.dmDisplayFrequency > 1)
        hz = mode.dmDisplayFrequency;
    RECT *m = &info.rcMonitor;
    printf("%ld %ld %ld %ld %lu\n", m->left, m->top, m->right - m->left, m->bottom - m->top, hz);
    return TRUE;
}

static int lister_ecrans(void)
{
    /* l'écran principal d'abord : c'est lui qui aura le son */
    EnumDisplayMonitors(NULL, NULL, ecran_trouve, 1);
    EnumDisplayMonitors(NULL, NULL, ecran_trouve, 0);
    return 0;
}

static BOOL CALLBACK chercher_workerw(HWND haut, LPARAM resultat)
{
    if (FindWindowExW(haut, NULL, L"SHELLDLL_DefView", NULL))
        *(HWND *)resultat = FindWindowExW(NULL, haut, L"WorkerW", NULL);
    return TRUE;
}

static LRESULT CALLBACK procedure(HWND h, UINT message, WPARAM w, LPARAM l)
{
    switch (message) {
    case WM_ERASEBKGND: {
        RECT r;
        GetClientRect(h, &r);
        FillRect((HDC)w, &r, (HBRUSH)GetStockObject(BLACK_BRUSH));
        return 1;
    }
    case WM_DESTROY: /* explorer.exe redémarré : le lecteur recrée tout */
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(h, message, w, l);
}

static DWORD WINAPI surveiller_entree(LPVOID inutile)
{
    (void)inutile;
    char ligne[128];
    while (fgets(ligne, sizeof ligne, stdin))
        if (strncmp(ligne, "quitter", 7) == 0)
            break;
    PostMessageW(fenetre, WM_CLOSE, 0, 0);
    return 0;
}

static int creer_fond(int x, int y, int l, int h)
{
    HWND progman = FindWindowW(L"Progman", NULL);
    HWND parent = NULL, icones = NULL, workerw = NULL;
    DWORD_PTR r;

    if (!progman) {
        fprintf(stderr, "Progman introuvable (explorer.exe ne tourne pas ?)\n");
        return 1;
    }
    /* demande à l'explorateur de créer le WorkerW qui sert de fond animé */
    SendMessageTimeoutW(progman, 0x052C, 0xD, 0x1, SMTO_NORMAL, 1000, &r);
    SendMessageTimeoutW(progman, 0x052C, 0, 0, SMTO_NORMAL, 1000, &r);

    EnumWindows(chercher_workerw, (LPARAM)&workerw);
    if (workerw) {
        parent = workerw; /* Windows 10 et Windows 11 jusqu'à 23H2 */
    } else {
        /* Windows 11 24H2 : le WorkerW et les icônes sont des enfants de Progman */
        icones = FindWindowExW(progman, NULL, L"SHELLDLL_DefView", NULL);
        workerw = FindWindowExW(progman, NULL, L"WorkerW", NULL);
        parent = progman;
    }

    WNDCLASSW classe = {0};
    classe.lpfnWndProc = procedure;
    classe.hInstance = GetModuleHandleW(NULL);
    classe.lpszClassName = L"FondVivantHote";
    classe.hCursor = LoadCursorW(NULL, (LPCWSTR)IDC_ARROW);
    RegisterClassW(&classe);

    fenetre = CreateWindowExW(WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW, classe.lpszClassName, L"Fond Vivant",
                              WS_POPUP, x, y, l, h, NULL, NULL, classe.hInstance, NULL);
    if (!fenetre) {
        fprintf(stderr, "création de la fenêtre impossible (%lu)\n", GetLastError());
        return 1;
    }
    SetWindowLongPtrW(fenetre, GWL_STYLE, WS_CHILD | WS_CLIPSIBLINGS | WS_CLIPCHILDREN);
    SetParent(fenetre, parent);

    /* le parent couvre tout le bureau virtuel : on se place relativement à son coin */
    POINT coin = {x, y};
    ScreenToClient(parent, &coin);
    if (icones) {
        SetWindowPos(fenetre, icones, coin.x, coin.y, l, h, SWP_NOACTIVATE | SWP_SHOWWINDOW);
        if (workerw)
            SetWindowPos(workerw, fenetre, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
    } else {
        SetWindowPos(fenetre, HWND_TOP, coin.x, coin.y, l, h, SWP_NOACTIVATE | SWP_SHOWWINDOW);
    }

    printf("WID %lld\n", (long long)(INT_PTR)fenetre);
    fflush(stdout);

    CreateThread(NULL, 0, surveiller_entree, NULL, 0, NULL);
    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    if (IsWindow(fenetre))
        DestroyWindow(fenetre);
    return 0;
}

int main(int argc, char **argv)
{
    int x, y, l, h;
    rendre_dpi_conscient();
    if (argc == 2 && strcmp(argv[1], "--ecrans") == 0)
        return lister_ecrans();
    if (argc == 5 && lire_geometrie(argv, &x, &y, &l, &h))
        return creer_fond(x, y, l, h);
    fprintf(stderr, "usage : fv-bureau --ecrans | fv-bureau X Y LARGEUR HAUTEUR\n");
    return 2;
}

#else
/* ======================================================================== */
#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/extensions/Xrandr.h>
#include <X11/extensions/shape.h>
#include <sys/select.h>
#include <unistd.h>

static int lister_ecrans(Display *dpy)
{
    Window racine = DefaultRootWindow(dpy);
    XRRScreenResources *res = XRRGetScreenResourcesCurrent(dpy, racine);
    RROutput principal = XRRGetOutputPrimary(dpy, racine);
    if (!res)
        return 1;
    /* deux passes : l'écran principal d'abord (c'est lui qui aura le son) */
    for (int passe = 0; passe < 2; passe++) {
        for (int i = 0; i < res->noutput; i++) {
            if ((res->outputs[i] == principal) != (passe == 0))
                continue;
            XRROutputInfo *sortie = XRRGetOutputInfo(dpy, res, res->outputs[i]);
            if (sortie && sortie->connection == RR_Connected && sortie->crtc) {
                XRRCrtcInfo *crtc = XRRGetCrtcInfo(dpy, res, sortie->crtc);
                double hz = 60.0;
                for (int m = 0; crtc && m < res->nmode; m++) {
                    XRRModeInfo *mode = &res->modes[m];
                    if (mode->id == crtc->mode && mode->hTotal && mode->vTotal)
                        hz = (double)mode->dotClock / ((double)mode->hTotal * mode->vTotal);
                }
                if (crtc && crtc->width && crtc->height)
                    printf("%d %d %u %u %.3f\n", crtc->x, crtc->y, crtc->width, crtc->height, hz);
                if (crtc)
                    XRRFreeCrtcInfo(crtc);
            }
            if (sortie)
                XRRFreeOutputInfo(sortie);
        }
    }
    XRRFreeScreenResources(res);
    return 0;
}

static void poser_atomes(Display *dpy, Window w, const char *propriete, const char **noms, int n)
{
    Atom valeurs[8];
    for (int i = 0; i < n; i++)
        valeurs[i] = XInternAtom(dpy, noms[i], False);
    XChangeProperty(dpy, w, XInternAtom(dpy, propriete, False), XA_ATOM, 32, PropModeReplace,
                    (unsigned char *)valeurs, n);
}

static int est_bureau_etranger(Display *dpy, Window w)
{
    /* une autre fenêtre de bureau : celle des icônes (Desktop Icons de GNOME, Nautilus…) */
    Atom type_reel, *types = NULL;
    int format, resultat = 0;
    unsigned long n, reste;
    XClassHint classe;
    if (XGetClassHint(dpy, w, &classe)) {
        int a_nous = classe.res_name && strcmp(classe.res_name, "fond-vivant") == 0;
        XFree(classe.res_name);
        XFree(classe.res_class);
        if (a_nous)
            return 0;
    }
    if (XGetWindowProperty(dpy, w, XInternAtom(dpy, "_NET_WM_WINDOW_TYPE", False), 0, 8, False, XA_ATOM,
                           &type_reel, &format, &n, &reste, (unsigned char **)&types) == Success && types) {
        Atom bureau = XInternAtom(dpy, "_NET_WM_WINDOW_TYPE_DESKTOP", False);
        for (unsigned long i = 0; i < n; i++)
            resultat |= types[i] == bureau;
        XFree(types);
    }
    return resultat;
}

static Time heure_serveur(Display *dpy, Window w)
{
    /* l'heure du serveur X : on touche une propriété et on lit l'heure de l'événement */
    XEvent ev;
    XSelectInput(dpy, w, PropertyChangeMask);
    XChangeProperty(dpy, w, XInternAtom(dpy, "_FOND_VIVANT_HEURE", False), XA_STRING, 8, PropModeReplace,
                    (unsigned char *)"", 0);
    XWindowEvent(dpy, w, PropertyChangeMask, &ev);
    XSelectInput(dpy, w, NoEventMask);
    return ev.xproperty.time;
}

static void passer_sous_les_icones(Display *dpy, Window w, Time heure)
{
    /* _NET_CLIENT_LIST_STACKING va du bas vers le haut */
    Atom type_reel;
    int format;
    unsigned long n, reste;
    Window *pile = NULL;
    if (XGetWindowProperty(dpy, DefaultRootWindow(dpy), XInternAtom(dpy, "_NET_CLIENT_LIST_STACKING", False), 0,
                           4096, False, XA_WINDOW, &type_reel, &format, &n, &reste, (unsigned char **)&pile)
            != Success || !pile)
        return;
    int au_dessus_des_icones = 0;
    for (unsigned long i = 0; i < n && pile[i] != w; i++)
        au_dessus_des_icones |= est_bureau_etranger(dpy, pile[i]);
    XFree(pile);
    if (!au_dessus_des_icones)
        return;

    /* Mutter ignore une demande de placement venant d'une fenêtre dont la dernière
       « activité » est plus ancienne que celle de la fenêtre active : on la date de maintenant */
    unsigned long t = heure;
    XChangeProperty(dpy, w, XInternAtom(dpy, "_NET_WM_USER_TIME", False), XA_CARDINAL, 32, PropModeReplace,
                    (unsigned char *)&t, 1);
    XWindowChanges changement;
    changement.stack_mode = Below; /* tout en bas de la couche « bureau » */
    XReconfigureWMWindow(dpy, w, DefaultScreen(dpy), CWStackMode, &changement);
    XFlush(dpy);
}

static int creer_fond(Display *dpy, int x, int y, int l, int h)
{
    int ecran = DefaultScreen(dpy);
    XSetWindowAttributes attributs;
    attributs.background_pixel = BlackPixel(dpy, ecran);
    Window w = XCreateWindow(dpy, RootWindow(dpy, ecran), x, y, (unsigned)l, (unsigned)h, 0,
                             CopyFromParent, InputOutput, CopyFromParent, CWBackPixel, &attributs);

    const char *type[] = {"_NET_WM_WINDOW_TYPE_DESKTOP"};
    const char *etat[] = {"_NET_WM_STATE_BELOW", "_NET_WM_STATE_STICKY", "_NET_WM_STATE_SKIP_TASKBAR",
                          "_NET_WM_STATE_SKIP_PAGER"};
    poser_atomes(dpy, w, "_NET_WM_WINDOW_TYPE", type, 1);
    poser_atomes(dpy, w, "_NET_WM_STATE", etat, 4);

    /* sur tous les bureaux virtuels */
    unsigned long tous = 0xFFFFFFFF;
    XChangeProperty(dpy, w, XInternAtom(dpy, "_NET_WM_DESKTOP", False), XA_CARDINAL, 32,
                    PropModeReplace, (unsigned char *)&tous, 1);

    /* 2 = ne jamais court-circuiter le compositeur : sinon une fenêtre plein écran
       peut s'afficher par-dessus tout, barre du haut comprise */
    unsigned long jamais = 2;
    XChangeProperty(dpy, w, XInternAtom(dpy, "_NET_WM_BYPASS_COMPOSITOR", False), XA_CARDINAL, 32,
                    PropModeReplace, (unsigned char *)&jamais, 1);

    XClassHint classe = {"fond-vivant", "FondVivant"};
    XSetClassHint(dpy, w, &classe);
    XStoreName(dpy, w, "Fond Vivant");

    /* position et taille imposées : le gestionnaire de fenêtres ne doit rien déplacer */
    XSizeHints *taille = XAllocSizeHints();
    taille->flags = USPosition | USSize | PMinSize | PMaxSize;
    taille->x = x;
    taille->y = y;
    taille->min_width = taille->max_width = l;
    taille->min_height = taille->max_height = h;
    XSetWMNormalHints(dpy, w, taille);
    XFree(taille);

    /* zone de saisie vide : les clics traversent jusqu'aux icônes et au menu du bureau */
    XShapeCombineRectangles(dpy, w, ShapeInput, 0, 0, NULL, 0, ShapeSet, Unsorted);

    XMapWindow(dpy, w);
    XMoveResizeWindow(dpy, w, x, y, (unsigned)l, (unsigned)h);
    XFlush(dpy);

    printf("WID %lu\n", (unsigned long)w);
    fflush(stdout);

    /* rester sous les icônes du bureau, même quand elles sont recréées */
    Atom pile = XInternAtom(dpy, "_NET_CLIENT_LIST_STACKING", False);
    passer_sous_les_icones(dpy, w, heure_serveur(dpy, w));
    XSelectInput(dpy, DefaultRootWindow(dpy), PropertyChangeMask);

    int fd_x = ConnectionNumber(dpy);
    char ligne[128];
    for (;;) {
        while (XPending(dpy)) {
            XEvent ev;
            XNextEvent(dpy, &ev);
            if (ev.type == PropertyNotify && ev.xproperty.atom == pile)
                passer_sous_les_icones(dpy, w, ev.xproperty.time);
        }
        fd_set lecture;
        FD_ZERO(&lecture);
        FD_SET(fd_x, &lecture);
        FD_SET(STDIN_FILENO, &lecture);
        if (select(fd_x + 1, &lecture, NULL, NULL, NULL) < 0)
            break;
        if (FD_ISSET(STDIN_FILENO, &lecture)) {
            ssize_t n = read(STDIN_FILENO, ligne, sizeof ligne - 1);
            if (n <= 0)
                break; /* le lecteur a disparu */
            ligne[n] = '\0';
            if (strncmp(ligne, "quitter", 7) == 0)
                break;
        }
    }
    XDestroyWindow(dpy, w);
    XCloseDisplay(dpy);
    return 0;
}

int main(int argc, char **argv)
{
    int x, y, l, h;
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) {
        fprintf(stderr, "impossible d'ouvrir l'affichage X11 (session Wayland ?)\n");
        return 1;
    }
    if (argc == 2 && strcmp(argv[1], "--ecrans") == 0)
        return lister_ecrans(dpy);
    if (argc == 5 && lire_geometrie(argv, &x, &y, &l, &h))
        return creer_fond(dpy, x, y, l, h);
    fprintf(stderr, "usage : fv-bureau --ecrans | fv-bureau X Y LARGEUR HAUTEUR\n");
    return 2;
}
#endif
