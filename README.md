# 3D Model Viewer – Semestrálny projekt (Časť B)

> **Client-side** real-time 3D prehliadač modelov v Pythone bežiaci priamo v prehliadači  
> bez servera, bez backendu, bez inštalácie.

---

## Popis projektu

Webová aplikácia, ktorá umožňuje načítať a interaktívne zobraziť 3D model vo formáte `.obj`  
priamo v prehliadači. Celá logika je napísaná v **Pythone** a beží cez **PyScript / Pyodide**  
(Python skompilovaný do WebAssembly). Vykresľovanie prebieha na **HTML5 Canvas**.

---

## Štruktúra projektu

```
Moj_3D_Viewer/
├── index.html    ← Hlavná stránka, načíta PyScript a HTML rozhranie
├── style.css     ← Dizajn (CSS, bez externých frameworkov)
├── main.py       ← Python logika: parser .obj, 3D projekcia, renderer, vstup
└── README.md     ← Tento súbor
```

---

## Technológie

| Čo | Prečo |
|---|---|
| **Python 3 (PyScript / Pyodide)** | Hlavná logika bežiaca v prehliadači cez WebAssembly |
| **HTML5 Canvas 2D API** | Vykresľovanie 3D scény pixel po pixeli |
| **Vanilla JavaScript** | Iba nutné minimum: skrytie loading screenu, drag CSS |
| **Žiadny server** | Stačí otvoriť index.html v prehliadači |

---

## Spustenie

### Možnosť 1 – lokálny HTTP server (odporúčané)

PyScript potrebuje HTTP server kvôli CORS pri načítaní `.py` súboru.

```bash
# Python 3
cd Moj_3D_Viewer
python -m http.server 8080
```

Potom otvor v prehliadači: **http://localhost:8080**

### Možnosť 2 – VS Code Live Server

Otvor priečinok `Moj_3D_Viewer` vo VS Code a spusti **Live Server** (rozšírenie).

### Možnosť 3 – GitHub Pages / Netlify Drop

Nahraj obsah priečinka na GitHub Pages alebo pretiahni na [netlify.com/drop](https://app.netlify.com/drop).  
Projekt funguje ako statická stránka – žiadna serverová konfigurácia nie je potrebná.

### Možnosť 4 – hlavný portál

Ak je projekt súčasťou väčšieho portálu (napr. Flask app pre iné projekty),  
pridaj odkaz na `Moj_3D_Viewer/index.html`. Odkaz „← Späť" v aplikácii mieri na `/`.

---

## Čo aplikácia dokáže

- **Načítanie .obj súboru** – tlačidlom alebo drag & drop priamo na canvas
- **Validácia prípony** – akceptuje iba `.obj`, iné formáty odmietne s chybou
- **Demo model** – kocka sa zobrazí automaticky ak nie je nahratý žiadny model
- **Rotácia** – ťahanie ľavým tlačidlom myši
- **Zoom** – koliesko myši
- **Reset kamery** – klávesa R alebo tlačidlo ↺ Reset
- **Wireframe / Solid mód** – klávesa L alebo tlačidlo ⬡ Wireframe
- **Info panel** – názov modelu, počet vertexov, počet plôch, stav načítania

---

## Princípy implementácie (pre obhajobu)

### Parser .obj
Súbor sa číta riadok po riadku. Riadky začínajúce `v` sú vertexy (x, y, z).  
Riadky `f` sú plochy – indexy vertexov (od 1, nie od 0 ako v Pythone).  
Token `1/2/3` sa spracuje rozdelením podľa `/` a použije sa prvé číslo (index vertexu).

### 3D projekcia
Každý vertex sa najprv **rotuje** pomocou rotačných matíc okolo osi X a Y.  
Potom sa aplikuje **perspektívna projekcia**:

```
px = šírka/2 + (x / (z + hĺbka)) × ohnisko
py = výška/2 − (y / (z + hĺbka)) × ohnisko
```

Vzorec zachytáva perspektívu: vzdialené objekty sú menšie.

### Painter's algorithm
Plochy sa vykresľujú od najvzdialenejšej k najbližšej (zoradenie podľa priemernej Z).  
Tým sa zabezpečí správne prekrývanie bez potreby Z-bufferu.

### Flat shading
V solid móde sa pre každú plochu vypočíta **normálový vektor** (cross product dvoch hrán).  
Intenzita farby = skalárny súčin (dot product) normály a smeru svetla.  
**Back-face culling** – plochy odvrátené od kamery sa nevykreslia.

---

## Požiadavky prehliadača

- Moderný prehliadač s podporou WebAssembly: Chrome 88+, Firefox 89+, Edge 88+, Safari 15+
- Internetové pripojenie pre prvé načítanie PyScript/Pyodide (~8 MB, potom cache)
- Prvé načítanie trvá 2–5 sekúnd (sťahovanie Pyodide)

---

## Obmedzenia

- Nie je vhodné pre modely s >50 000 plochami (Canvas 2D je pomalší ako WebGL)
- Nepodporuje textúry ani MTL materiály (plánované rozšírenie)
- Nepodporuje animácie
