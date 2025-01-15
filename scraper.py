import aiohttp
import asyncio
from bs4 import BeautifulSoup
import json
from datetime import datetime, timedelta
import re
from colorama import Fore, init

init(autoreset=True)

BASE_URLS = ["https://repack-games.com/category/" + url for url in [
    "latest-updates/", "action-games/", "anime-games/", "adventure-games/",
    "building-games/", "exploration/", "multiplayer-games/", "open-world-game/",
    "fighting-games/", "horror-games/", "racing-game/", "shooting-games/",
    "rpg-pc-games/", "puzzle/", "sport-game/", "survival-games/",
    "simulation-game/", "strategy-games/", "sci-fi-games/", "adult/"
]]

JSON_FILENAME = "source.json"
INVALID_JSON_FILENAME = "invalid_games.json"
MAX_GAMES = 999999
CONCURRENT_REQUESTS = 100
REGEX_TITLE = r"(?:\(.*?\)|\s*(Free Download|v\d+(\.\d+)*[a-zA-Z0-9\-]*|Build \d+|P2P|GOG|Repack|Edition.*|FLT|TENOKE)\s*)"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}

processed_games_count = 0

class GameLimitReached(Exception):
    pass

def normalize_title(title):
    return re.sub(REGEX_TITLE, "", title).strip()

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

def load_invalid_games():
    try:
        with open(INVALID_JSON_FILENAME, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "updated": datetime.now().isoformat(),
            "invalid_games": []
        }

def save_invalid_game(title, reason, links=None):
    invalid_data = load_invalid_games()
    invalid_data["updated"] = datetime.now().isoformat()
    
    invalid_game = {
        "title": title,
        "reason": reason,
        "date": datetime.now().isoformat()
    }
    if links:
        invalid_game["links"] = links
        
    invalid_data["invalid_games"].append(invalid_game)
    
    with open(INVALID_JSON_FILENAME, 'w', encoding='utf-8') as f:
        json.dump(invalid_data, f, ensure_ascii=False, indent=4)

async def fetch_page(session, url, semaphore):
    async with semaphore:
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with session.get(url, headers=HEADERS, timeout=timeout) as response:
                if response.status == 200:
                    return await response.text()
                return None
        except Exception as e:
            print(f"Error fetching {url}: {str(e)}")
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
    if processed_games_count >= MAX_GAMES:
        raise GameLimitReached()

    page_content = await fetch_page(session, page_url, semaphore)
    if not page_content:
        return

    soup = BeautifulSoup(page_content, 'html.parser')
    articles = soup.find_all('div', class_='articles-content')
    if not articles:
        return

    remaining_games = MAX_GAMES - processed_games_count
    tasks = []
    
    for article in articles:
        if len(tasks) >= remaining_games:
            break
        
        for li in article.find_all('li'):
            if len(tasks) >= remaining_games:
                break
                
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
            save_invalid_game(title, "Ignored title pattern")
            print(f"Ignoring game with title: {title}")
            continue

        title_normalized = normalize_title(title)
        # Find all games with the same normalized title
        same_games = [g for g in existing_data["downloads"] if normalize_title(g["title"]) == title_normalized]
        
        if same_games:
            # Sort by upload date, most recent first
            same_games.sort(key=lambda x: x.get("uploadDate", ""), reverse=True)
            most_recent = same_games[0]
            
            # If current game is newer, update the most recent entry
            if upload_date and upload_date > most_recent.get("uploadDate", ""):
                most_recent.update({
                    "title": title,
                    "uris": links,
                    "fileSize": size,
                    "uploadDate": upload_date
                })
                log_game_status("UPDATED", page_num, title)
                
                # Remove other versions of the same game
                existing_data["downloads"] = [g for g in existing_data["downloads"] 
                                           if normalize_title(g["title"]) != title_normalized or g == most_recent]
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

async def get_file_size(session, link, headers, timeout):
    try:
        async with session.head(link, headers=headers, timeout=timeout) as response:
            if response.status == 200:
                content_length = response.headers.get('content-length')
                if (content_length):
                    size_bytes = int(content_length)
                    if size_bytes > 1073741824:
                        return f"{size_bytes / 1073741824:.2f} GB"
                    else:
                        return f"{size_bytes / 1048576:.2f} MB"
    except:
        pass
    return None

async def validate_single_link(session, link, semaphore, game_title):
    try:
        async with semaphore:
            timeout = aiohttp.ClientTimeout(total=30)
            
            if "pixeldrain.com" in link:
                file_id = link.split('/')[-1]
                api_url = f"https://pixeldrain.com/api/file/{file_id}/info"
                
                try:
                    async with session.get(api_url, headers=HEADERS, timeout=timeout) as response:
                        if response.status == 200:
                            json_data = await response.json()
                            
                            if json_data.get('name', '').lower().endswith(('.torrent', '.magnet')):
                                print(f"{Fore.RED}[TORRENT DETECTED] {game_title}: {link}")
                                return (None, None)
                                
                            if 'size' in json_data:
                                size_bytes = int(json_data['size'])
                                if size_bytes > 1073741824:
                                    file_size = f"{size_bytes / 1073741824:.2f} GB"
                                else:
                                    file_size = f"{size_bytes / 1048576:.2f} MB"
                                print(f"{Fore.GREEN}[VALID - Size: {file_size}] {game_title} - pixeldrain: {link}")
                                return (link, file_size)
                except Exception as e:
                    print(f"{Fore.YELLOW}[DEBUG] Pixeldrain API error: {str(e)}")
            
            async with session.get(link, headers=HEADERS, timeout=timeout) as response:
                if response.status != 200:
                    print(f"{Fore.RED}[INVALID] {game_title} - Status {response.status}: {link}")
                    return (None, None)
                
                result = await response.text()
                soup = BeautifulSoup(result, 'html.parser')
                
                if any(text in result.lower() for text in [
                    "file could not be found",
                    "unavailable for legal reasons",
                    "unavailable",
                    "qbittorrent",
                    "torrent",
                    "magnet:",
                    ".torrent"
                ]):
                    print(f"{Fore.RED}[INVALID/TORRENT] {game_title}: {link}")
                    return (None, None)

                file_size = None
                
                if "qiwi.gg" in link:
                    download_span = soup.find('span', string=re.compile(r'Download \d+'))
                    if download_span:
                        size_match = re.search(r'(\d+\.?\d*)\s*(GB|MB|KB)', download_span.text)
                        if size_match:
                            file_size = f"{size_match.group(1)} {size_match.group(2)}"

                domain = "1fichier" if "1fichier.com" in link else "qiwi" if "qiwi.gg" in link else "pixeldrain"
                size_info = f" - Size: {file_size}" if file_size else ""
                print(f"{Fore.GREEN}[VALID{size_info}] {game_title} - {domain}: {link}")
                
                return (link, file_size)

    except Exception as e:
        print(f"{Fore.RED}[ERROR] {game_title} - {link}: {str(e)}")
        return (None, None)

async def validate_links(session, games):
    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)
    print(f"\n{Fore.YELLOW}Starting link validation...{Fore.RESET}")
    
    games_to_keep = []
    total_links = sum(len(game["uris"]) for game in games)
    validated = 0
    
    for game in games:
        if not game["uris"]:
            save_invalid_game(game["title"], "No links available")
            continue
            
        print(f"\n{Fore.CYAN}Validating: {game['title']}{Fore.RESET}")
        tasks = [validate_single_link(session, link, semaphore, game['title']) for link in game["uris"]]
        results = await asyncio.gather(*tasks)
        
        valid_links = []
        invalid_links = []
        sizes = []
        
        for link, size in results:
            if link:
                valid_links.append(link)
                if size:
                    sizes.append(size)
            else:
                invalid_links.append(link)
        
        if valid_links and not (len(valid_links) == 1 and "1fichier.com" in valid_links[0]):
            game["uris"] = valid_links
            if sizes:
                max_size = max(sizes, key=lambda x: float(x.split()[0]) * (1024 if x.endswith('GB') else 1))
                game["fileSize"] = max_size
                print(f"{Fore.BLUE}[SIZE UPDATE] {game['title']} - Set to {max_size}")
            games_to_keep.append(game)
            validated += len(valid_links)
        else:
            reason = "Only 1fichier links" if (len(valid_links) == 1 and "1fichier.com" in valid_links[0]) else "All links invalid"
            save_invalid_game(game["title"], reason, {
                "valid_links": valid_links,
                "invalid_links": invalid_links,
                "original_links": game["uris"]
            })
            print(f"{Fore.RED}[REMOVED] {game['title']} - {reason}")
        
        print(f"Progress: {validated}/{total_links} links checked")
    
    games[:] = games_to_keep
    print(f"\n{Fore.GREEN}Validation completed: {validated} valid links found")
    print(f"Games remaining after validation: {len(games_to_keep)}")

async def cleanup():
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

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

    try:
        async with aiohttp.ClientSession() as session:
            for base_url in BASE_URLS:
                if processed_games_count >= MAX_GAMES:
                    break
                    
                try:
                    last_page_num = await fetch_last_page_num(session, semaphore, base_url)
                    for page_num in range(1, last_page_num + 1):
                        if processed_games_count >= MAX_GAMES:
                            break
                        page_url = f"{base_url}/page/{page_num}"
                        await process_page(session, page_url, semaphore, existing_data, page_num)
                except GameLimitReached:
                    break

            await validate_links(session, existing_data["downloads"])
            
            save_data(JSON_FILENAME, existing_data)
            print(f"\nScraping finished. Total games processed: {processed_games_count}")
    
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        await cleanup()

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(scrape_games())
    except KeyboardInterrupt:
        print("\nScript interrupted by user.")
    except Exception as e:
        print(f"\nUnexpected error: {str(e)}")
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        
        try:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
            
        loop.close()
        print("Script terminated.")
        
if __name__ == "__main__":
    main()
