"""
Scraper de Toyota of North Miami (inventario nuevo, plataforma Dealer.com).

Ejecutar:
    python scraper_toyota_north_miami.py

- Solo agrega autos que ya estan en el lote ("live") y tienen al menos
  MIN_REAL_PHOTOS fotos reales del auto (las fotos genericas de fabrica
  se descartan).
- Baja solo la foto de portada (para la miniatura de la tarjeta); la
  galeria se muestra desde el servidor de fotos del dealer.
- Quita del catalogo los autos de este dealer que ya no aparecen en su
  inventario (vendidos).
- Al terminar genera las miniaturas (build_thumbs.py).
"""
import json
import os
import re
import shutil
import time

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

import build_thumbs

# --- CONFIGURACION ---
BASE_URL = "https://www.toyotaofnorthmiami.com"
LISTING_URL = BASE_URL + "/new-inventory/index.htm?start={start}"
PAGE_STEP = 24
SOURCE = "Toyota of North Miami"
LOCATION = "North Miami, FL"
PHOTO_HOST = "https://pictures.dealer.com/t/toyotaofnorthmiamitoy/"
MIN_REAL_PHOTOS = 3
MAX_PHOTOS = 15

DATA_DIR = "data"
IMAGE_DIR = "images"
OUTPUT_FILE = os.path.join(DATA_DIR, "vehicles.json")
JS_OUTPUT_FILE = os.path.join(DATA_DIR, "vehicles.js")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# Lee la galeria de la pagina de detalle. La galeria del auto es el arreglo
# "images" cuya primera foto coincide con la foto del listado; asi no se
# mezclan fotos de "autos similares" que tambien aparecen en la pagina.
FETCH_GALLERY_JS = """
const [link, firstUri, done] = arguments;
fetch(link).then(r => r.text()).then(html => {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    for (const s of [...doc.querySelectorAll('script:not([src])')].map(x => x.textContent)) {
        let idx = s.indexOf('"images":[');
        while (idx >= 0) {
            let depth = 0, end = -1;
            for (let k = idx + 9; k < s.length; k++) {
                if (s[k] === '[') depth++;
                else if (s[k] === ']') { depth--; if (depth === 0) { end = k + 1; break; } }
            }
            if (end < 0) break;
            try {
                const arr = JSON.parse(s.slice(idx + 9, end));
                if (arr[0] && arr[0].uri === firstUri) {
                    return done(arr.map(i => ({ uri: i.uri, provider: i.provider })));
                }
            } catch (e) {}
            idx = s.indexOf('"images":[', end);
        }
    }
    done(null);
}).catch(() => done(null));
"""

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)


def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(f"user-agent={USER_AGENT}")
    driver = webdriver.Chrome(options=chrome_options)
    driver.set_script_timeout(60)
    return driver


def load_existing_data():
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_data(data):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    with open(JS_OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"const vehicleData = {json.dumps(data, indent=4, ensure_ascii=False)};")
    print(f"Datos guardados en {OUTPUT_FILE} y {JS_OUTPUT_FILE}")


def read_listing_page(driver, start):
    """Devuelve (vehiculos del dataLayer, ultimo 'start' de la paginacion)."""
    driver.get(LISTING_URL.format(start=start))
    for _ in range(40):
        vehicles = driver.execute_script(
            "return (window.DDC && DDC.dataLayer && DDC.dataLayer.vehicles) || null"
        )
        if vehicles is not None:
            last_start = driver.execute_script(
                "return Math.max(0, ...[...document.querySelectorAll('a[href*=\"start=\"]')]"
                ".map(a => Number((a.getAttribute('href').match(/start=(\\d+)/) || [])[1] || 0)))"
            )
            return vehicles, last_start
        time.sleep(0.5)
    raise RuntimeError(f"La pagina start={start} no cargo el inventario")


def price_value(pricing):
    for key in ("finalPrice", "internetPrice", "salePrice", "askingPrice", "msrp"):
        digits = re.sub(r"[^\d]", "", str((pricing or {}).get(key) or ""))
        if digits:
            return digits
    return ""


def download_cover(url, vin):
    folder = os.path.join(IMAGE_DIR, vin)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "image_1.jpg")
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    response.raise_for_status()
    with open(path, "wb") as f:
        f.write(response.content)
    return f"images\\{vin}\\image_1.jpg"


def build_vehicle(listing, photos):
    title = f"{listing.get('modelYear')} {listing.get('make')} {listing.get('model')} {listing.get('trim') or ''}".strip()
    return {
        "vin": listing["vin"],
        "year": str(listing.get("modelYear") or listing.get("year") or ""),
        "make": listing.get("make") or "",
        "model": listing.get("model") or "",
        "trim": listing.get("trim") or "",
        "price": price_value(listing.get("pricing")),
        "mileage": None,
        "condition": "NEW",
        "ext_color": listing.get("exteriorColor") or "",
        "int_color": listing.get("interiorColor") or "",
        "body_style": listing.get("bodyStyle") or "",
        "transmission": listing.get("transmission") or "",
        "engine": listing.get("engine") or "",
        "fuel": listing.get("fuelType") or "",
        "vdp_url": BASE_URL + (listing.get("link") or ""),
        "display_name": title.upper(),
        "location": LOCATION,
        "source": SOURCE,
        "image_url": photos[0],
        "images": photos,
        "local_image": "",
    }


def scrape():
    driver = setup_driver()
    listed_vins = set()
    candidates = []
    try:
        start, last_start = 0, 0
        while start <= last_start:
            vehicles, last_start = read_listing_page(driver, start)
            print(f"Pagina start={start}: {len(vehicles)} autos (ultima pagina start={last_start})")
            for v in vehicles:
                vin = v.get("vin")
                if not vin or vin in listed_vins:
                    continue
                listed_vins.add(vin)
                first = (v.get("images") or [{}])[0]
                # Los autos con fotos reales las muestran primero en el listado
                if v.get("status") == "live" and first.get("provider") == "ACTUAL_PHOTO":
                    candidates.append(v)
            start += PAGE_STEP
            time.sleep(1.5)

        print(f"\nAutos en el inventario: {len(listed_vins)} | con fotos reales: {len(candidates)}")
        galleries = {}
        for i, v in enumerate(candidates, 1):
            gallery = driver.execute_async_script(FETCH_GALLERY_JS, v["link"], v["images"][0]["uri"])
            photos = []
            for img in gallery or []:
                uri = img.get("uri") or ""
                if img.get("provider") == "ACTUAL_PHOTO" and uri.startswith(PHOTO_HOST) and uri not in photos:
                    photos.append(uri)
            galleries[v["vin"]] = photos[:MAX_PHOTOS]
            print(f"  [{i}/{len(candidates)}] {v['vin']} {v.get('modelYear')} {v.get('model')}: {len(photos)} fotos reales")
            time.sleep(1)
    finally:
        driver.quit()
    return listed_vins, candidates, galleries


def main():
    print(f"Iniciando extraccion de {SOURCE}...")
    data = load_existing_data()
    existing_vins = {v["vin"] for v in data if v.get("vin")}
    print(f"Cargados {len(data)} vehiculos existentes.")

    listed_vins, candidates, galleries = scrape()

    # Una foto que aparece en dos autos distintos no es confiable
    owners = {}
    for vin, photos in galleries.items():
        for uri in photos:
            owners.setdefault(uri, set()).add(vin)

    added = 0
    for v in candidates:
        vin = v["vin"]
        photos = [u for u in galleries.get(vin, []) if len(owners[u]) == 1]
        if vin in existing_vins or len(photos) < MIN_REAL_PHOTOS:
            continue
        vehicle = build_vehicle(v, photos)
        try:
            vehicle["local_image"] = download_cover(photos[0], vin)
        except requests.RequestException as e:
            print(f"  No se pudo bajar la portada de {vin}: {e}")
            continue
        data.append(vehicle)
        existing_vins.add(vin)
        added += 1
        print(f"  [OK] {vehicle['display_name']} ({len(photos)} fotos)")

    # Autos de este dealer que ya no estan en su inventario (vendidos).
    # Si el listado vino casi vacio, el sitio cambio: mejor no quitar nada.
    sold = []
    if len(listed_vins) >= 50:
        sold = [v for v in data if v.get("source") == SOURCE and v["vin"] not in listed_vins]
    else:
        print(f"Aviso: el listado solo trajo {len(listed_vins)} autos; no se quita ninguno por vendido.")
    for v in sold:
        shutil.rmtree(os.path.join(IMAGE_DIR, v["vin"]), ignore_errors=True)
    data = [v for v in data if v not in sold]

    save_data(data)
    print(f"\nPROCESO COMPLETADO. Nuevos: {added} | quitados por vendidos: {len(sold)} | total en catalogo: {len(data)}")
    print("\nGenerando miniaturas...")
    build_thumbs.main()


if __name__ == "__main__":
    main()
