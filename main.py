# ================================================================
#  main.py  –  3D Model Viewer v2  (PyScript / Pyodide)
#  100% client-side, beží priamo v prehliadači bez servera.
#
#  Novinky v tejto verzii:
#    - Spracovanie normál z OBJ (vn) + dopočítanie ak chýbajú
#    - Lambert flat shading bez viditeľných hrán v solid móde
#    - Blender-like ovládanie: MMB orbit, Shift+MMB pan, koliesko zoom
#    - Záložné ovládanie: LMB orbit, Shift+LMB pan
#    - Pan posúva kamerový offset (nie model)
#    - Výber farby / materiálu modelu
#    - Numpad skratky: 1=front, 3=side, 7=top
#    - Painter's algorithm pre správne poradie plôch
# ================================================================

import math
from pyodide.ffi import create_proxy
from js import document, window, console, Object


# ================================================================
#  GLOBÁLNY STAV MODELU
# ================================================================

model = {
    "vertexy":      [],   # list of (x,y,z)  – pozície vertexov
    "normals_obj":  [],   # list of (nx,ny,nz) – normály z OBJ (vn riadky)
    "plochy":       [],   # list of { "vi": [...], "ni": [...] }
                          #   vi = indexy vertexov (0-based)
                          #   ni = indexy normál  (0-based), môže byť []
    "face_normals": [],   # dopočítané face-normály (1 na plochu)
    "ma_obj_normals": False,  # či OBJ obsahoval vn záznamy
    "nazov":        "demo_kocka",
    "nacitany":     False,
}

# ================================================================
#  STAV KAMERY / POHĽADU
# ================================================================

kamera = {
    "rot_x":    0.4,      # pitch – rotácia okolo X (radiány)
    "rot_y":    0.6,      # yaw   – rotácia okolo Y (radiány)
    "zoom":     1.0,      # faktor priblíženia
    "pan_x":    0.0,      # posun pohľadu – X (world jednotky)
    "pan_y":    0.0,      # posun pohľadu – Y (world jednotky)
    "wireframe": False,   # False = solid, True = wireframe
    "material": (0.55, 0.65, 0.75),  # základná RGB farba modelu (0–1)
}

# Predvolené pohľady (Blender numpad)
POHLADOVE_PRESET = {
    "1": (0.0,   0.0,   "predný"),
    "3": (0.0,   math.pi / 2, "bočný"),
    "7": (-math.pi / 2, 0.0, "horný"),
}

# Dostupné materiálové farby
MATERIALY = {
    "siva":    (0.55, 0.58, 0.62),
    "modra":   (0.20, 0.45, 0.80),
    "zelena":  (0.25, 0.65, 0.35),
    "cervena": (0.75, 0.22, 0.22),
    "oranzova":(0.85, 0.48, 0.12),
    "biela":   (0.85, 0.85, 0.85),
    "tmava":   (0.15, 0.17, 0.20),
}

# ================================================================
#  STAV MYŠI
# ================================================================

mys = {
    "tahanie_orbit": False,   # LMB alebo MMB bez Shift
    "tahanie_pan":   False,   # Shift + LMB alebo Shift + MMB
    "posl_x": 0,
    "posl_y": 0,
}


# ================================================================
#  DEMO MODEL  –  kocka s explicitnými normálami
# ================================================================

def nacitaj_demo():
    """Naplní stav demo kockou (8 vertexov, 6 plôch, 6 normál)."""
    vertexy = [
        (-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),
        (-1,-1, 1),(1,-1, 1),(1,1, 1),(-1,1, 1),
    ]
    # Outward-facing normály pre každú stenu kocky
    normals_obj = [
        (0,0,-1),(0,0,1),(0,-1,0),(0,1,0),(-1,0,0),(1,0,0),
    ]
    # Každá plocha odkazuje na 4 vertexy a 1 normálu (flat per-face)
    plochy = [
        {"vi":[0,3,2,1], "ni":[0,0,0,0]},   # zadná  (-Z)
        {"vi":[4,5,6,7], "ni":[1,1,1,1]},   # predná (+Z)
        {"vi":[0,1,5,4], "ni":[2,2,2,2]},   # spodná (-Y)
        {"vi":[2,3,7,6], "ni":[3,3,3,3]},   # horná  (+Y)
        {"vi":[0,4,7,3], "ni":[4,4,4,4]},   # ľavá   (-X)
        {"vi":[1,2,6,5], "ni":[5,5,5,5]},   # pravá  (+X)
    ]

    model["vertexy"]      = vertexy
    model["normals_obj"]  = normals_obj
    model["plochy"]       = plochy
    model["ma_obj_normals"] = True
    model["nazov"]        = "demo_kocka"
    model["nacitany"]     = True

    vypocitaj_face_normals()
    aktualizuj_info_panel()
    vykresli()


# ================================================================
#  PARSER OBJ
# ================================================================

def parsuj_obj(obsah: str, nazov: str = "model"):
    """
    Parsuje .obj súbor. Spracúva:
      v  x y z         – vertex
      vn nx ny nz       – normála vrcholu
      f  v/t/n  ...     – plocha (podporuje v, v/t, v//n, v/t/n)

    Normály z OBJ sa preferujú pred dopočítanými.
    Ak OBJ normály neobsahuje, dopočítajú sa face-normály.
    """
    nove_vertexy     = []
    nove_normals_obj = []
    nove_plochy      = []

    for r_idx, riadok in enumerate(obsah.splitlines(), 1):
        riadok = riadok.strip()
        if not riadok or riadok.startswith("#"):
            continue

        casti = riadok.split()
        typ   = casti[0].lower()

        # ---- Vertex (v) ----
        if typ == "v" and len(casti) >= 4:
            try:
                nove_vertexy.append((
                    float(casti[1]),
                    float(casti[2]),
                    float(casti[3]),
                ))
            except ValueError:
                console.warn(f"[OBJ] r.{r_idx}: chybný vertex")

        # ---- Normála (vn) ----
        elif typ == "vn" and len(casti) >= 4:
            try:
                nove_normals_obj.append((
                    float(casti[1]),
                    float(casti[2]),
                    float(casti[3]),
                ))
            except ValueError:
                console.warn(f"[OBJ] r.{r_idx}: chybná normála")

        # ---- Plocha (f) ----
        elif typ == "f" and len(casti) >= 4:
            vi_list = []
            ni_list = []
            chyba   = False

            for token in casti[1:]:
                # Token formáty: "1"  "1/2"  "1//3"  "1/2/3"
                casti_tok = token.split("/")
                try:
                    raw_v = int(casti_tok[0])
                    idx_v = raw_v - 1 if raw_v > 0 else len(nove_vertexy) + raw_v
                    vi_list.append(idx_v)
                except ValueError:
                    chyba = True
                    break

                # Normálový index (3. pozícia tokenu, môže chýbať)
                idx_n = None
                if len(casti_tok) >= 3 and casti_tok[2]:
                    try:
                        raw_n = int(casti_tok[2])
                        idx_n = raw_n - 1 if raw_n > 0 else len(nove_normals_obj) + raw_n
                    except ValueError:
                        pass
                ni_list.append(idx_n)

            if not chyba and len(vi_list) >= 3:
                # Ak niektorý n-index je None, zrušíme celý ni_list pre túto plochu
                has_all_n = all(n is not None for n in ni_list)
                nove_plochy.append({
                    "vi": vi_list,
                    "ni": ni_list if has_all_n else [],
                })

    if not nove_vertexy:
        zobraz_chybu("Súbor neobsahuje vertexy (v x y z).")
        return False
    if not nove_plochy:
        zobraz_chybu("Súbor neobsahuje plochy (f ...).")
        return False

    model["vertexy"]       = nove_vertexy
    model["normals_obj"]   = nove_normals_obj
    model["plochy"]        = nove_plochy
    model["ma_obj_normals"]= bool(nove_normals_obj)
    model["nazov"]         = nazov.replace(".obj","")
    model["nacitany"]      = True

    normalizuj_model()
    vypocitaj_face_normals()
    aktualizuj_info_panel()
    vykresli()
    return True


# ================================================================
#  NORMALIZÁCIA  –  centrovanie + škálovanie
# ================================================================

def normalizuj_model():
    """Vycentruje model a škáluje ho do jednotkovej gule (polomer ≈ 1)."""
    verts = model["vertexy"]
    if not verts:
        return
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    cx = (min(xs)+max(xs))/2
    cy = (min(ys)+max(ys))/2
    cz = (min(zs)+max(zs))/2
    r  = max(max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs)) / 2
    if r == 0:
        r = 1
    model["vertexy"] = [((x-cx)/r, (y-cy)/r, (z-cz)/r) for x,y,z in verts]


# ================================================================
#  VÝPOČET FACE-NORMÁL  (fallback alebo vždy pre painter sorting)
# ================================================================

def _cross(a, b):
    """Krížový súčin dvoch 3D vektorov."""
    return (
        a[1]*b[2] - a[2]*b[1],
        a[2]*b[0] - a[0]*b[2],
        a[0]*b[1] - a[1]*b[0],
    )

def _normalize(v):
    """Normalizuje 3D vektor na jednotkovú dĺžku."""
    d = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)
    if d < 1e-10:
        return (0.0, 0.0, 1.0)
    return (v[0]/d, v[1]/d, v[2]/d)

def _dot(a, b):
    """Skalárny súčin dvoch 3D vektorov."""
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

def vypocitaj_face_normals():
    """
    Pre každú plochu vypočíta face-normálu z prvých troch vertexov
    pomocou krížového súčinu. Výsledok uloží do model["face_normals"].

    Tieto normály sa používajú:
      a) pre flat shading ak OBJ nemá vn záznamy
      b) vždy pre painter's algorithm (z-sorting)
    """
    verts = model["vertexy"]
    fn    = []
    for pl in model["plochy"]:
        vi = pl["vi"]
        if len(vi) < 3:
            fn.append((0,0,1))
            continue
        # Dva hrany od prvého vertexu
        v0,v1,v2 = verts[vi[0]], verts[vi[1]], verts[vi[2]]
        e1 = (v1[0]-v0[0], v1[1]-v0[1], v1[2]-v0[2])
        e2 = (v2[0]-v0[0], v2[1]-v0[1], v2[2]-v0[2])
        fn.append(_normalize(_cross(e1, e2)))
    model["face_normals"] = fn


# ================================================================
#  3D MATEMATIKA  –  rotácia, projekcia
# ================================================================

def rotuj_bod(x, y, z, rx, ry):
    """
    Aplikuje rotáciu okolo osi X (pitch) a potom Y (yaw).
    Poradie: najprv X, potom Y – rovnaké ako Blender orbit.
    """
    # Rotácia okolo X
    cx, sx = math.cos(rx), math.sin(rx)
    y1 =  y*cx - z*sx
    z1 =  y*sx + z*cx
    # Rotácia okolo Y
    cy, sy = math.cos(ry), math.sin(ry)
    x2 =  x*cy + z1*sy
    z2 = -x*sy + z1*cy
    return (x2, y1, z2)


def rotuj_normal(nx, ny, nz, rx, ry):
    """Otočí normálový vektor rovnakou rotáciou ako body scény."""
    return rotuj_bod(nx, ny, nz, rx, ry)


def projektuj(x, y, z, W, H, zoom, pan_x, pan_y):
    """
    Perspektívna projekcia 3D bodu na 2D canvas.

    pan_x, pan_y posúvajú výsledok v obrazovkových pixeloch
    (aplikované po projekcii – zodpovedá Blender pan správaniu).

    Returns (px, py) alebo None ak je bod za kamerou.
    """
    d = 3.5           # vzdialenosť kamery
    f = 380 * zoom    # ohnisková vzdialenosť

    men = z + d
    if men < 0.01:
        return None

    px = W/2 + (x / men) * f + pan_x
    py = H/2 - (y / men) * f + pan_y
    return (px, py)


# ================================================================
#  SVETLO  –  smer a výpočet intenzity
# ================================================================

# Smer svetla vo world-space (fixný, prichádza zľava-zhora-spredu)
# Normalizovaný vektor
_SVETLO_DIR = _normalize((0.6, 0.9, 1.0))

# Ambientná zložka (minimálne osvetlenie aj tienených plôch)
_AMBIENT = 0.18

def lambert_intenzita(normal_ws):
    """
    Vypočíta Lambert difúznu intenzitu pre danú normálu vo world-space.

    Lambert model: I = max(0, dot(N, L)) + ambient
    Výsledok je clampovaný do [0, 1].

    Args:
        normal_ws: Normalizovaná normála vo world-space (tuple 3).
    Returns:
        Float v rozsahu [0, 1].
    """
    difuz = max(0.0, _dot(normal_ws, _SVETLO_DIR))
    return min(1.0, _AMBIENT + difuz * (1.0 - _AMBIENT))


def farba_plochy(intenzita, material_rgb):
    """
    Skonvertuje intenzitu osvetlenia a základnú farbu materiálu
    na CSS rgb() reťazec.

    Args:
        intenzita:   Float 0–1 z lambert_intenzita()
        material_rgb: Trojica (r,g,b) v rozsahu 0–1
    Returns:
        CSS string napr. "rgb(120,145,180)"
    """
    r, g, b = material_rgb
    ri = int(r * intenzita * 255)
    gi = int(g * intenzita * 255)
    bi = int(b * intenzita * 255)
    return f"rgb({ri},{gi},{bi})"


# ================================================================
#  VYKRESĽOVANIE
# ================================================================

def vykresli():
    """
    Hlavná vykresľovacia funkcia.

    Algoritmus:
      1. Transformuj všetky vertexy (rotácia + pan + projekcia)
      2. Pre každú plochu:
         a) Získaj normálu (z OBJ alebo dopočítanú)
         b) Otočí normálu rovnakou rotáciou ako model
         c) Back-face culling: preskočiť plochy odvrátené od kamery
            (nz_view > 0 znamená, že plocha mieri preč od diváka)
         d) Vypočítaj z-hĺbku plochy (priemerné z po rotácii)
      3. Zoradiť plochy podľa z-hĺbky (painter's algorithm)
      4. Vykresliť každú plochu (solid: fill bez stroke, wireframe: stroke)
    """
    canvas = document.getElementById("canvas3d")
    ctx    = canvas.getContext("2d")
    W, H   = canvas.width, canvas.height

    ctx.clearRect(0, 0, W, H)

    verts = model["vertexy"]
    plochy = model["plochy"]
    if not verts or not plochy:
        return

    rx   = kamera["rot_x"]
    ry   = kamera["rot_y"]
    zoom = kamera["zoom"]
    px_o = kamera["pan_x"]
    py_o = kamera["pan_y"]
    wire = kamera["wireframe"]
    mat  = kamera["material"]

    # ---- Krok 1: Transformácia vertexov ----
    # Každý vertex: rotácia → uloženie 3D (pre z-sort) → projekcia do 2D
    verts_rot = []   # Rotované 3D body (pre z-sort a back-face culling)
    verts_2d  = []   # Premietnuté 2D body (px, py) alebo None

    for (x,y,z) in verts:
        rx3, ry3, rz3 = rotuj_bod(x, y, z, rx, ry)
        verts_rot.append((rx3, ry3, rz3))
        verts_2d.append(projektuj(rx3, ry3, rz3, W, H, zoom, px_o, py_o))

    # ---- Krok 2: Príprava plôch – normála, hĺbka, culling ----
    plochy_na_kreslenie = []   # [(hlbka, plocha_dict, intenzita)]

    for i, pl in enumerate(plochy):
        vi = pl["vi"]
        ni = pl["ni"]

        # Preskočiť plochy s neplatnými vertexami
        if any(idx < 0 or idx >= len(verts_rot) for idx in vi):
            continue

        # -- Získať normálu pre tienenie --
        # Priorita: per-vertex normály z OBJ → per-face dopočítaná normála
        if ni and model["normals_obj"]:
            # Použijeme priemernú normálu z OBJ normál plochy
            # (pre flat shading stačí prvá, pre smooth by sme priemernili)
            sum_n = [0.0, 0.0, 0.0]
            valid_n = 0
            for nidx in ni:
                if 0 <= nidx < len(model["normals_obj"]):
                    nn = model["normals_obj"][nidx]
                    sum_n[0] += nn[0]
                    sum_n[1] += nn[1]
                    sum_n[2] += nn[2]
                    valid_n  += 1
            if valid_n > 0:
                norm_ws = _normalize((sum_n[0]/valid_n, sum_n[1]/valid_n, sum_n[2]/valid_n))
            else:
                norm_ws = model["face_normals"][i]
        else:
            # Fallback: dopočítaná face-normála
            norm_ws = model["face_normals"][i]

        # -- Otočiť normálu do view-space (rovnaká rotácia ako model) --
        norm_view = rotuj_normal(norm_ws[0], norm_ws[1], norm_ws[2], rx, ry)

        # -- Back-face culling --
        # V nášej projekcii kamera pozerá v smere -Z (do obrazovky).
        # Ak nz_view > 0, normála mieri k divákovi → plocha je viditeľná.
        # Ak nz_view <= 0, plocha je odvrátená → preskočíme ju.
        # POZNÁMKA: Znamienko závisí od orientácie normál.
        # Blender exportuje normály smerom VON z povrchu.
        nz_view = norm_view[2]
        if not wire and nz_view >= 0:
            # Solid mód: culling zapnutý
            continue

        # -- Priemerná Z hĺbka plochy (pre painter's algorithm) --
        hlbka = sum(verts_rot[idx][2] for idx in vi) / len(vi)

        # -- Intenzita osvetlenia (len pre solid mód) --
        if not wire:
            intenz = lambert_intenzita(norm_view)
        else:
            intenz = 1.0

        plochy_na_kreslenie.append((hlbka, pl, intenz))

    # ---- Krok 3: Painter's algorithm – od najvzdialenejšej ----
    # Plochy s väčším Z sú vzdialenejšie (kamera je na kladnom konci Z)
    plochy_na_kreslenie.sort(key=lambda t: t[0], reverse=True)

    # ---- Krok 4: Kreslenie ----
    for (hlbka, pl, intenz) in plochy_na_kreslenie:
        vi = pl["vi"]
        pts = [verts_2d[idx] for idx in vi]

        # Preskočiť ak je niektorý bod za kamerou (None)
        if any(p is None for p in pts):
            continue

        ctx.beginPath()
        ctx.moveTo(pts[0][0], pts[0][1])
        for pt in pts[1:]:
            ctx.lineTo(pt[0], pt[1])
        ctx.closePath()

        if wire:
            # ---- WIREFRAME: iba hrany, žiadna výplň ----
            ctx.strokeStyle = "#00e5ff"
            ctx.lineWidth   = 0.9
            ctx.stroke()
        else:
            # ---- SOLID: výplň + žiadne viditeľné hrany ----
            ctx.fillStyle = farba_plochy(intenz, mat)
            ctx.fill()
            # ŽIADNY stroke → žiadne viditeľné polygonové čiary


# ================================================================
#  INFO PANEL
# ================================================================

def aktualizuj_info_panel():
    """Aktualizuje všetky zobrazené štatistiky modelu v HTML paneli."""
    def set_text(eid, txt):
        el = document.getElementById(eid)
        if el:
            el.textContent = txt

    set_text("info-nazov",   model["nazov"])
    set_text("info-vertexy", str(len(model["vertexy"])))
    set_text("info-normals", str(len(model["normals_obj"])) +
             (" ✓ OBJ" if model["ma_obj_normals"] else " (dopočítané)"))
    set_text("info-plochy",  str(len(model["plochy"])))

    stav_el = document.getElementById("info-stav")
    if stav_el:
        if model["nacitany"]:
            stav_el.textContent = "✓ Načítaný"
            stav_el.style.color = "#00e5ff"
        else:
            stav_el.textContent = "— Čakám"
            stav_el.style.color = "#666"


def zobraz_chybu(sprava: str):
    """Zobrazí chybovú hlášku v info paneli."""
    el = document.getElementById("info-stav")
    if el:
        el.textContent = "✗ " + sprava
        el.style.color = "#ff4444"
    console.error("[3D Viewer] " + sprava)


# ================================================================
#  MYŠOVÉ UDALOSTI  –  Blender-like ovládanie
#
#  Blender schéma:
#    MMB drag            = orbit (rotácia okolo target)
#    Shift + MMB drag    = pan
#    Koliesko            = zoom
#    LMB drag            = orbit (fallback pre myši bez MMB)
#    Shift + LMB drag    = pan   (fallback)
# ================================================================

def _je_shift(event):
    """Vráti True ak je Shift stlačený."""
    return bool(event.shiftKey)

def _zacni_tahanie(event, je_pan):
    """Spoločná logika pre začiatok ťahania."""
    mys["posl_x"] = event.clientX
    mys["posl_y"] = event.clientY
    if je_pan:
        mys["tahanie_orbit"] = False
        mys["tahanie_pan"]   = True
    else:
        mys["tahanie_orbit"] = True
        mys["tahanie_pan"]   = False


def on_mousedown(event):
    """
    button == 0: LMB  → orbit, alebo pan ak je Shift
    button == 1: MMB  → orbit, alebo pan ak je Shift
    """
    btn = event.button
    if btn == 0 or btn == 1:
        _zacni_tahanie(event, _je_shift(event))
        event.preventDefault()


def on_mouseup(event):
    """Uvoľnenie akéhokoľvek tlačidla ukončí ťahanie."""
    mys["tahanie_orbit"] = False
    mys["tahanie_pan"]   = False


def on_mousemove(event):
    """
    Pohyb myšou:
      - orbit mode: zmení rot_x a rot_y
      - pan mode:   zmení pan_x a pan_y (posun v pixeloch obrazovky)
    """
    dx = event.clientX - mys["posl_x"]
    dy = event.clientY - mys["posl_y"]
    mys["posl_x"] = event.clientX
    mys["posl_y"] = event.clientY

    if mys["tahanie_orbit"]:
        # Citlivosť orbit: 0.007 rad/pixel (podobné Blenderu)
        kamera["rot_y"] += dx * 0.007
        # Clamp pitch aby sa model nepreklopil cez pól
        kamera["rot_x"] = max(-math.pi/2 + 0.01,
                          min( math.pi/2 - 0.01,
                               kamera["rot_x"] + dy * 0.007))
        vykresli()

    elif mys["tahanie_pan"]:
        # Pan citlivosť závisí od zoomu: pri väčšom zoome pomalší pan
        citlivost = 1.0 / max(0.1, kamera["zoom"])
        kamera["pan_x"] += dx * citlivost
        kamera["pan_y"] += dy * citlivost
        vykresli()


def on_wheel(event):
    """
    Koliesko myši = zoom.
    Faktor 1.1 / 0.9 per krok (rovnaké ako Blender scroll).
    """
    faktor = 1.12 if event.deltaY > 0 else 0.88
    kamera["zoom"] = max(0.05, min(20.0, kamera["zoom"] * faktor))
    vykresli()
    event.preventDefault()


def on_keydown(event):
    """
    Klávesové skratky (Blender-like):
      R        → reset pohľadu
      L        → wireframe toggle
      Numpad 1 → predný pohľad
      Numpad 3 → bočný pohľad
      Numpad 7 → horný pohľad
    """
    k = event.key

    if k.upper() == "R":
        reset_pohladu()

    elif k.upper() == "L":
        prepni_wireframe()

    elif k in ("1","3","7") and not _je_shift(event):
        # Numpad preset pohľady
        if k in POHLADOVE_PRESET:
            rx_p, ry_p, _ = POHLADOVE_PRESET[k]
            kamera["rot_x"] = rx_p
            kamera["rot_y"] = ry_p
            kamera["pan_x"] = 0.0
            kamera["pan_y"] = 0.0
            vykresli()


def reset_pohladu():
    """Vráti kameru na predvolenú pozíciu (rovnaké ako Blender Home)."""
    kamera["rot_x"] = 0.4
    kamera["rot_y"] = 0.6
    kamera["zoom"]  = 1.0
    kamera["pan_x"] = 0.0
    kamera["pan_y"] = 0.0
    vykresli()


def prepni_wireframe():
    """Prepne wireframe/solid a aktualizuje UI tlačidlo."""
    kamera["wireframe"] = not kamera["wireframe"]
    btn = document.getElementById("btn-wireframe")
    if btn:
        if kamera["wireframe"]:
            btn.textContent  = "■ Solid"
            btn.dataset.active = "true"
        else:
            btn.textContent  = "⬡ Wireframe"
            btn.dataset.active = "false"
    vykresli()


# ================================================================
#  DRAG & DROP  a  FILE INPUT
# ================================================================

def on_dragover(event):
    event.preventDefault()
    event.dataTransfer.dropEffect = "copy"


def on_drop(event):
    """Pretiahnutie .obj súboru na canvas."""
    event.preventDefault()
    subory = event.dataTransfer.files
    if subory.length == 0:
        return
    _spracuj_file(subory.item(0))


def on_file_input_change(event):
    """Výber súboru cez tlačidlo."""
    subory = event.target.files
    if subory.length == 0:
        return
    _spracuj_file(subory.item(0))
    # Reset input aby sa dal znova vybrať rovnaký súbor
    event.target.value = ""


def _spracuj_file(subor):
    """Spoločná logika pre drop aj file input."""
    nazov = subor.name
    if not nazov.lower().endswith(".obj"):
        zobraz_chybu(f"Len .obj formát! ('{nazov}' odmietnutý)")
        return

    stav_el = document.getElementById("info-stav")
    if stav_el:
        stav_el.textContent = "⏳ Parsovanie..."
        stav_el.style.color = "#ffcc00"

    reader = window.FileReader.new()
    def on_load(evt):
        parsuj_obj(evt.target.result, nazov)
    reader.onload = create_proxy(on_load)
    reader.readAsText(subor)


# ================================================================
#  VÝBER MATERIÁLU / FARBY
# ================================================================

def on_material_click(event):
    """
    Klik na farebné tlačidlo materiálu.
    Hodnota farby je uložená v data-rgb atribúte tlačidla
    vo formáte "r,g,b" (float 0–1).
    """
    tlacidlo = event.currentTarget
    rgb_str  = tlacidlo.dataset.rgb
    try:
        r, g, b = (float(x) for x in rgb_str.split(","))
        kamera["material"] = (r, g, b)
    except Exception:
        return

    # Vizuálne označenie aktívneho tlačidla
    for btn in document.querySelectorAll(".mat-btn"):
        btn.dataset.active = "false"
    tlacidlo.dataset.active = "true"

    vykresli()


# ================================================================
#  INICIALIZÁCIA
# ================================================================

def init():
    """
    Zaregistruje všetky event listenery.
    Volá sa raz pri načítaní stránky.
    """
    canvas = document.getElementById("canvas3d")

    # Nastaviť rozlíšenie canvasu podľa jeho CSS veľkosti
    w = canvas.offsetWidth  or 800
    h = canvas.offsetHeight or 560
    canvas.width  = w
    canvas.height = h

    # Predísť context menu pri MMB (stredné tlačidlo)
    canvas.addEventListener("contextmenu", create_proxy(lambda e: e.preventDefault()))

    # Myšové udalosti
    canvas.addEventListener("mousedown", create_proxy(on_mousedown))
    document.addEventListener("mouseup",   create_proxy(on_mouseup))
    document.addEventListener("mousemove", create_proxy(on_mousemove))
    canvas.addEventListener("wheel",     create_proxy(on_wheel),
                            Object.fromEntries([["passive", False]]))

    # Drag & drop
    canvas.addEventListener("dragover", create_proxy(on_dragover))
    canvas.addEventListener("drop",     create_proxy(on_drop))

    # Klávesnica
    document.addEventListener("keydown", create_proxy(on_keydown))

    # File input
    fi = document.getElementById("file-input")
    if fi:
        fi.addEventListener("change", create_proxy(on_file_input_change))

    # Tlačidlá toolbar
    b = document.getElementById("btn-wireframe")
    if b:
        b.addEventListener("click", create_proxy(lambda e: prepni_wireframe()))

    b = document.getElementById("btn-reset")
    if b:
        b.addEventListener("click", create_proxy(lambda e: reset_pohladu()))

    # Tlačidlá materiálov
    for btn in document.querySelectorAll(".mat-btn"):
        btn.addEventListener("click", create_proxy(on_material_click))

    # Preset pohľady (tlačidlá numpad)
    for k in ("1","3","7"):
        el = document.getElementById(f"btn-view-{k}")
        if el:
            def make_handler(key):
                def handler(e):
                    rx_p, ry_p, _ = POHLADOVE_PRESET[key]
                    kamera["rot_x"] = rx_p
                    kamera["rot_y"] = ry_p
                    kamera["pan_x"] = 0.0
                    kamera["pan_y"] = 0.0
                    vykresli()
                return handler
            el.addEventListener("click", create_proxy(make_handler(k)))

    # Demo model
    nacitaj_demo()
    console.log("[3D Viewer v2] Inicializácia OK")


init()