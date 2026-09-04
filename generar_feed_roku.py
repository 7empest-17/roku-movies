import json
import re
import time
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from curl_cffi import requests

BASE_URL = "https://cinebel.cc"
AJAX_URL = f"{BASE_URL}/wp-admin/admin-ajax.php"

# Inicializar sesión emulando Chrome 124 con gestión de cookies de paso
session = requests.Session(impersonate="chrome124")
headers_base = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Referer": "https://www.google.com/"
}
session.headers.update(headers_base)

def establecer_sesion():
    try:
        # Visita preliminar para recopilar cookies de Cloudflare
        session.get(BASE_URL, timeout=15)
        time.sleep(2)
    except Exception:
        pass

def obtener_urls_sitemap():
    # Alternativa directa cuando las rutas HTML del catálogo están restringidas en datacenters
    sitemap_candidates = [
        f"{BASE_URL}/wp-sitemap-posts-movies-1.xml",
        f"{BASE_URL}/movie-sitemap.xml",
        f"{BASE_URL}/sitemap-movies.xml"
    ]
    
    urls = []
    for sm_url in sitemap_candidates:
        try:
            res = session.get(sm_url, timeout=15)
            if res.status_code == 200 and "<urlset" in res.text:
                root = ET.fromstring(res.content)
                for elem in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc"):
                    if "/movies/" in elem.text and elem.text != f"{BASE_URL}/movies/":
                        urls.append(elem.text)
                if urls:
                    break
        except Exception:
            continue
    return urls

def resolver_video_rumble(embed_url):
    try:
        res = session.get(embed_url, headers={"Referer": BASE_URL}, timeout=15)
        if res.status_code != 200:
            return None

        html = res.text
        config_match = re.search(r'const\s+configId\s*=\s*["\']([a-zA-Z0-9_-]+)["\']', html)
        if not config_match:
            return None

        config_id = config_match.group(1)
        config_url = f"{BASE_URL}/get_video_config.php?id={config_id}"

        cfg_res = session.get(config_url, headers={
            "Referer": embed_url,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest"
        }, timeout=15)

        if cfg_res.status_code == 200:
            data = cfg_res.json()
            for source in data.get("sources", []):
                file_url = source.get("file", "")
                if file_url and "test-streams.mux.dev" not in file_url:
                    return {
                        "url": file_url,
                        "format": "hls" if ".m3u8" in file_url else "mp4"
                    }
    except Exception as e:
        print(f"    [!] Error en config: {e}")
    return None

def extraer_stream_pelicula(movie_url):
    try:
        res = session.get(movie_url, headers={"Referer": f"{BASE_URL}/movies/"}, timeout=15)
        if res.status_code != 200:
            return None, None, None

        soup = BeautifulSoup(res.text, "html.parser")
        
        # Metadatos para el feed de Roku
        title_tag = soup.select_one("h1, .sheader .data h1")
        title = title_tag.get_text(strip=True) if title_tag else movie_url.rstrip("/").split("/")[-1]
        
        poster_tag = soup.select_one(".poster img, .sheader .poster img")
        poster = ""
        if poster_tag:
            poster = poster_tag.get("data-src") or poster_tag.get("src") or ""
            if poster.startswith("//"):
                poster = "https:" + poster

        player_item = soup.select_one("li[data-post][data-nume], div[data-post][data-nume]")
        if not player_item:
            return None, title, poster

        post_id = player_item.get("data-post")
        nume = player_item.get("data-nume")
        player_type = player_item.get("data-type", "movie")

        payload = {
            "action": "doo_player_ajax",
            "post": post_id,
            "nume": nume,
            "type": player_type
        }

        ajax_res = session.post(AJAX_URL, data=payload, headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": movie_url,
            "X-Requested-With": "XMLHttpRequest"
        }, timeout=15)

        if ajax_res.status_code == 200:
            embed_html = ajax_res.json().get("embed_url", "")
            src_match = re.search(r'src=["\']([^"\']+)["\']', embed_html)
            iframe_url = src_match.group(1) if src_match else embed_html

            if iframe_url.startswith("//"):
                iframe_url = "https:" + iframe_url

            stream = resolver_video_rumble(iframe_url)
            return stream, title, poster
            
    except Exception as e:
        print(f"    [!] Error en ajax: {e}")
        
    return None, None, None

def generar_feed(limite_peliculas=15):
    establecer_sesion()
    
    movie_links = []
    catalog_url = f"{BASE_URL}/movies/"
    print(f"[-] Intentando catálogo regular: {catalog_url}")
    
    res = session.get(catalog_url, timeout=15)
    if res.status_code == 200:
        soup = BeautifulSoup(res.text, "html.parser")
        items = soup.select("article.item.movies a, .item.movies a")
        for a in items:
            href = a.get("href", "")
            if href and href not in movie_links and href != catalog_url:
                movie_links.append(href)
    else:
        print(f"[!] Catálogo bloqueado ({res.status_code}). Conectando por sitemap...")
        movie_links = obtener_urls_sitemap()

    if not movie_links:
        print("[!] No se pudieron extraer URLs del catálogo ni del sitemap.")
        return

    print(f"[+] Total de títulos localizados: {len(movie_links)}. Procesando los primeros {limite_peliculas}...")

    peliculas_roku = []
    for movie_url in movie_links[:limite_peliculas]:
        slug = movie_url.rstrip("/").split("/")[-1]
        print(f"  -> Procesando: {slug}")
        
        stream_info, title, poster = extraer_stream_pelicula(movie_url)
        
        if stream_info:
            print(f"     [OK] Enlace extraído ({stream_info['format'].upper()})")
            peliculas_roku.append({
                "id": slug,
                "title": title or slug,
                "hdPosterUrl": poster,
                "description": "",
                "url": stream_info["url"],
                "streamFormat": stream_info["format"]
            })
        else:
            print("     [x] No disponible")

        time.sleep(1.5)

    with open("feed_roku.json", "w", encoding="utf-8") as f:
        json.dump(peliculas_roku, f, ensure_ascii=False, indent=2)

    print(f"\n[+] Proceso finalizado. {len(peliculas_roku)} películas guardadas en 'feed_roku.json'.")

if __name__ == "__main__":
    generar_feed(limite_peliculas=15)
