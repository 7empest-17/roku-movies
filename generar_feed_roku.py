import json
import re
import time
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup
from seleniumbase import Driver

BASE_URL = "https://cinebel.cc"

def obtener_urls_sitemap():
    sitemap_candidates = [
        f"{BASE_URL}/wp-sitemap-posts-movies-1.xml",
        f"{BASE_URL}/movie-sitemap.xml",
        f"{BASE_URL}/sitemap-movies.xml"
    ]
    urls = []
    for sm_url in sitemap_candidates:
        try:
            res = requests.get(sm_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if res.status_code == 200 and "<urlset" in res.text:
                root = ET.fromstring(res.content)
                for elem in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc"):
                    loc = elem.text.strip()
                    if "/movies/" in loc and loc != f"{BASE_URL}/movies/":
                        urls.append(loc)
                if urls:
                    break
        except Exception:
            continue
    return urls

def extraer_stream_rumble(driver, embed_url):
    try:
        driver.uc_open_with_reconnect(embed_url, reconnect_time=4)
        driver.uc_gui_click_captcha()
        html = driver.page_source

        config_match = re.search(r'const\s+configId\s*=\s*["\']([a-zA-Z0-9_-]+)["\']', html)
        if config_match:
            config_id = config_match.group(1)
            config_url = f"{BASE_URL}/get_video_config.php?id={config_id}"
            
            driver.uc_open_with_reconnect(config_url, reconnect_time=2)
            cfg_text = driver.get_text("body")
            data = json.loads(cfg_text)
            for source in data.get("sources", []):
                f = source.get("file", "")
                if f and "test-streams.mux.dev" not in f:
                    return {
                        "url": f,
                        "format": "hls" if ".m3u8" in f else "mp4"
                    }
        
        # Búsqueda secundaria de enlace directo
        streams = re.findall(r'https?://[^\s"\'<>]+\.(?:mp4|m3u8)[^\s"\'<>]*', html)
        for s in streams:
            if "mux.dev" not in s:
                return {"url": s, "format": "hls" if ".m3u8" in s else "mp4"}
    except Exception as e:
        print(f"       -> Error resolviendo rumble: {e}")
    return None

def generar_feed(limite_peliculas=15):
    print("[-] Descargando lista de títulos del sitemap...")
    movie_links = obtener_urls_sitemap()

    if not movie_links:
        print("[!] Error: No se encontraron URLs en el sitemap.")
        return

    print(f"[+] Total detectadas: {len(movie_links)}. Extrayendo primeras {limite_peliculas}...")

    # UC Mode (Undetected-Chromedriver) en ventana real virtualizada
    driver = Driver(uc=True, headless=False)
    peliculas_roku = []

    try:
        # Abrir la home para superar Cloudflare y sembrar la sesión
        print("[-] Validando acceso inicial y resolviendo Turnstile...")
        driver.uc_open_with_reconnect(BASE_URL, reconnect_time=6)
        driver.uc_gui_click_captcha()
        time.sleep(3)

        for movie_url in movie_links[:limite_peliculas]:
            slug = movie_url.rstrip("/").split("/")[-1]
            print(f"\n  -> Procesando: {slug}")

            driver.uc_open_with_reconnect(movie_url, reconnect_time=5)
            driver.uc_gui_click_captcha()

            html = driver.page_source
            soup = BeautifulSoup(html, "html.parser")

            title_tag = soup.select_one("h1, .sheader .data h1")
            title = title_tag.get_text(strip=True) if title_tag else slug

            poster_tag = soup.select_one(".poster img, .sheader .poster img")
            poster = ""
            if poster_tag:
                poster = poster_tag.get("data-src") or poster_tag.get("src") or ""
                if poster.startswith("//"):
                    poster = "https:" + poster

            iframe_url = ""

            # Caso 1: Iframe directo en el DOM
            iframe_elem = soup.select_one("#playernos1 iframe, .playex iframe, .source-box iframe")
            if iframe_elem and iframe_elem.get("src"):
                iframe_url = iframe_elem.get("src")

            # Caso 2: Clic en botón DooPlay AJAX
            if not iframe_url:
                player_item = soup.select_one("li[data-post][data-nume], div[data-post][data-nume]")
                if player_item:
                    try:
                        driver.click("li[data-post][data-nume], div[data-post][data-nume]")
                        time.sleep(2)
                        html_updated = driver.page_source
                        soup_updated = BeautifulSoup(html_updated, "html.parser")
                        iframe_elem = soup_updated.select_one("#playernos1 iframe, .playex iframe, iframe")
                        if iframe_elem and iframe_elem.get("src"):
                            iframe_url = iframe_elem.get("src")
                    except Exception:
                        pass

            if not iframe_url:
                print(f"       [x] No se encontró reproductor (Título: '{title}')")
                continue

            if iframe_url.startswith("//"):
                iframe_url = "https:" + iframe_url

            print(f"       -> Player detectado: {iframe_url[:50]}...")
            stream = extraer_stream_rumble(driver, iframe_url)

            if stream:
                print(f"       [OK] Stream obtenido ({stream['format'].upper()})")
                peliculas_roku.append({
                    "id": slug,
                    "title": title,
                    "hdPosterUrl": poster,
                    "description": "",
                    "url": stream["url"],
                    "streamFormat": stream["format"]
                })
            else:
                print("       [x] No se pudo obtener enlace de video")

            time.sleep(1)

    finally:
        driver.quit()

    with open("feed_roku.json", "w", encoding="utf-8") as f:
        json.dump(peliculas_roku, f, ensure_ascii=False, indent=2)

    print(f"\n[+] Proceso finalizado: {len(peliculas_roku)} películas guardadas en 'feed_roku.json'.")

if __name__ == "__main__":
    generar_feed(limite_peliculas=15)
