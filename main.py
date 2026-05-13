# ================================================================
#  main.py  –  3D Model Viewer  (PyScript / Pyodide)
#  Beží priamo v prehliadači, žiadny server nie je potrebný.
#
#  Čo tento súbor robí:
#    - parsuje .obj súbor (vertexy, normály, plochy)
#    - implementuje jednoduchú 3D → 2D projekciu (perspektíva)
#    - vykresľuje wireframe aj základný „flat-shaded" solid mód
#    - reaguje na myš (rotácia, zoom) a klávesy (R, L)
#    - komunikuje s HTML canvasom cez JavaScript bridge
# ================================================================

import math
import json
from pyodide.ffi import create_proxy   # Proxy pre JS event listenery
from js import document, window, console, Object  # JS globály


# ================================================================
#  GLOBÁLNY STAV APLIKÁCIE
# ================================================================

# Aktuálny 3D model uložený ako slovník
stav = {
    "vertexy":  [],          # zoznam (x, y, z) – surové 3D body
    "plochy":   [],          # zoznam zoznamov indexov vertexov
    "nazov":    "demo_kocka",
    "nacitany": False,
}

# Stav kamery / pohľadu
kamera = {
    "rot_x":    0.25,        # Rotácia okolo osi X (radiány)
    "rot_y":    0.45,        # Rotácia okolo osi Y (radiány)
    "zoom":     1.0,         # Faktor priblíženia
    "wireframe": True,       # True = drôtový mód, False = solid
}

# Stav ťahania myši
mys = {
    "tahanie":  False,
    "posl_x":   0,
    "posl_y":   0,
}


# ================================================================
#  DEMO MODEL  –  kocka (fallback keď nie je nahratý .obj)
# ================================================================

DEMO_VERTEXY = [
    (-1, -1, -1), ( 1, -1, -1), ( 1,  1, -1), (-1,  1, -1),  # zadná stena
    (-1, -1,  1), ( 1, -1,  1), ( 1,  1,  1), (-1,  1,  1),  # predná stena
]

DEMO_PLOCHY = [
    [0, 1, 2, 3],   # zadná
    [4, 5, 6, 7],   # predná
    [0, 1, 5, 4],   # spodná
    [2, 3, 7, 6],   # horná
    [0, 3, 7, 4],   # ľavá
    [1, 2, 6, 5],   # pravá
]


def nacitaj_demo():
    """Naplní globálny stav demo kockou."""
    stav["vertexy"]  = list(DEMO_VERTEXY)
    stav["plochy"]   = list(DEMO_PLOCHY)
    stav["nazov"]    = "demo_kocka"
    stav["nacitany"] = True
    aktualizuj_info_panel()
    vykresli()


# ================================================================
#  PARSER .OBJ SÚBOROV
# ================================================================

def parsuj_obj(obsah: str, nazov: str = "model"):
    """
    Parsuje textový obsah .obj súboru.

    Spracúva:
      v  x y z       → vertex (bod v priestore)
      f  i j k ...   → plocha (trojuholník alebo polygón)
                        Indexy môžu byť vo formáte  i  alebo  i/t  alebo  i/t/n

    Ignoruje: normály (vn), UV súradnice (vt), materiály, komentáre.

    Args:
        obsah:  Celý textový obsah .obj súboru.
        nazov:  Meno súboru (zobrazené v info paneli).

    Returns:
        True ak parsovanie prebehlo bez chyby, inak False.
    """
    nove_vertexy = []
    nove_plochy  = []

    for cislo_riadku, riadok in enumerate(obsah.splitlines(), 1):
        riadok = riadok.strip()

        # Preskočiť prázdne riadky a komentáre
        if not riadok or riadok.startswith("#"):
            continue

        casti = riadok.split()
        typ   = casti[0].lower()

        # ---- Vertex ----
        if typ == "v" and len(casti) >= 4:
            try:
                x, y, z = float(casti[1]), float(casti[2]), float(casti[3])
                nove_vertexy.append((x, y, z))
            except ValueError:
                console.warn(f"[OBJ] Riadok {cislo_riadku}: chybný vertex '{riadok}'")

        # ---- Plocha ----
        elif typ == "f" and len(casti) >= 4:
            indexy = []
            chyba  = False
            for token in casti[1:]:
                # Token môže byť  "1"  alebo  "1/2"  alebo  "1/2/3"
                try:
                    idx = int(token.split("/")[0])
                    # .obj indexuje od 1, Python od 0
                    idx = idx - 1 if idx > 0 else len(nove_vertexy) + idx
                    indexy.append(idx)
                except ValueError:
                    console.warn(f"[OBJ] Riadok {cislo_riadku}: chybný index '{token}'")
                    chyba = True
                    break
            if not chyba and len(indexy) >= 3:
                nove_plochy.append(indexy)

    if not nove_vertexy:
        zobraz_chybu("Súbor neobsahuje žiadne vertexy (v x y z).")
        return False

    if not nove_plochy:
        zobraz_chybu("Súbor neobsahuje žiadne plochy (f i j k).")
        return False

    # Uložiť do globálneho stavu
    stav["vertexy"]  = nove_vertexy
    stav["plochy"]   = nove_plochy
    stav["nazov"]    = nazov.replace(".obj", "")
    stav["nacitany"] = True

    # Automaticky vycentrovať a normalizovať veľkosť modelu
    normalizuj_model()
    aktualizuj_info_panel()
    vykresli()
    return True


def normalizuj_model():
    """
    Vycentruje model do počiatku súradníc a škáluje ho
    tak, aby sa zmestil do kocky s rozmerom 2×2×2.
    Zabezpečuje, že rôzne modely budú mať podobnú veľkosť na obrazovke.
    """
    if not stav["vertexy"]:
        return

    xs = [v[0] for v in stav["vertexy"]]
    ys = [v[1] for v in stav["vertexy"]]
    zs = [v[2] for v in stav["vertexy"]]

    # Stred ohraničujúcej krabice (bounding box)
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    cz = (min(zs) + max(zs)) / 2

    # Polomer ohraničujúcej gule
    polomer = max(
        max(xs) - min(xs),
        max(ys) - min(ys),
        max(zs) - min(zs),
    ) / 2

    if polomer == 0:
        polomer = 1

    # Aplikovať posun a škálovanie
    stav["vertexy"] = [
        ((x - cx) / polomer, (y - cy) / polomer, (z - cz) / polomer)
        for x, y, z in stav["vertexy"]
    ]


# ================================================================
#  3D MATEMATIKA  –  rotácia, projekcia
# ================================================================

def rotuj_bod(x, y, z, rx, ry):
    """
    Aplikuje dve rotácie na bod (x, y, z):
      rx  = rotácia okolo osi X (pitch – naklonenie hore/dole)
      ry  = rotácia okolo osi Y (yaw   – otočenie doľava/doprava)

    Vzorce pochádzajú z rotačných matíc:
      Rx = [[1,0,0],[0,cos,-sin],[0,sin,cos]]
      Ry = [[cos,0,sin],[0,1,0],[-sin,0,cos]]

    Returns:
        Trojica (x', y', z') po rotácii.
    """
    # Rotácia okolo X
    cos_x, sin_x = math.cos(rx), math.sin(rx)
    y1 =  y * cos_x - z * sin_x
    z1 =  y * sin_x + z * cos_x

    # Rotácia okolo Y
    cos_y, sin_y = math.cos(ry), math.sin(ry)
    x2 =  x * cos_y + z1 * sin_y
    z2 = -x * sin_y + z1 * cos_y

    return x2, y1, z2


def perspektivna_projekcia(x, y, z, sirka, vyska, zoom):
    """
    Premení 3D bod na 2D súradnice obrazovky pomocou
    perspektívnej projekcie.

    Vzorec:
        px = cx + (x / (z + d)) * f
        py = cy - (y / (z + d)) * f   (Y je invertované – canvas má Y nadol)

    kde:
        d  = vzdalenosť kamery od scény (perspektívna hĺbka)
        f  = ohnisková vzdialenosť × zoom
        cx, cy = stred canvasu

    Returns:
        Dvojica (px, py) – súradnice pixelu na canvase.
        None ak je bod za kamerou (z + d <= 0).
    """
    d = 3.0           # Vzdialenosť kamery
    f = 400 * zoom    # Ohnisková vzdialenosť (zoom škáluje)

    menovatel = z + d
    if menovatel <= 0.01:
        return None   # Bod je za kamerou → preskočiť

    px = sirka  / 2 + (x / menovatel) * f
    py = vyska  / 2 - (y / menovatel) * f   # Invertujeme Y
    return px, py


def vypocitaj_normal_plochy(body_3d):
    """
    Vypočíta normálový vektor plochy pomocou krížového súčinu
    (cross product) dvoch hrán plochy.

    Normála určuje, ktorým smerom plocha „mieri" –
    používa sa pre back-face culling a tienenie.

    Args:
        body_3d: Zoznam aspoň 3 trojíc (x, y, z).

    Returns:
        Trojica (nx, ny, nz) – normálový vektor (môže byť nenormalizovaný).
    """
    if len(body_3d) < 3:
        return (0, 0, 1)

    ax, ay, az = body_3d[1][0]-body_3d[0][0], body_3d[1][1]-body_3d[0][1], body_3d[1][2]-body_3d[0][2]
    bx, by, bz = body_3d[2][0]-body_3d[0][0], body_3d[2][1]-body_3d[0][1], body_3d[2][2]-body_3d[0][2]

    nx = ay*bz - az*by
    ny = az*bx - ax*bz
    nz = ax*by - ay*bx
    return (nx, ny, nz)


# ================================================================
#  VYKRESĽOVANIE  –  canvas
# ================================================================

def ziskaj_canvas_a_kontext():
    """Vráti canvas element a jeho 2D kontext."""
    canvas = document.getElementById("canvas3d")
    ctx    = canvas.getContext("2d")
    return canvas, ctx


def vykresli():
    """
    Hlavná vykresľovacia funkcia.
    Volá sa pri každej zmene stavu (rotácia, zoom, nový model).

    Algoritmus:
      1. Vymaže canvas
      2. Pre každý vertex aplikuje rotáciu + projekciu
      3. Zoradie plochy podľa hĺbky (painter's algorithm)
      4. Vykreslí každú plochu (wireframe alebo solid)
    """
    canvas, ctx = ziskaj_canvas_a_kontext()
    W = canvas.width
    H = canvas.height

    # Vymazať canvas
    ctx.clearRect(0, 0, W, H)

    if not stav["vertexy"]:
        return

    rx   = kamera["rot_x"]
    ry   = kamera["rot_y"]
    zoom = kamera["zoom"]
    wire = kamera["wireframe"]

    # ---- Krok 1: Pretransformovať všetky vertexy ----
    # Každý vertex rotujeme a premietame do 2D
    body_3d_rotovane = []   # Po rotácii (stále 3D – potrebné pre hĺbku a normály)
    body_2d          = []   # Po projekcii (2D pixely)

    for (x, y, z) in stav["vertexy"]:
        rx3, ry3, rz3 = rotuj_bod(x, y, z, rx, ry)
        body_3d_rotovane.append((rx3, ry3, rz3))
        proj = perspektivna_projekcia(rx3, ry3, rz3, W, H, zoom)
        body_2d.append(proj)

    # ---- Krok 2: Zoradiť plochy podľa priemernej Z hĺbky ----
    # Painter's algorithm: kreslíme od najvzdialenejšieho k najbližšiemu
    plochy_s_hlbkou = []
    for plocha in stav["plochy"]:
        # Filtrujeme indexy mimo rozsah (opatrnosť pri neplatných .obj)
        platne = [i for i in plocha if 0 <= i < len(body_3d_rotovane)]
        if len(platne) < 3:
            continue

        priem_z = sum(body_3d_rotovane[i][2] for i in platne) / len(platne)
        plochy_s_hlbkou.append((priem_z, platne))

    # Zoradiť od najvzdialenejšej (najväčší Z) k najbližšej
    plochy_s_hlbkou.sort(key=lambda p: p[0], reverse=True)

    # ---- Krok 3: Vykresliť každú plochu ----
    for (priem_z, platne) in plochy_s_hlbkou:

        # Premietnuté 2D body plochy
        pts_2d = [body_2d[i] for i in platne]

        # Preskočiť ak je ktorýkoľvek bod za kamerou
        if any(p is None for p in pts_2d):
            continue

        if wire:
            # ---- WIREFRAME MÓD ----
            ctx.beginPath()
            ctx.moveTo(pts_2d[0][0], pts_2d[0][1])
            for pt in pts_2d[1:]:
                ctx.lineTo(pt[0], pt[1])
            ctx.closePath()
            ctx.strokeStyle = "#00e5ff"   # Tyrkysová farba hrán
            ctx.lineWidth   = 0.8
            ctx.stroke()

        else:
            # ---- SOLID MÓD s jednoduchým flat-shaded tienením ----

            # Výpočet normály plochy (po rotácii)
            body_plochy_3d = [body_3d_rotovane[i] for i in platne]
            nx, ny, nz = vypocitaj_normal_plochy(body_plochy_3d)

            # Normalizácia normálového vektora
            dlzka = math.sqrt(nx*nx + ny*ny + nz*nz)
            if dlzka > 0:
                nx, ny, nz = nx/dlzka, ny/dlzka, nz/dlzka

            # Smer svetla (svetlo prichádza zľava-zhora-spredu)
            lx, ly, lz = 0.5, 0.8, 1.0
            ll = math.sqrt(lx*lx + ly*ly + lz*lz)
            lx, ly, lz = lx/ll, ly/ll, lz/ll

            # Difúzne tienenie: dot product normály a smeru svetla
            # Clampujeme na [0.1, 1.0] aby tienené časti neboli úplne čierne
            intenzita = max(0.1, min(1.0, nx*lx + ny*ly + nz*lz))

            # Back-face culling: ak Z normály mieri od kamery, preskočiť
            # (plocha nie je viditeľná)
            if nz > 0:
                continue

            # Farba plochy: modrasto-sivá so simulovaným tienením
            r = int(40  + intenzita * 60)
            g = int(80  + intenzita * 100)
            b = int(120 + intenzita * 100)

            ctx.beginPath()
            ctx.moveTo(pts_2d[0][0], pts_2d[0][1])
            for pt in pts_2d[1:]:
                ctx.lineTo(pt[0], pt[1])
            ctx.closePath()
            ctx.fillStyle   = f"rgb({r},{g},{b})"
            ctx.fill()

            # Hrany aj v solid móde (tenšie)
            ctx.strokeStyle = "rgba(0,229,255,0.25)"
            ctx.lineWidth   = 0.4
            ctx.stroke()


# ================================================================
#  INFO PANEL
# ================================================================

def aktualizuj_info_panel():
    """Aktualizuje HTML elementy info panela na základe aktuálneho stavu."""
    document.getElementById("info-nazov").textContent   = stav["nazov"]
    document.getElementById("info-vertexy").textContent = str(len(stav["vertexy"]))
    document.getElementById("info-plochy").textContent  = str(len(stav["plochy"]))
    document.getElementById("info-stav").textContent    = "✓ Načítaný" if stav["nacitany"] else "— Čakám na model"
    styl = document.getElementById("info-stav").style
    styl.color = "#00e5ff" if stav["nacitany"] else "#888"


def zobraz_chybu(sprava: str):
    """Zobrazí chybovú správu v info paneli."""
    document.getElementById("info-stav").textContent = "✗ " + sprava
    document.getElementById("info-stav").style.color = "#ff4444"
    console.error("[3D Viewer] " + sprava)


# ================================================================
#  EVENT HANDLERY  –  myš a klávesnica
# ================================================================

def on_mousedown(event):
    """Stlačenie ľavého tlačidla myši → začiatok ťahania."""
    mys["tahanie"] = True
    mys["posl_x"]  = event.clientX
    mys["posl_y"]  = event.clientY
    event.preventDefault()


def on_mouseup(event):
    """Uvoľnenie tlačidla myši → koniec ťahania."""
    mys["tahanie"] = False


def on_mousemove(event):
    """
    Pohyb myšou počas ťahania → rotácia modelu.
    Rozdiel polohy myši sa prevedie na zmenu rotačných uhlov.
    """
    if not mys["tahanie"]:
        return

    dx = event.clientX - mys["posl_x"]
    dy = event.clientY - mys["posl_y"]

    citlivost = 0.008   # Radiány na pixel

    kamera["rot_y"] += dx * citlivost
    kamera["rot_x"] += dy * citlivost

    # Obmedzenie vertikálneho uhla (aby sa model „nepreklopil")
    kamera["rot_x"] = max(-math.pi / 2, min(math.pi / 2, kamera["rot_x"]))

    mys["posl_x"] = event.clientX
    mys["posl_y"] = event.clientY

    vykresli()


def on_wheel(event):
    """
    Otočenie kolieska myši → zoom.
    deltaY > 0 = scroll nadol = oddialenie.
    """
    delta = event.deltaY
    faktor = 1.1 if delta > 0 else 0.9
    kamera["zoom"] = max(0.1, min(10.0, kamera["zoom"] * faktor))
    vykresli()
    event.preventDefault()


def on_keydown(event):
    """
    Klávesové skratky:
      R  → reset kamery
      L  → prepnutie wireframe / solid
    """
    klaves = event.key.upper()

    if klaves == "R":
        kamera["rot_x"]    = 0.25
        kamera["rot_y"]    = 0.45
        kamera["zoom"]     = 1.0
        vykresli()

    elif klaves == "L":
        kamera["wireframe"] = not kamera["wireframe"]
        # Aktualizovať štítok tlačidla
        btn = document.getElementById("btn-wireframe")
        if btn:
            btn.textContent = "■ Solid" if kamera["wireframe"] else "⬡ Wireframe"
        vykresli()


# ================================================================
#  DRAG & DROP  a  FILE INPUT
# ================================================================

def nacitaj_subor_text(obsah: str, nazov: str):
    """Spracuje textový obsah .obj súboru."""
    document.getElementById("info-stav").textContent = "⏳ Parsovanie..."
    document.getElementById("info-stav").style.color = "#ffcc00"
    parsuj_obj(obsah, nazov)


def on_dragover(event):
    """Povolí drop operáciu (bez toho by prehliadač drag neakceptoval)."""
    event.preventDefault()
    event.dataTransfer.dropEffect = "copy"


def on_drop(event):
    """
    Spracovanie súboru pretiahnutého na canvas.
    Overí príponu .obj a načíta obsah súboru.
    """
    event.preventDefault()
    subory = event.dataTransfer.files
    if subory.length == 0:
        return

    subor = subory.item(0)
    nazov = subor.name

    # Validácia prípony
    if not nazov.lower().endswith(".obj"):
        zobraz_chybu(f"Nepodporovaný formát: '{nazov}'. Nahrај .obj súbor.")
        return

    # Načítanie súboru cez FileReader (asynchrónne)
    reader = window.FileReader.new()

    def on_load(evt):
        obsah = evt.target.result
        nacitaj_subor_text(obsah, nazov)

    reader.onload = create_proxy(on_load)
    reader.readAsText(subor)


def on_file_input_change(event):
    """
    Spracovanie súboru vybraného cez tlačidlo „Vybrať .obj".
    Rovnaká logika ako drag & drop.
    """
    subory = event.target.files
    if subory.length == 0:
        return

    subor = subory.item(0)
    nazov = subor.name

    if not nazov.lower().endswith(".obj"):
        zobraz_chybu(f"Nepodporovaný formát: '{nazov}'. Vyber .obj súbor.")
        return

    reader = window.FileReader.new()

    def on_load(evt):
        obsah = evt.target.result
        nacitaj_subor_text(obsah, nazov)

    reader.onload = create_proxy(on_load)
    reader.readAsText(subor)


# ================================================================
#  TLAČIDLO WIREFRAME (HTML)
# ================================================================

def on_wireframe_click(event):
    """Prepne wireframe/solid mód po kliknutí na tlačidlo."""
    kamera["wireframe"] = not kamera["wireframe"]
    btn = document.getElementById("btn-wireframe")
    if btn:
        btn.textContent = "■ Solid" if kamera["wireframe"] else "⬡ Wireframe"
    vykresli()


def on_reset_click(event):
    """Resetuje kameru po kliknutí na tlačidlo."""
    kamera["rot_x"] = 0.25
    kamera["rot_y"] = 0.45
    kamera["zoom"]  = 1.0
    vykresli()


# ================================================================
#  INICIALIZÁCIA  –  spustí sa raz pri načítaní stránky
# ================================================================

def init():
    """
    Zaregistruje všetky event listenery a načíta demo model.
    Táto funkcia je vstupný bod celej Python logiky.
    """
    canvas = document.getElementById("canvas3d")

    # Nastaviť veľkosť canvasu podľa jeho CSS veľkosti
    canvas.width  = canvas.offsetWidth  or 800
    canvas.height = canvas.offsetHeight or 600

    # ---- Registrácia myšových udalostí ----
    canvas.addEventListener("mousedown",  create_proxy(on_mousedown))
    canvas.addEventListener("mouseup",    create_proxy(on_mouseup))
    canvas.addEventListener("mousemove",  create_proxy(on_mousemove))
    canvas.addEventListener("wheel",      create_proxy(on_wheel), Object.fromEntries([["passive", False]]))

    # ---- Drag & drop na canvas ----
    canvas.addEventListener("dragover",   create_proxy(on_dragover))
    canvas.addEventListener("drop",       create_proxy(on_drop))

    # ---- Klávesnica (globálne) ----
    document.addEventListener("keydown",  create_proxy(on_keydown))

    # ---- File input ----
    file_input = document.getElementById("file-input")
    if file_input:
        file_input.addEventListener("change", create_proxy(on_file_input_change))

    # ---- Tlačidlá ----
    btn_wire = document.getElementById("btn-wireframe")
    if btn_wire:
        btn_wire.addEventListener("click", create_proxy(on_wireframe_click))

    btn_reset = document.getElementById("btn-reset")
    if btn_reset:
        btn_reset.addEventListener("click", create_proxy(on_reset_click))

    # ---- Načítať demo model ----
    nacitaj_demo()
    console.log("[3D Viewer] Inicializácia dokončená.")


# Spustenie inicializácie
init()
