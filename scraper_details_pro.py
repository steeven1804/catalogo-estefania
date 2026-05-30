
import os
import json
import time
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURACIÓN ---
DATA_DIR = "data"
IMAGE_DIR = "images"
INPUT_FILE = os.path.join(DATA_DIR, "vehicles.json")
OUTPUT_FILE = os.path.join(DATA_DIR, "vehicles.json")
JS_OUTPUT_FILE = os.path.join(DATA_DIR, "vehicles.js")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=chrome_options)

def download_image(url, folder, filename):
    if not url: return ""
    try:
        if url.startswith("//"): url = "https:" + url
        # Strip query params for better resolution if needed, but some CDNs need them.
        # For now, let's keep them unless we see issues.
        
        response = requests.get(url, stream=True, timeout=10)
        if response.status_code == 200:
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, filename)
            with open(path, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            # Return relative path for web use
            return path.replace("\\", "/")
    except Exception as e:
        print(f"      Error descargando {url}: {e}")
    return ""

def scrape_vdp(driver, vdp_url):
    print(f"   -> Visitando VDP: {vdp_url}")
    data = {
        "trim": "",
        "transmission": "",
        "fuel": "",
        "exterior": "",
        "interior": "",
        "location": "",
        "description": "",
        "all_images": []
    }
    
    try:
        driver.get(vdp_url)
        wait_time = 6 if "hollywoodkia" in vdp_url else 4
        time.sleep(wait_time)
        
        vin = ""
        # 1. Try DDC dataLayer (Dealer.com sites)
        try:
            ddc_data = driver.execute_script("return (window.DDC && DDC.dataLayer && DDC.dataLayer.vehicles) ? DDC.dataLayer.vehicles : [];")
            if ddc_data and len(ddc_data) > 0:
                veh = ddc_data[0]
                vin = veh.get("vin", "")
                data["trim"] = veh.get("trim", "")
                data["transmission"] = veh.get("transmission", "")
                data["fuel"] = veh.get("fuelType", "") or veh.get("engine", "")
                data["exterior"] = veh.get("exteriorColor", "")
                data["interior"] = veh.get("interiorColor", "")
                
                if veh.get("images"):
                    for img in veh["images"]:
                        if img.get("uri"):
                            data["all_images"].append(img["uri"].replace("\\", ""))
        except: pass
        
        # 2. Try window.dataLayer (Standard GTM)
        if not data["all_images"]:
            try:
                dl_images = driver.execute_script("""
                    let uris = [];
                    if (window.dataLayer) {
                        for (let i = 0; i < window.dataLayer.length; i++) {
                            let obj = window.dataLayer[i];
                            if (obj.ecommerce && obj.ecommerce.detail && obj.ecommerce.detail.products) {
                                let p = obj.ecommerce.detail.products[0];
                                if (p.images) uris = p.images;
                            }
                        }
                    }
                    return uris;
                """)
                if dl_images: data["all_images"] = dl_images
            except: pass

        # 3. DOM Scraping + VIN matching logic
        if not vin:
            # Try to get VIN from current vehicle context or page
            try:
                vin_el = driver.find_elements(By.XPATH, "//*[contains(text(), 'VIN')]/following-sibling::*")
                if vin_el: vin = vin_el[0].text.strip()
            except: pass

        # If we have a VIN (either from param or page), search for it in all image srcs
        # This is very effective for sites like Hollywood Kia
        vdp_vin = vdp_url.split("/")[-2].upper() if vdp_url.endswith("/") else vdp_url.split("/")[-1].upper()
        search_vin = vin if len(vin) > 10 else vdp_vin

        img_elements = driver.find_elements(By.TAG_NAME, "img")
        for img in img_elements:
            try:
                src = img.get_attribute("src") or img.get_attribute("data-src") or img.get_attribute("srcset")
                if src:
                    if "," in src: src = src.split(",")[0].split(" ")[0]
                    # Check if URL contains VIN or common vehicle image patterns
                    if (search_vin in src.upper()) or ("vehicle-images" in src) or ("photos/inventory" in src):
                        if "placeholder" not in src.lower() and "base64" not in src:
                            # Prefer non-thumbnail versions if possible
                            clean_src = src.replace("/thumbnails/large/", "/").replace("/thumbnails/small/", "/")
                            data["all_images"].append(clean_src)
            except: continue

        # Swiper fallback
        if len(data["all_images"]) < 5:
            img_elements = driver.find_elements(By.CSS_SELECTOR, ".swiper-slide:not(.swiper-slide-duplicate) img, .vdp-gallery img, .photos img")
            for img in img_elements:
                src = img.get_attribute("src") or img.get_attribute("data-src")
                if src and src not in data["all_images"] and "placeholder" not in src.lower():
                    data["all_images"].append(src)

        # Clean URLs
        data["all_images"] = [url.split("?")[0] if "?" in url else url for url in data["all_images"]]
        data["all_images"] = list(dict.fromkeys(data["all_images"])) # Deduplicate
        data["all_images"] = data["all_images"][:30] 

        # Metadata extraction
        if not data["transmission"]:
            items = driver.find_elements(By.CSS_SELECTOR, ".vdp-details__sub-list-item, .spec-item, li")
            for item in items:
                try:
                    text = item.text.lower()
                    if ":" in text:
                        label, value = text.split(":", 1)
                        label = label.strip()
                        value = value.strip()
                        if "trans" in label: data["transmission"] = value
                        if "ext" in label or "color" in label: data["exterior"] = value
                        if "int" in label: data["interior"] = value
                        if "fuel" in label or "motor" in label: data["fuel"] = value
                        if "trim" in label: data["trim"] = value
                except: pass

        # Location fallback
        if "hollywoodkia" in vdp_url: data["location"] = "Hollywood, FL"
        elif "braman" in vdp_url: data["location"] = "Miami, FL"

    except Exception as e:
        print(f"      Error scrapeando VDP: {e}")
        
    return data

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} no existe.")
        return

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        vehicles = json.load(f)

    # Filtrar vehículos que necesitan procesamiento (menos de 3 imágenes)
    to_process = []
    for v in vehicles:
        current_images = v.get("images", [])
        if len(current_images) < 3:
            to_process.append(v)

    print(f"Total vehículos: {len(vehicles)}")
    print(f"Vehículos a procesar (nuevos o sin fotos): {len(to_process)}")
    
    if not to_process:
        print("No hay vehículos nuevos para procesar.")
        return

    driver = setup_driver()
    
    try:
        for i, v in enumerate(to_process):
            print(f"[{i+1}/{len(to_process)}] {v.get('display_name', 'Vehicle')}")
            
            vin = v.get("vin")
            if not vin: continue
            
            vdp_url = v.get("vdp_url")
            if not vdp_url:
                print("   ! No hay VDP URL, saltando.")
                continue
                
            details = scrape_vdp(driver, vdp_url)
            
            # Update fields
            if details["trim"]: v["trim"] = details["trim"]
            if details["transmission"]: v["transmission"] = details["transmission"]
            if details["fuel"]: v["fuel"] = details["fuel"]
            if details["exterior"]: v["exterior"] = details["exterior"]
            if details["interior"]: v["interior"] = details["interior"]
            if details.get("location"): v["location"] = details["location"]
            if details.get("description"): v["description"] = details["description"]
            
            # Download images (8) - Reduced to save disk space
            vin_safe = "".join([c for c in vin if c.isalnum()])
            car_img_dir = os.path.join(IMAGE_DIR, vin_safe)
            
            img_list = []
            if details["all_images"]:
                # Limit to 8 images to save disk space
                target_images = details["all_images"][:8]
                print(f"    -> Descargando {len(target_images)} imágenes...")
                for idx, img_url in enumerate(target_images):
                    filename = f"image_{idx+1}.jpg"
                    local_path = download_image(img_url, car_img_dir, filename)
                    if local_path:
                        img_list.append(local_path)
            
            if img_list:
                v["images"] = img_list
                v["local_image"] = img_list[0].replace("/", "\\")
                print(f"    [OK] {len(img_list)} fotos guardadas.")
            else:
                print("    [!] No se pudieron descargar fotos.")
            
            # Guardar cada 5 o al final del bloque con manejo de errores de disco
            if (i+1) % 5 == 0:
                try:
                    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                        json.dump(vehicles, f, indent=4, ensure_ascii=False)
                    with open(JS_OUTPUT_FILE, 'w', encoding='utf-8') as f:
                        f.write(f"const vehicleData = {json.dumps(vehicles, indent=4, ensure_ascii=False)};")
                except OSError as e:
                    if e.errno == 28:
                        print("\n[CRÍTICO] Disco lleno. Deteniendo para evitar pérdida de datos.")
                        break
                    raise e

    finally:
        driver.quit()

    # Final Save
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(vehicles, f, indent=4, ensure_ascii=False)
        
        with open(JS_OUTPUT_FILE, 'w', encoding='utf-8') as f:
            f.write(f"const vehicleData = {json.dumps(vehicles, indent=4, ensure_ascii=False)};")
            
        print("\n¡PROCESO COMPLETADO!")
    except OSError as e:
        if e.errno == 28:
            print("\n[CRÍTICO] No se pudo realizar el guardado final por falta de espacio.")
        else:
            raise e

if __name__ == "__main__":
    main()
