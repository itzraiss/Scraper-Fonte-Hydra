import aiohttp
import asyncio
from bs4 import BeautifulSoup
import json
from datetime import datetime, timedelta
import re
from tqdm import tqdm
from colorama import Fore, init

init(autoreset=True)

BASE_URLS = [
    "https://repack-games.com/category/latest-updates/",
    "https://repack-games.com/category/action-games/",
    "https://repack-games.com/category/anime-games/",
    "https://repack-games.com/category/adventure-games/",
    "https://repack-games.com/category/building-games/",
    "https://repack-games.com/category/exploration/",
    "https://repack-games.com/category/multiplayer-games/",
    "https://repack-games.com/category/open-world-game/",
    "https://repack-games.com/category/fighting-games/",
    "https://repack-games.com/category/horror-games/",
    "https://repack-games.com/category/racing-game/",
    "https://repack-games.com/category/shooting-games/",
    "https://repack-games.com/category/rpg-pc-games/",
    "https://repack-games.com/category/puzzle/",
    "https://repack-games.com/category/sport-game/",
    "https://repack-games.com/category/survival-games/",
    "https://repack-games.com/category/simulation-game/",
    "https://repack-games.com/category/strategy-games/",
    "https://repack-games.com/category/sci-fi-games/",
    "https://repack-games.com/category/adult/"
]
JSON_FILENAME = "source.json"
MAX_GAMES = 99999
CONCURRENT_REQUESTS = 100

processed_games_count = 0

# Regex melhorada para lidar com edições P2P, DLCs e outras variações
REGEX_TITLE = r"(?:\(.*?\)|\s*(Free Download|v\d+(\.\d+)*[a-zA-Z0-9\-]*|Build \d+|P2P|GOG|Repack|Edition.*|FLT|TENOKE)\s*)"

def normalize_title(title):
    normalized_title = re.sub(REGEX_TITLE, "", title)
    return normalized_title.strip()

def load_existing_data(json_filename):
    try:
        with open(json_filename, 'r', encoding='utf-8') as json_file:
            return json.load(json_file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"name": "Shisuy's source", "downloads": []}

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
                if response.status == 200:
                    print(f"Successfully fetched page: {url}")
                    return await response.text()
                else:
                    print(f"Failed to fetch page: {url} with status: {response.status}")
                    return None
        except Exception as e:
            print(f"Exception occurred while fetching page: {url} - {e}")
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
        if any(domain in href for domain in ["1fichier.com", "qiwi.gg", "pixeldrain.com"]):
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

        if domain and domain not in filtered_links:
            filtered_links[domain] = link

    download_links = list(filtered_links.values())

    if len(download_links) == 1 and "1fichier.com" in download_links[0]:
        return title, size, [], upload_date

    return title, size, download_links, upload_date

async def fetch_last_page_num(session, semaphore, base_url):
    page_content = await fetch_page(session, base_url, semaphore)
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
        print(f"No content fetched for page: {page_url}")
        return

    soup = BeautifulSoup(page_content, 'html.parser')
    articles = soup.find_all('div', class_='articles-content')
    if not articles:
        print(f"No articles found on page: {page_url}")
        return

    tasks = []
    for article in articles:
        for li in article.find_all('li'):
            a_tag = li.find('a', href=True)
            if a_tag and 'href' in a_tag.attrs:
                tasks.append(fetch_game_details(session, a_tag['href'], semaphore))

    games = await asyncio.gather(*tasks, return_exceptions=True)
    for game in games:
        if isinstance(game, Exception):
            print(f"Exception occurred while fetching game details: {game}")
            continue

        if processed_games_count >= MAX_GAMES:
            break

        title, size, links, upload_date = game
        if not links:
            log_game_status("NO_LINKS", page_num, title)
            continue

        if "FULL UNLOCKED" in title.upper() or "CRACKSTATUS" in title.upper():
            print(f"Ignoring game with title: {title}")
            continue

        title_normalized = normalize_title(title)
        existing_game = next((g for g in existing_data["downloads"] if normalize_title(g["title"]) == title_normalized), None)
        if existing_game:
            if upload_date and upload_date > existing_game.get("uploadDate", ""):
                existing_game.update({
                    "title": title,
                    "uris": list(set(links)),
                    "fileSize": size,
                    "uploadDate": upload_date
                })
                log_game_status("UPDATED", page_num, title)
            else:
                existing_game["uris"] = list(set(existing_game["uris"] + links))
                log_game_status("IGNORED", page_num, title)
        else:
            existing_data["downloads"].append({
                "title": title,
                "uris": links,
                "fileSize": size,
                "uploadDate": upload_date
            })
            log_game_status("NEW", page_num, title)

async def validate_links(session, games):
    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)
    tasks = []
    for game in games:
        for link in game["uris"]:
            if "qiwi.gg" in link or "pixeldrain.com" in link:
                tasks.append((game, link, fetch_page(session, link, semaphore)))

    results = await asyncio.gather(*[task[2] for task in tasks], return_exceptions=True)
    for (game, link), result in zip([(task[0], task[1]) for task in tasks], results):
        if isinstance(result, Exception):
            continue

        soup = BeautifulSoup(result, 'html.parser')
        if "This file could not be found." in result or link.endswith(".torrent") or soup.find('h2', string="Unavailable for legal reasons") or "unavailable" in result.lower():
            game["uris"].remove(link)
        else:
            download_span = None
            if "qiwi.gg" in link:
                download_span = soup.find('span', string=re.compile(r'Download \d+(\.\d+)? (GB|MB)'))
            elif "pixeldrain.com" in link:
                download_span = soup.find(string=re.compile(r'Compressed size: \d+(\.\d+)? (GB|MB)'))

            if download_span:
                download_span = download_span.get_text() if hasattr(download_span, 'get_text') else download_span
                size_match = re.search(r'(\d+(\.\d+)?)\s*(GB|MB)', download_span)
                if size_match:
                    new_size = f"{size_match.group(1)} {size_match.group(3)}"
                    if "fileSize" not in game or compare_sizes(new_size, game["fileSize"]) > 0:
                        game["fileSize"] = new_size

    # Remover jogos sem links válidos ou apenas com links de 1fichier
    games[:] = [game for game in games if game["uris"] and not (len(game["uris"]) == 1 and "1fichier.com" in game["uris"][0])]

def compare_sizes(size1, size2):
    size1_value, size1_unit = size1.split()
    size2_value, size2_unit = size2.split()
    size1_value = float(size1_value)
    size2_value = float(size2_value)
    if size1_unit == size2_unit:
        return size1_value - size2_value
    elif size1_unit == "GB" and size2_unit == "MB":
        return size1_value - (size2_value / 1024)
    elif size1_unit == "MB" and size2_unit == "GB":
        return (size1_value / 1024) - size2_value
    return 0

async def scrape_games():
    global processed_games_count
    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)
    existing_data = load_existing_data(JSON_FILENAME)

    async with aiohttp.ClientSession() as session:
        for base_url in BASE_URLS:
            last_page_num = await fetch_last_page_num(session, semaphore, base_url)
            print(f"Processing base URL: {base_url} with last page number: {last_page_num}")

            for page_num in range(1, last_page_num + 1):
                if processed_games_count >= MAX_GAMES:
                    print(f"Limit of {MAX_GAMES} games reached. Continuing to link validation.")
                    break
                page_url = f"{base_url}/page/{page_num}"
                print(f"Processing page URL: {page_url}")
                await process_page(session, page_url, semaphore, existing_data, page_num)

        # Ensure link validation runs after game processing
        await validate_links(session, existing_data["downloads"])

    save_data(JSON_FILENAME, existing_data)
    print(f"Scraping finished. Total games processed: {processed_games_count}")

if __name__ == "__main__":
    asyncio.run(scrape_games())
