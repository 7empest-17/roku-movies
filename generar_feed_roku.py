import json
import re
import time
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE_URL = "https://cinebel.cc"

# Inyección JS para eludir detección de automatización en Cloudflare
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['es-ES', 'es', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
"""

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

def resolver_video_rumble(context, embed_url):
    try:
        p = context.new_page()
        p.add_init_script(STEALTH_JS)
        p.goto(embed_url, wait_until="domcontentloaded", timeout=20000)
        html = p.content()
        p.close()

        # 1. Config ID de get_video_config.php
        config_match = re.search(r'const\s+configId\s*=\s*["\']([a-zA-Z0-9_-]+)["\']', html)
        if config_match:
            config_id = config_match.group(1)
            config_url = f"{BASE_URL}/get_video_config.php?id={config_id}"
            
            p_api = context.new_page()
            res = p_api.request.get(config_url, headers={"Referer": embed_url})
            if res.status == 200:
                data = res.json()
                p_api.close()
                for source in data.get("sources", []):
                    f = source.get("file", "")
                    if f and "test-streams.mux.dev" not in f:
                        return {
                            "url": f,
                            "format": "hls" if ".m3u8" in f else "mp4"
                        }
            else:
                p_api.close()

        # 2. Búsqueda de stream directo en el HTML
        streams = re.findall(r'https?://[^\s"\'<>]+\.(?:mp4|m3u8)[^\s"\'<>]*', html)
        for s in streams:
            if "mux.dev" not in s:
                return {"url": s, "format": "hls" if ".m3u8" in s else "mp4"}

    except Exception as e:
        print(f"       -> Error resolviendo rumble: {e}")
    return None

def esperar_desafio_si_aparece(page):
    for _ in range(6):
        title = page.title()
        content = page.content()
        if "Just a moment" in title or "Checking your browser" in content or "Cloudflare" in title:
            print("       [!] Cloudflare activo, esperando 3s...")
            time.sleep(3)
        else:
            break

def generar_feed(limite_peliculas=15):
    print("[-] Obteniendo lista de títulos desde el sitemap...")
    movie_links = obtener_urls_sitemap()

    if not movie_links:
        print("[!] No se encontraron URLs en el sitemap.")
        return

    print(f"[+] Total de títulos disponibles: {len(movie_links)}. Extrayendo los primeros {limite_peliculas}...")

    peliculas_roku = []

    with sync_playwright() as p:
        # Modo 'new' de headless en Chromium: indistinguible de un navegador real
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-size=1920,1080"
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="es-ES"
        )
        page = context.new_page()
        page.add_init_script(STEALTH_JS)

        print("[-] Validando acceso al home...")
        try:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=25000)
            esperar_desafio_si_aparece(page)
        except Exception:
            pass

        for movie_url in movie_links[:limite_peliculas]:
            slug = movie_url.rstrip("/").split("/")[-1]
            print(f"\n  -> Procesando: {slug}")

            try:
                page.goto(movie_url, wait_until="domcontentloaded", timeout=25000)
                esperar_desafio_si_aparece(page)

                html = page.content()
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

                # Opción 1: Iframe incrustado directamente
                iframe_elem = soup.select_one("#playernos1 iframe, .playex iframe, .source-box iframe")
                if iframe_elem and iframe_elem.get("src"):
                    iframe_url = iframe_elem.get("src")

                # Opción 2: Llamada DooPlay AJAX
                if not iframe_url:
                    player_item = soup.select_one("li[data-post][data-nume], div[data-post][data-nume]")
                    if player_item:
                        post_id = player_item.get("data-post")
                        nume = player_item.get("data-nume")
                        player_type = player_item.get("data-type", "movie")

                        ajax_res = page.request.post(
                            f"{BASE_URL}/wp-admin/admin-ajax.php",
                            form={
                                "action": "doo_player_ajax",
                                "post": post_id,
                                "nume": nume,
                                "type": player_type
                            },
                            headers={"Referer": movie_url}
                        )

                        if ajax_res.status == 200:
                            embed_html = ajax_res.json().get("embed_url", "")
                            src_match = re.search(r'src=["\']([^"\']+)["\']', embed_html)
                            iframe_url = src_match.group(1) if src_match else embed_html

                if not iframe_url:
                    print(f"       [x] No se encontró reproductor (Título leído: '{title}')")
                    continue

                if iframe_url.startswith("//"):
                    iframe_url = "https:" + iframe_url

                print(f"       -> Player detectado: {iframe_url[:55]}...")
                stream_info = resolver_video_rumble(context, iframe_url)

                if stream_info:
                    print(f"       [OK] Enlace obtenido ({stream_info['format'].upper()})")
                    peliculas_roku.append({
                        "id": slug,
                        "title": title,
                        "hdPosterUrl": poster,
                        "description": "",
                        "url": stream_info["url"],
                        "streamFormat": stream_info["format"]
                    })
                else:
                    print("       [x] No se pudo resolver URL directa de Rumble")

            except Exception as e:
                print(f"       -> Error: {e}")

            time.sleep(1)

        browser.close()

    with open("feed_roku.json", "w", encoding="utf-8") as f:
        json.dump(peliculas_roku, f, ensure_ascii=False, indent=2)

    print(f"\n[+] Finalizado: {len(peliculas_roku)} películas guardadas en 'feed_roku.json'.")

if __name__ == "__main__":
    generar_feed(limite_peliculas=15)
