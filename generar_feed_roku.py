def extraer_stream_pelicula(movie_url):
    try:
        res = session.get(movie_url, headers={"Referer": f"{BASE_URL}/"}, timeout=15)
        if res.status_code != 200:
            print(f"       -> Falló carga de página HTML (Status: {res.status_code})")
            return None, None, None

        soup = BeautifulSoup(res.text, "html.parser")
        
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
            print("       -> No se encontró elemento player (li/div con data-post)")
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

        if ajax_res.status_code != 200:
            print(f"       -> Falló admin-ajax.php (Status: {ajax_res.status_code})")
            return None, title, poster

        embed_html = ajax_res.json().get("embed_url", "")
        src_match = re.search(r'src=["\']([^"\']+)["\']', embed_html)
        iframe_url = src_match.group(1) if src_match else embed_html

        if iframe_url.startswith("//"):
            iframe_url = "https:" + iframe_url

        stream = resolver_video_rumble(iframe_url)
        return stream, title, poster
            
    except Exception as e:
        print(f"       -> Excepción: {e}")
        
    return None, None, None
