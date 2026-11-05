"""
Genera miniaturas livianas (WebP) para las tarjetas del catalogo.

Ejecutar despues de cada scraper:
    python build_thumbs.py

- Crea thumbs/<VIN>.webp a partir de la foto de portada (o de la primera
  foto de galeria que exista) y agrega el campo "thumb" a
  data/vehicles.json y data/vehicles.js.
- Las miniaturas que ya existen no se vuelven a generar.
- Borra las miniaturas de vehiculos que ya no estan en el catalogo.
"""
import json
import os

from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
THUMBS_DIR = os.path.join(BASE_DIR, "thumbs")
JSON_FILE = os.path.join(DATA_DIR, "vehicles.json")
JS_FILE = os.path.join(DATA_DIR, "vehicles.js")

THUMB_WIDTH = 480
QUALITY = 72
# Some scrapes save 1x1 / 5x5 tracking pixels instead of the real photo
MIN_SOURCE_SIZE = 50


def is_real_photo(path):
    try:
        with Image.open(path) as img:
            return min(img.size) >= MIN_SOURCE_SIZE
    except OSError:
        return False


def source_image(vehicle):
    candidates = [vehicle.get("local_image")] + list(vehicle.get("images") or [])
    for path in candidates:
        if not path:
            continue
        full = os.path.join(BASE_DIR, path.replace("\\", "/"))
        if os.path.isfile(full) and is_real_photo(full):
            return full
    return None


def make_thumb(src, out):
    with Image.open(src) as img:
        if img.mode != "RGB":
            # Transparent areas become white instead of black
            rgba = img.convert("RGBA")
            img = Image.new("RGB", rgba.size, "white")
            img.paste(rgba, mask=rgba.getchannel("A"))
        img.thumbnail((THUMB_WIDTH, THUMB_WIDTH * 2))
        img.save(out, "WEBP", quality=QUALITY, method=6)


def main():
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        vehicles = json.load(f)

    os.makedirs(THUMBS_DIR, exist_ok=True)
    created = reused = without_photo = 0
    used_files = set()

    for vehicle in vehicles:
        vin = vehicle.get("vin")
        if not vin:
            continue
        filename = f"{vin}.webp"
        out = os.path.join(THUMBS_DIR, filename)

        if os.path.isfile(out):
            reused += 1
        else:
            src = source_image(vehicle)
            if not src:
                vehicle.pop("thumb", None)
                without_photo += 1
                continue
            try:
                make_thumb(src, out)
                created += 1
            except OSError as e:
                print(f"  No se pudo procesar {src}: {e}")
                vehicle.pop("thumb", None)
                without_photo += 1
                continue

        vehicle["thumb"] = f"thumbs/{filename}"
        used_files.add(filename)

    removed = 0
    for filename in os.listdir(THUMBS_DIR):
        if filename.endswith(".webp") and filename not in used_files:
            os.remove(os.path.join(THUMBS_DIR, filename))
            removed += 1

    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(vehicles, f, indent=4, ensure_ascii=False)
    with open(JS_FILE, "w", encoding="utf-8") as f:
        f.write(f"const vehicleData = {json.dumps(vehicles, indent=4, ensure_ascii=False)};")

    total_kb = sum(
        os.path.getsize(os.path.join(THUMBS_DIR, name)) for name in used_files
    ) / 1024
    print(f"Miniaturas nuevas: {created} | ya existian: {reused} | borradas: {removed}")
    print(f"Vehiculos sin foto local (usaran la foto remota): {without_photo}")
    print(f"Peso total de miniaturas: {total_kb:.0f} KB")


if __name__ == "__main__":
    main()
