import aiohttp
import asyncio
from bs4 import BeautifulSoup
import json
from datetime import datetime, timedelta
import re
from tqdm import tqdm
from colorama import Fore, init

# Inicialização do Colorama
init(autoreset=True)

# Configurações gerais
BASE_URL = "https://repack-games.com/category/latest-updates/"
JSON_FILENAME = "all_games_data.json"
MAX_GAMES = 999999
CONCURRENT_REQUESTS = 100

processed_games_count = 0

# Constante para a regex
REGEX_TITULO = r"(?:\(.*?\)|\s*(Free Download|v\d+(\.\d+)*[a-zA-Z0-9\-]*|Build \d+|P2P|GOG|Repack|Edition.*|FLT|TENOKE)\s*)"


def normalizar_titulo(titulo):
    """Remove informações irrelevantes do título do jogo."""
    titulo_normalizado = re.sub(REGEX_TITULO, "", titulo)
    return titulo_normalizado.strip()


def load_existing_data(json_filename):
    try:
        with open(json_filename, 'r', encoding='utf-8') as json_file:
            return json.load(json_file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"name": "Shisuy's source [repack-games]", "downloads": []}


def save_data(json_filename, data):
    with open(json_filename, "w", encoding="utf-8") as json_file:
        json.dump(data, json_file, ensure_ascii=False, indent=4)


def parse_relative_date(date_str):
    now = datetime.now()
    try:
        if "hour" in date_str:
            result_date = now - timedelta(hours=int(re.search(r'(\d+)', date_str).group(1)))
        elif "day" in date_str:
            result_date = now - timedelta(days=int(re.search(r'(\d+)', date_str).group(1)))
        elif "week" in date_str:
            result_date = now - timedelta(weeks=int(re.search(r'(\d+)', date_str).group(1)))
        elif "month" in date_str:
            result_date = now - timedelta(days=30 * int(re.search(r'(\d+)', date_str).group(1)))
        elif "year" in date_str:
            result_date = now - timedelta(days=365 * int(re.search(r'(\d+)', date_str).group(1)))
        else:
            return now.isoformat()

        return result_date.isoformat()
    except Exception:
        return now.isoformat()


def log_game_status(status, page, game_title):
    global processed_games_count
    if status == "NEW":
        processed_games_count += 1
        print(f"{Fore.GREEN}[NEW GAME] Page {page}: {game_title} - Games Processed: {processed_games_count}")
    elif status == "UPDATED":
        print(f"{Fore.YELLOW}[UPDATED] Page {page}: {game_title}")
    elif status == "IGNORED":
        print(f"{Fore.CYAN}[IGNORED] Page {page}: {game_title}")
    elif status == "NO_LINKS":
        print(f"{Fore.RED}[NO LINKS] Page {page}: {game_title}")


async def fetch_page(session, url, semaphore):
    async with semaphore:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            timeout = aiohttp.ClientTimeout(total=50)
            async with session.get(url, headers=headers, timeout=timeout) as response:
                return await response.text() if response.status == 200 else None
        except Exception:
            return None


async def fetch_game_details(session, game_url, semaphore):
    page_content = await fetch_page(session, game_url, semaphore)
    if not page_content:
        return None, None, [], None

    soup = BeautifulSoup(page_content, 'html.parser')

    title = soup.find('h1', class_='entry-title').get_text(strip=True) if soup.find('h1', class_='entry-title') else "Unknown Title"

    size = "Undefined"
    size_patterns = [
        r"(\d+(\.\d+)?)\s*(GB|MB)\s+available space",
        r"Storage:\s*(\d+(\.\d+)?)\s*(GB|MB)"
    ]
    for pattern in size_patterns:
        match = re.search(pattern, page_content, re.IGNORECASE)
        if match:
            size_value = match.group(1)
            size_unit = match.group(3).upper()
            size = f"{size_value} {size_unit}"
            break

    date_element = soup.select_one('.time-article.updated a')
    if date_element and date_element.text.strip():
        relative_date_str = date_element.text.strip()
        upload_date = parse_relative_date(relative_date_str)
    else:
        upload_date = None

    all_links = []
    for tag in soup.find_all('a', href=True):
        href = tag['href']
        if any(domain in href for domain in ["1fichier.com", "qiwi.gg", "pixeldrain.com", "gofile.io"]):
            all_links.append(href)

    filtered_links = {}
    for link in all_links:
        domain = None
        if "1fichier.com" in link:
            domain = "1fichier"
        elif "qiwi.gg" in link:
            domain = "qiwi"
        elif "pixeldrain.com" in link:
            domain = "pixeldrain"
        elif "gofile.io" in link:
            domain = "gofile"

        if domain and domain not in filtered_links:
            filtered_links[domain] = link

    download_links = list(filtered_links.values())

    if len(download_links) == 1 and "1fichier.com" in download_links[0]:
        return title, size, [], upload_date

    return title, size, download_links, upload_date


async def fetch_last_page_num(session, semaphore):
    page_content = await fetch_page(session, BASE_URL, semaphore)
    if not page_content:
        return 1

    soup = BeautifulSoup(page_content, 'html.parser')
    last_page_tag = soup.find('a', class_='last', string='Last »')
    if last_page_tag:
        match = re.search(r'page/(\d+)', last_page_tag['href'])
        if match:
            return int(match.group(1))
    return 1


async def process_page(session, page_url, semaphore, existing_data, page_num):
    global processed_games_count
    page_content = await fetch_page(session, page_url, semaphore)
    if not page_content:
        return

    soup = BeautifulSoup(page_content, 'html.parser')
    articles = soup.find_all('div', class_='articles-content')

    tasks = []
    for article in articles:
        for li in article.find_all('li'):
            a_tag = li.find('a', href=True)
            if a_tag and 'href' in a_tag.attrs:
                tasks.append(fetch_game_details(session, a_tag['href'], semaphore))

    games = await asyncio.gather(*tasks, return_exceptions=True)
    for game in games:
        if isinstance(game, Exception):
            continue

        if processed_games_count >= MAX_GAMES:
            break

        title, size, links, upload_date = game
        if not links:
            log_game_status("NO_LINKS", page_num, title)
            continue

        title_normalized = normalizar_titulo(title)
        existing_game = next((g for g in existing_data["downloads"] if normalizar_titulo(g["title"]) == title_normalized), None)
        if existing_game:
            if upload_date and upload_date > existing_game.get("uploadDate", ""):
                existing_game.update({
                    "title": title,
                    "uris": list(set(existing_game["uris"] + links)),
                    "fileSize": size,
                    "uploadDate": upload_date
                })
                log_game_status("UPDATED", page_num, title)
            else:
                log_game_status("IGNORED", page_num, title)
        else:
            existing_data["downloads"].append({
                "title": title,
                "uris": links,
                "fileSize": size,
                "uploadDate": upload_date
            })
            log_game_status("NEW", page_num, title)


async def scrape_games():
    global processed_games_count
    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)
    existing_data = load_existing_data(JSON_FILENAME)

    async with aiohttp.ClientSession() as session:
        last_page_num = await fetch_last_page_num(session, semaphore)

        for page_num in range(1, last_page_num + 1):
            if processed_games_count >= MAX_GAMES:
                print(f"Limite de {MAX_GAMES} jogos atingido. Encerrando o scraping.")
                break
            page_url = f"{BASE_URL}/page/{page_num}"
            await process_page(session, page_url, semaphore, existing_data, page_num)

    save_data(JSON_FILENAME, existing_data)
    print(f"Scraping finalizado. Total de jogos processados: {processed_games_count}")


if __name__ == "__main__":
    asyncio.run(scrape_games())
