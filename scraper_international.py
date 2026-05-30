import os
import json
import re
import sys
import time
import requests
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from concurrent.futures import ThreadPoolExecutor, as_completed

# Forzar salida en UTF-8 para evitar errores de codificación en consolas Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# --- CONFIGURACIÓN ---
DATA_DIR = "data"
IMAGE_DIR = "images"
OUTPUT_FILE = os.path.join(DATA_DIR, "vehicles.json")
JS_OUTPUT_FILE = os.path.join(DATA_DIR, "vehicles.js")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
}

def clean_text(text):
    if not text: return ""
    return re.sub(r'\s+', ' ', text).strip()

def download_image(job):
    """
    Descarga una imagen localmente para el vehículo
    """
    url = job["url"]
    folder = job["folder"]
    filename = job["filename"]
    vin = job["vin"]
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, filename)
            with open(path, 'wb') as f:
                f.write(response.content)
            return {"vin": vin, "path": f"images/{vin}/{filename}"}
    except Exception as e:
        print(f"      [!] Error descargando imagen para {vin}: {e}")
    return {"vin": vin, "path": ""}

def setup_driver():
    """
    Configura y retorna el driver de undetected-chromedriver
    """
    options = uc.ChromeOptions()
    # Ejecutamos de forma no-headless para evadir Cloudflare fácilmente
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    
    # Configuramos para evadir la detección básica
    options.add_argument("--disable-blink-features=AutomationControlled")
    
    # Forzamos a que detecte la versión 148 de Chrome (instalada en la máquina)
    driver = uc.Chrome(options=options, version_main=148)
    return driver

def scrape_international_cars():
    print("Iniciando navegador con undetected-chromedriver...")
    driver = setup_driver()
    
    vehicles = []
    page = 1
    
    try:
        while True:
            url = f"https://www.internationalcarsusa.com/inventory/?sort_by=price_asc&page_no={page}"
            print(f"\n--- Procesando Página {page}: {url} ---")
            
            driver.get(url)
            
            # Esperamos a que Cloudflare verifique y cargue el inventario
            time.sleep(12)
            
            html = driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
            
            # Buscar las tarjetas de vehículos
            cards = soup.select(".dws-listing-item")
            print(f"   -> Encontradas {len(cards)} tarjetas de vehículos en esta página.")
            
            if not cards:
                print("   -> No se encontraron más vehículos en esta página. Finalizando paginación.")
                break
                
            for card in cards:
                # 1. VIN (Intentar clase o expresión regular en el texto)
                vin_el = card.select_one(".dws-vehicle-field-vin .dws-vehicle-listing-item-field-value")
                vin = clean_text(vin_el.text) if vin_el else ""
                
                if not vin:
                    vin_match = re.search(r'\b[A-HJ-NPR-Z0-9]{17}\b', card.text)
                    vin = vin_match.group(0) if vin_match else ""
                    
                if not vin:
                    # Si no tiene VIN, no podemos identificarlo de forma única
                    continue
                    
                # 2. Título (Year, Make, Model)
                title_el = card.select_one(".view-details-link")
                title = clean_text(title_el.text) if title_el else ""
                
                parts = title.split()
                year = parts[0] if parts and parts[0].isdigit() else ""
                make = parts[1] if len(parts) > 1 else ""
                model = " ".join(parts[2:]) if len(parts) > 2 else ""
                
                # 3. Precio
                price_el = card.select_one(".dws-listing-price.vehicle-price .field-value, .vehicle-price .field-value, .price, .final-price")
                price_raw = price_el.text if price_el else ""
                price = "".join(filter(str.isdigit, price_raw))
                if not price and "call" in price_raw.lower():
                    price = "Call for Price"
                    
                # 4. Kilometraje
                mileage_el = card.select_one(".dws-vehicle-field-mileage .dws-vehicle-listing-item-field-value")
                mileage_raw = mileage_el.text if mileage_el else ""
                mileage = "".join(filter(str.isdigit, mileage_raw))
                
                # 5. Especificaciones técnicas
                trans_el = card.select_one(".dws-vehicle-field-transmission .dws-vehicle-listing-item-field-value")
                transmission = clean_text(trans_el.text) if trans_el else ""
                
                fuel_el = card.select_one(".dws-vehicle-field-fueltype .dws-vehicle-listing-item-field-value")
                fuel = clean_text(fuel_el.text) if fuel_el else ""
                
                body_el = card.select_one(".dws-vehicle-field-bodytype .dws-vehicle-listing-item-field-value")
                body_style = clean_text(body_el.text).capitalize() if body_el else ""
                
                engine_el = card.select_one(".dws-vehicle-field-engine .dws-vehicle-listing-item-field-value")
                engine = clean_text(engine_el.text) if engine_el else ""
                
                ext_el = card.select_one(".dws-vehicle-field-exteriorcolor .dws-vehicle-listing-item-field-value")
                ext_color = clean_text(ext_el.text) if ext_el else ""
                
                int_el = card.select_one(".dws-vehicle-field-interiorcolor .dws-vehicle-listing-item-field-value")
                int_color = clean_text(int_el.text) if int_el else ""
                
                # 6. URL de detalles (VDP)
                vdp_url = ""
                if title_el:
                    href = title_el.get("href", "")
                    if href.startswith("/"):
                        vdp_url = "https://www.internationalcarsusa.com" + href
                    else:
                        vdp_url = href
                        
                # 7. Imagen principal
                img_container = card.select_one(".dws-vehicle-image-container")
                img_url = ""
                if img_container:
                    img_url = img_container.get("data-background-image") or ""
                    
                v_type = "USADO"
                
                vehicle = {
                    "vin": vin,
                    "year": year,
                    "make": make,
                    "model": model,
                    "price": price,
                    "mileage": mileage,
                    "ext_color": ext_color,
                    "int_color": int_color,
                    "body_style": body_style,
                    "transmission": transmission,
                    "engine": engine,
                    "fuel": fuel,
                    "vdp_url": vdp_url,
                    "display_name": f"{v_type} {year} {make} {model}".upper(),
                    "image_url": img_url,
                    "local_image": "",
                    "trim": "",
                    "exterior": ext_color,
                    "interior": int_color,
                    "images": []
                }
                vehicles.append(vehicle)
                print(f"      [+] Capturado: {vehicle['display_name']} ({vin})")
            
            # Pasar a la siguiente página
            page += 1
            time.sleep(1)
            
    except Exception as e:
        print(f"Error durante el raspado de la página: {e}")
    finally:
        try:
            driver.quit()
        except:
            pass
            
    print(f"\nExtracción de metadatos finalizada. Encontrados {len(vehicles)} vehículos en International Cars USA.")
    return vehicles

def main():
    start_time = time.time()
    print("==================================================================")
    print(" INICIANDO SCRAPER PARA INTERNATIONAL CARS USA CORP (CLOUDFLARE BYPASS)")
    print("==================================================================")
    
    # 1. Cargar catálogo existente
    existing_vehicles = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                existing_vehicles = json.load(f)
        except Exception as e:
            print(f"Advertencia al cargar archivo existente: {e}")
            
    print(f"Cargados {len(existing_vehicles)} vehículos existentes en el catálogo.")
    
    # Mapear inventario por VIN para fusionar y preservar otros concesionarios
    db_by_vin = {v["vin"]: v for v in existing_vehicles if v.get("vin")}
    
    # 2. Raspado de International Cars
    international_scraped = scrape_international_cars()
    
    # 3. Filtrar vehículos nuevos o sin imágenes locales
    new_or_missing_images = []
    
    for v in international_scraped:
        vin = v["vin"]
        if vin in db_by_vin:
            # Actualizar datos técnicos de vehículos existentes
            existing_car = db_by_vin[vin]
            existing_car.update({
                "price": v["price"],
                "mileage": v["mileage"],
                "transmission": v["transmission"],
                "engine": v["engine"],
                "fuel": v["fuel"],
                "body_style": v["body_style"]
            })
            # Si no tiene imagen local pero la URL remota está disponible
            if not existing_car.get("local_image") and v["image_url"]:
                existing_car["image_url"] = v["image_url"]
                new_or_missing_images.append(existing_car)
        else:
            # Es un auto totalmente nuevo, lo añadimos y preparamos para descarga
            db_by_vin[vin] = v
            new_or_missing_images.append(v)
            
    print(f"Vehículos de International Cars que requieren descarga de imagen de portada: {len(new_or_missing_images)}")
    
    # 4. Descarga concurrente de imágenes
    download_jobs = []
    for v in new_or_missing_images:
        vin = v["vin"]
        url = v.get("image_url")
        if not url:
            continue
            
        vin_safe = "".join([c for c in vin if c.isalnum()])
        folder = os.path.join(IMAGE_DIR, vin_safe)
        
        job = {
            "vin": vin,
            "url": url,
            "folder": folder,
            "filename": "image_1.jpg"
        }
        download_jobs.append(job)
        
    downloaded_results = []
    if download_jobs:
        max_workers = min(10, len(download_jobs)) # Máximo 10 descargas paralelas
        print(f"Descargando {len(download_jobs)} imágenes concurrentemente...")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(download_image, job) for job in download_jobs]
            for future in as_completed(futures):
                res = future.result()
                if res["path"]:
                    downloaded_results.append(res)
                    
    # 5. Actualizar rutas en los vehículos procesados
    for res in downloaded_results:
        vin = res["vin"]
        path = res["path"]
        car = db_by_vin[vin]
        car["images"] = [path]
        car["local_image"] = path.replace("/", "\\") # Compatibilidad de Windows
        print(f"  [+] Imagen descargada para: {car['display_name']} ({vin})")
        
    # 6. Guardado final en base de datos
    final_vehicles = list(db_by_vin.values())
    
    # Guardar en archivo JSON
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_vehicles, f, indent=4, ensure_ascii=False)
        
    # Guardar en archivo JS
    with open(JS_OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(f"const vehicleData = {json.dumps(final_vehicles, indent=4, ensure_ascii=False)};")
        
    duration = time.time() - start_time
    print("==================================================================")
    print(" PROCESO DE EXTRACCIÓN Y FUSIÓN COMPLETADO")
    print(f" Tiempo total: {duration:.2f} segundos")
    print(f" Total de vehículos en catálogo: {len(final_vehicles)}")
    print(f" Archivos guardados: {OUTPUT_FILE} y {JS_OUTPUT_FILE}")
    print("==================================================================")

if __name__ == "__main__":
    main()
