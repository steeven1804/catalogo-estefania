import os
import json
import re
import sys
import time
import requests
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

# Configuración de Typesense de Toyota of Hollywood
TYPESENSE_URL = "https://hjnrb3s21408ezpfp.a1.typesense.net/multi_search?x-typesense-api-key=eQUa8iq30l8Tu908Drz9WKqar6tCJGd4"
COLLECTION_NAME = "vehicles-TOY09107"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
}

def clean_image_url(url):
    """
    Limpia los parámetros de resize de la URL para obtener la imagen en alta resolución
    """
    if not url: return ""
    if url.startswith("//"):
        url = "https:" + url
    # Reemplazar patrones de resize /resize/640x640/ o similares por un simple slash /
    url = re.sub(r'/resize/\d+x\d+/', '/', url)
    return url

def download_single_image(job):
    """
    Descarga una sola imagen y retorna la ruta local relativa en formato compatible
    """
    url = job["url"]
    folder = job["folder"]
    filename = job["filename"]
    vin = job["vin"]
    idx = job["idx"]
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, filename)
            with open(path, 'wb') as f:
                f.write(response.content)
            # Retornar la ruta local relativa (el frontend espera forward slash en images)
            return {"vin": vin, "idx": idx, "path": f"images/{vin}/{filename}"}
    except Exception as e:
        print(f"      [!] Error descargando imagen {idx+1} para {vin}: {e}")
    return {"vin": vin, "idx": idx, "path": ""}

def fetch_toyota_used_vehicles():
    """
    Consulta la API de Typesense y recupera todos los vehículos con condición 'Used'
    """
    print("Consultando la API de Typesense de Toyota of Hollywood...")
    vehicles = []
    page = 1
    per_page = 250  # Tamaño máximo por página recomendado en Typesense
    
    while True:
        body = {
            "searches": [
                {
                    "collection": COLLECTION_NAME,
                    "q": "*",
                    "filter_by": "condition:=Used",
                    "page": page,
                    "per_page": per_page
                }
            ]
        }
        
        try:
            response = requests.post(TYPESENSE_URL, json=body, headers=HEADERS, timeout=15)
            response.raise_for_status()
            res_data = response.json()
            
            if "results" not in res_data or not res_data["results"]:
                break
                
            search_res = res_data["results"][0]
            hits = search_res.get("hits", [])
            total_found = search_res.get("found", 0)
            
            if not hits:
                break
                
            print(f"   -> Página {page}: Cargados {len(hits)} vehículos (Total en servidor: {total_found})")
            
            for hit in hits:
                doc = hit.get("document", {})
                vin = doc.get("vin")
                if not vin:
                    continue
                
                # Obtener lista de imágenes en alta resolución
                raw_images = doc.get("imageUrls", [])
                image_urls = [clean_image_url(url) for url in raw_images if url]
                
                # Mapeo a nuestro formato estandarizado
                vdp_path = doc.get("vdpUrl", "")
                vdp_url = f"https://www.toyotaofhollywood.com{vdp_path}" if vdp_path else ""
                
                v_type = "USADO" # Convención del catálogo
                
                vehicle = {
                    "vin": vin,
                    "year": str(doc.get("year", "")),
                    "make": doc.get("make", "Toyota"),
                    "model": doc.get("model", ""),
                    "price": str(doc.get("price") or doc.get("finalPriceInt") or ""),
                    "mileage": str(doc.get("mileage") or ""),
                    "ext_color": doc.get("exteriorColor", ""),
                    "int_color": doc.get("interiorColor", ""),
                    "body_style": (doc.get("body") or "Used").capitalize(),
                    "transmission": doc.get("transmission", ""),
                    "engine": doc.get("engine", ""),
                    "vdp_url": vdp_url,
                    "display_name": f"{v_type} {doc.get('year', '')} {doc.get('make', 'Toyota')} {doc.get('model', '')}".upper(),
                    "image_url": image_urls[0] if image_urls else "",
                    "local_image": "",
                    "trim": doc.get("trim", ""),
                    "fuel": doc.get("fuel", ""),
                    "exterior": doc.get("exteriorColor", ""),
                    "interior": doc.get("interiorColor", ""),
                    "images": [],
                    # Guardamos la lista de URLs originales de alta resolución para descargas
                    "_all_image_urls": image_urls
                }
                vehicles.append(vehicle)
                
            # Si trajimos menos de los solicitados, ya terminamos
            if len(hits) < per_page:
                break
                
            page += 1
            time.sleep(0.5) # Pequeña pausa para ser gentiles con el servidor
            
        except Exception as e:
            print(f"   [!] Error consultando la API en página {page}: {e}")
            break
            
    print(f"Extracción de metadatos finalizada. Encontrados {len(vehicles)} vehículos de Toyota.")
    return vehicles

def main():
    start_time = time.time()
    print("==================================================================")
    print(" INICIANDO SCRAPER OPTIMIZADO DE TOYOTA OF HOLLYWOOD (TYPESENSE API)")
    print("==================================================================")
    
    # 1. Cargar inventario existente
    existing_vehicles = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                existing_vehicles = json.load(f)
        except Exception as e:
            print(f"Advertencia al cargar archivo existente: {e}")
            
    print(f"Cargados {len(existing_vehicles)} vehículos existentes en el catálogo.")
    
    # Mapear inventario por VIN para actualización rápida y filtrar los de otros concesionarios
    db_by_vin = {v["vin"]: v for v in existing_vehicles if v.get("vin")}
    
    # 2. Consultar la API de Typesense
    toyota_scraped = fetch_toyota_used_vehicles()
    
    # Determinar qué vehículos de Toyota son nuevos o no tienen imagen local configurada
    new_or_missing_images = []
    
    for v in toyota_scraped:
        vin = v["vin"]
        if vin in db_by_vin:
            # Mantener y actualizar metadatos del vehículo existente
            existing_car = db_by_vin[vin]
            # Si no tiene imágenes locales pero ahora tenemos las URLs, lo procesamos
            if not existing_car.get("local_image") and v["_all_image_urls"]:
                existing_car["_all_image_urls"] = v["_all_image_urls"]
                new_or_missing_images.append(existing_car)
            else:
                # Actualizar otros campos técnicos pero mantener sus fotos y local_image
                existing_car.update({
                    "price": v["price"],
                    "mileage": v["mileage"],
                    "transmission": v["transmission"],
                    "engine": v["engine"],
                    "trim": v["trim"],
                    "fuel": v["fuel"]
                })
        else:
            # Es un vehículo totalmente nuevo, lo añadimos al diccionario de BD y a descargas
            db_by_vin[vin] = v
            new_or_missing_images.append(v)
            
    print(f"Vehículos de Toyota que requieren descarga de fotos: {len(new_or_missing_images)}")
    
    # 3. Preparar los trabajos de descarga multihilo para las imágenes
    download_jobs = []
    for v in new_or_missing_images:
        vin = v["vin"]
        urls = v.get("_all_image_urls", [])
        
        # Descargamos un máximo de 8 fotos por vehículo
        target_urls = urls[:8]
        vin_safe = "".join([c for c in vin if c.isalnum()])
        folder = os.path.join(IMAGE_DIR, vin_safe)
        
        for idx, url in enumerate(target_urls):
            filename = f"image_{idx+1}.jpg"
            job = {
                "vin": vin,
                "url": url,
                "folder": folder,
                "filename": filename,
                "idx": idx
            }
            download_jobs.append(job)
            
    # Ejecución concurrente con ThreadPoolExecutor
    downloaded_results = []
    if download_jobs:
        max_workers = min(16, len(download_jobs)) # Máximo 16 hilos en paralelo
        print(f"Descargando {len(download_jobs)} imágenes de forma concurrente usando {max_workers} hilos...")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(download_single_image, job) for job in download_jobs]
            
            completed_count = 0
            for future in as_completed(futures):
                res = future.result()
                downloaded_results.append(res)
                completed_count += 1
                if completed_count % 20 == 0 or completed_count == len(download_jobs):
                    print(f"   -> Progreso descargas: {completed_count}/{len(download_jobs)}")
                    
    # 4. Compilar los resultados de las descargas en cada vehículo
    # Agrupar resultados por VIN
    downloads_by_vin = {}
    for res in downloaded_results:
        vin = res["vin"]
        if vin not in downloads_by_vin:
            downloads_by_vin[vin] = []
        downloads_by_vin[vin].append(res)
        
    for vin, results in downloads_by_vin.items():
        # Ordenar por índice para garantizar el orden de la galería
        results.sort(key=lambda x: x["idx"])
        local_paths = [r["path"] for r in results if r["path"]]
        
        if local_paths:
            car = db_by_vin[vin]
            car["images"] = local_paths
            # local_image espera el estilo backslash de Windows en la base de datos de este sitio
            car["local_image"] = local_paths[0].replace("/", "\\")
            print(f"  [+] Galería descargada con éxito para {car['display_name']} ({len(local_paths)} fotos)")
            
    # 5. Limpieza y guardado final
    # Eliminar metadatos auxiliares de descarga antes de guardar
    final_vehicles = list(db_by_vin.values())
    for v in final_vehicles:
        if "_all_image_urls" in v:
            del v["_all_image_urls"]
            
    # Guardar en archivo JSON
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_vehicles, f, indent=4, ensure_ascii=False)
        
    # Guardar en archivo JS
    with open(JS_OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(f"const vehicleData = {json.dumps(final_vehicles, indent=4, ensure_ascii=False)};")
        
    duration = time.time() - start_time
    print("==================================================================")
    print(" PROCESO COMPLETADO EXITOSAMENTE")
    print(f" Tiempo total: {duration:.2f} segundos")
    print(f" Total de vehículos en catálogo: {len(final_vehicles)}")
    print(f" Datos guardados en: {OUTPUT_FILE} y {JS_OUTPUT_FILE}")
    print("==================================================================")

if __name__ == "__main__":
    main()
