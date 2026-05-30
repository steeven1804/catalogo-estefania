
import os
import json
import time
import requests
from bs4 import BeautifulSoup

# --- CONFIGURACIÓN ---
DATA_DIR = "data"
IMAGE_DIR = "images"
OUTPUT_FILE = os.path.join(DATA_DIR, "vehicles.json")
JS_OUTPUT_FILE = os.path.join(DATA_DIR, "vehicles.js")
BASE_URL = "https://www.metrofordmiami.com"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
}

def download_image(url, folder, filename):
    if not url: return ""
    try:
        if url.startswith("//"): url = "https:" + url
        elif url.startswith("/"): url = BASE_URL + url
            
        response = requests.get(url, stream=True, timeout=15, headers=HEADERS)
        if response.status_code == 200:
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, filename)
            with open(path, 'wb') as f:
                for chunk in response.iter_content(2048):
                    f.write(chunk)
            return path.replace("\\", "/")
    except Exception as e:
        print(f"      Error descargando {url}: {e}")
    return ""

def main(limit=20):
    print(f"Iniciando scraper de Metro Ford Miami (Lote de {limit})...")
    
    # Cargar vehículos existentes
    all_vehicles = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                all_vehicles = json.load(f)
        except: pass
    
    existing_vins = {v.get("vin") for v in all_vehicles if v.get("vin")}
    print(f"Cargados {len(all_vehicles)} vehículos existentes.")

    new_vehicles_count = 0
    page = 1
    
    while new_vehicles_count < limit:
        url = f"{BASE_URL}/searchused.aspx?page={page}"
        print(f"\nProcesando página {page}: {url}")
        
        try:
            response = requests.get(url, headers=HEADERS, timeout=20)
            if response.status_code != 200:
                print(f"   ! Error {response.status_code}. Fin de búsqueda.")
                break
                
            soup = BeautifulSoup(response.text, 'html.parser')
            containers = soup.select(".vehicle-card")
            
            if not containers:
                print("   ! No se encontraron vehículos. Fin de búsqueda.")
                break
                
            found_on_page = 0
            for container in containers:
                if new_vehicles_count >= limit:
                    break
                    
                vin = container.get("data-vin")
                if not vin: continue
                
                found_on_page += 1
                if vin in existing_vins:
                    continue
                
                year = container.get("data-year", "")
                make = container.get("data-make", "")
                model = container.get("data-model", "")
                price = container.get("data-price", "").split(".")[0]
                mileage = container.get("data-mileage", "")
                ext_color = container.get("data-extcolor", "")
                int_color = container.get("data-intcolor", "")
                
                title_el = container.select_one(".vehicle-title a")
                vdp_url = BASE_URL + title_el.get("href") if title_el else ""
                
                # Imagen
                img_el = container.select_one(".hero-carousel__image")
                img_url = img_el.get("src") if img_el else ""
                if not img_url:
                    img_el = container.select_one("img.lazyload")
                    if img_el:
                        img_url = img_el.get("data-src") or img_el.get("src")
                
                if img_url and img_url.startswith("/"):
                    img_url = BASE_URL + img_url

                # Crear objeto vehículo
                vehicle = {
                    "vin": vin,
                    "year": year,
                    "make": make,
                    "model": model,
                    "price": price,
                    "mileage": mileage,
                    "ext_color": ext_color,
                    "int_color": int_color,
                    "body_style": "Used",
                    "transmission": container.get("data-transmission", ""),
                    "engine": container.get("data-engine", ""),
                    "vdp_url": vdp_url,
                    "display_name": f"USADO {year} {make} {model}".upper(),
                    "image_url": img_url,
                    "local_image": "",
                    "trim": container.get("data-trim", ""),
                    "fuel": "",
                    "exterior": ext_color,
                    "interior": int_color,
                    "location": "Miami, FL",
                    "description": "",
                    "images": []
                }
                
                # Descargar imagen
                if img_url:
                    vin_safe = "".join([c for c in vin if c.isalnum()])
                    car_img_dir = os.path.join(IMAGE_DIR, vin_safe)
                    filename = "image_1.jpg"
                    local_path = download_image(img_url, car_img_dir, filename)
                    if local_path:
                        vehicle["local_image"] = local_path.replace("/", "\\")
                        vehicle["images"] = [local_path]

                all_vehicles.append(vehicle)
                existing_vins.add(vin)
                new_vehicles_count += 1
                print(f"   [+] Nuevo [{new_vehicles_count}/{limit}]: {vehicle['display_name']} ({vin})")

            if found_on_page == 0:
                print("   ! No se detectaron vehículos en el DOM. Saltando.")
                break

            page += 1
            if page > 20: break # Safety break

        except Exception as e:
            print(f"   ! Error en página {page}: {e}")
            break

        except Exception as e:
            print(f"   ! Error en página {page}: {e}")
            break

    # Guardar cambios
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_vehicles, f, indent=4, ensure_ascii=False)
    with open(JS_OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(f"const vehicleData = {json.dumps(all_vehicles, indent=4, ensure_ascii=False)};")
            
    print(f"\nLOTE COMPLETADO. Se añadieron {new_vehicles_count} vehículos.")

if __name__ == "__main__":
    main(20)
