# Import required libraries
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import random
from datetime import datetime
import argparse
import sys
import requests
import json

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection': 'keep-alive'
}

def setup_driver(headless: bool = True) -> webdriver.Chrome:
    """Configure and return a Chrome WebDriver with resilient settings.

    Args:
        headless: Whether to run Chrome in headless mode.
    """
    chrome_options = Options()
    if headless:
        chrome_options.add_argument('--headless=new')  # new headless mode (Chrome 109+)
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--disable-notifications')
    chrome_options.add_argument('--disable-features=Translate,AutomationControlled')
    chrome_options.add_argument('--window-size=1400,1000')
    chrome_options.add_argument('--start-maximized')
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    # Reduce resource usage (disable images)
    prefs = {'profile.managed_default_content_settings.images': 2}
    chrome_options.add_experimental_option('prefs', prefs)
    chrome_options.page_load_strategy = 'eager'  # don't wait for all resources
    chrome_options.add_argument(f'user-agent={DEFAULT_HEADERS["User-Agent"]}')

    driver = webdriver.Chrome(options=chrome_options)
    # Set broader timeout
    driver.set_page_load_timeout(60)
    driver.implicitly_wait(5)
    return driver

def robust_get(driver: webdriver.Chrome, url: str, attempts: int = 3, wait_selector: tuple | None = None):
    """Attempt to load a URL with retries. On timeout, stop loading and use partial DOM.

    Args:
        driver: WebDriver instance.
        url: URL to load.
        attempts: max retry attempts.
        wait_selector: optional (By, locator) tuple to wait for presence.
    Returns:
        bool indicating success.
    """
    for attempt in range(1, attempts + 1):
        try:
            driver.get(url)
            if wait_selector:
                WebDriverWait(driver, 20).until(EC.presence_of_element_located(wait_selector))
            return True
        except TimeoutException:
            print(f"⚠ Timeout loading {url} (attempt {attempt}/{attempts}) – stopping load and using partial content.")
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass
            if wait_selector:
                try:
                    WebDriverWait(driver, 5).until(EC.presence_of_element_located(wait_selector))
                    return True
                except Exception:
                    pass
        except WebDriverException as e:
            print(f"⚠ WebDriver error on attempt {attempt}: {e}")
        if attempt < attempts:
            time.sleep(2 * attempt)
    return False

def enable_api_capture(driver: webdriver.Chrome):
    """Inject JS to intercept fetch and XHR for review/graphql calls."""
    script = r"""
    if (!window.__capturedRequests) {
        window.__capturedRequests = [];
        (function() {
            const pushReq = (obj) => { try { window.__capturedRequests.push(obj); } catch(e) {} };
            const origFetch = window.fetch;
            window.fetch = function(...args) {
                const [resource, config] = args;
                let url = typeof resource === 'string' ? resource : resource.url;
                let body = config && config.body ? (''+config.body).slice(0,1000) : null;
                let headers = null;
                try {
                  if (config && config.headers) {
                    if (config.headers instanceof Headers) {
                      headers = {};
                      config.headers.forEach((v,k)=> headers[k]=v);
                    } else if (typeof config.headers === 'object') {
                      headers = config.headers;
                    }
                  }
                } catch(e) {}
                const record = (respText) => {
                    pushReq({ type:'fetch', url, body, headers, time: Date.now(), responseSnippet: respText ? respText.slice(0,2000) : null });
                };
                try {
                    return origFetch.apply(this, args).then(resp => {
                        if (url.includes('graphql') || url.includes('review') || url.includes('reviews')) {
                            try { resp.clone().text().then(t => record(t)); } catch(e){ record(null); }
                        }
                        return resp;
                    });
                } catch(e) {
                    if (url.includes('graphql') || url.includes('review') || url.includes('reviews')) { record(null); }
                    throw e;
                }
            };
            const origOpen = XMLHttpRequest.prototype.open;
            const origSend = XMLHttpRequest.prototype.send;
            XMLHttpRequest.prototype.open = function(method, url) {
                this.__url = url; this.__method = method; return origOpen.apply(this, arguments);
            };
            XMLHttpRequest.prototype.send = function(body) {
                const b = body ? (''+body).slice(0,1000) : null;
                this.addEventListener('load', function() {
                    try {
                        if (this.__url && (this.__url.includes('graphql') || this.__url.includes('review') || this.__url.includes('reviews'))) {
                            pushReq({ type:'xhr', url:this.__url, method:this.__method, body:b, time: Date.now(), responseSnippet: (this.responseText||'').slice(0,2000) });
                        }
                    } catch(e) {}
                });
                return origSend.apply(this, arguments);
            };
        })();
    }
    """
    try:
        driver.execute_script(script)
        print("✓ API capture instrumentation injected")
    except Exception as e:
        print(f"⚠ Failed to inject API capture: {e}")

def get_captured_requests(driver: webdriver.Chrome):
    try:
        data = driver.execute_script("return window.__capturedRequests || [];")
        return data if isinstance(data, list) else []
    except Exception:
        return []

def get_book_details_selenium(driver, url: str):
    """Scrape basic book details using Selenium with fallback to requests."""
    print(f"Fetching book details from: {url}")

    success = robust_get(driver, url, wait_selector=(By.CSS_SELECTOR, 'h1'))
    if not success:
        print("⚠ Selenium failed to fully load page. Falling back to requests.")
        try:
            r = requests.get(url, headers=DEFAULT_HEADERS, timeout=30, verify=False)
            r.raise_for_status()
            html = r.text
        except Exception as e:
            print(f"✗ Fallback requests failed: {e}")
            return None
    else:
        html = driver.page_source

    soup = BeautifulSoup(html, 'lxml')
    book_details = {}

    title_element = (soup.find('h1', class_='Text__title1') or
                     soup.find('h1', class_='BookPageTitleSection__title') or
                     soup.find('h1'))
    book_details['title'] = title_element.text.strip() if title_element else 'Unknown'

    author_element = (soup.find('span', class_='ContributorLink__name') or
                      soup.find('a', class_='ContributorLink') or
                      soup.find('span', {'data-testid': 'name'}))
    book_details['author'] = author_element.text.strip() if author_element else 'Unknown'

    details_div = (soup.find('div', {'data-testid': 'bookDetails'}) or
                   soup.find('div', {'data-testid': 'publicationInfo'}))
    if details_div:
        details_text = details_div.get_text()
        pub_date_match = (re.search(r'First published (\w+ \d+,? \d{4})', details_text) or
                          re.search(r'Published\s+(\w+\s+\d+(?:st|nd|rd|th)?,?\s+\d{4})', details_text))
        book_details['publicationInfo'] = pub_date_match.group(1) if pub_date_match else None
        pages_match = re.search(r'(\d+)\s*pages?', details_text)
        book_details['pagesFormat'] = int(pages_match.group(1)) if pages_match else None
    else:
        book_details['publicationInfo'] = None
        book_details['pagesFormat'] = None

    genre_elements = (soup.find_all('span', class_='BookPageMetadataSection__genreButton') or
                      soup.find_all('span', {'data-testid': 'genreLink'}))
    book_details['genres'] = [g.text.strip() for g in genre_elements] if genre_elements else []

    rating_div = (soup.find('div', {'class': 'RatingStatistics__rating'}) or
                  soup.find('div', {'data-testid': 'average'}))
    if rating_div:
        try:
            book_details['overall_rating'] = float(rating_div.text.strip())
        except ValueError:
            book_details['overall_rating'] = None
    else:
        book_details['overall_rating'] = None

    reviews_element = (soup.find('div', {'data-testid': 'reviewsCount'}) or
                       soup.find('span', {'data-testid': 'reviewsCount'}))
    if reviews_element:
        reviews_text = reviews_element.text.strip()
        reviews_count = ''.join(filter(str.isdigit, reviews_text))
        book_details['overall_reviews'] = int(reviews_count) if reviews_count else 0
    else:
        book_details['overall_reviews'] = 0

    print(f"✓ Successfully scraped details for: {book_details['title']}")
    return book_details
    
def get_reviews_selenium(driver, url, num_reviews=1000, max_clicks=50, min_clicks=0, aggressive=False):
    '''
    Scrape reviews from Goodreads using Selenium to click "Show more reviews" button
    
    Parameters:
    - driver: Selenium WebDriver instance
    - url: Book URL
    - num_reviews: Target number of unique reviews to collect
    - max_clicks: Maximum number of times to click "Show more" button
    '''
    reviews_list = []
    seen_review_texts = set()
    clicks = 0
    consecutive_no_new = 0
    max_consecutive_no_new = 5 if aggressive else 3
    
    try:
        # Navigate to reviews page
        reviews_url = f"{url}/reviews"
        print(f"\nNavigating to: {reviews_url}")
        if not robust_get(driver, reviews_url, wait_selector=(By.CSS_SELECTOR, 'div')):
            print("✗ Could not load reviews page.")
            return reviews_list
        time.sleep(random.uniform(2, 3))
        
        while (len(reviews_list) < num_reviews or clicks < min_clicks) and clicks < max_clicks:
            # Parse current page content
            soup = BeautifulSoup(driver.page_source, 'lxml')
            
            # Find all review containers
            review_containers = (
                soup.find_all('div', class_='ReviewCard') or
                soup.find_all('article', class_='ReviewCard') or
                soup.find_all('div', class_='Review')
            )
            
            print(f"\nIteration {clicks + 1}: Found {len(review_containers)} review containers")
            new_reviews_this_iteration = 0
            
            # Extract review data
            for container in review_containers:
                if len(reviews_list) >= num_reviews:
                    break
                
                review = {}
                
                # Get rating
                rating_element = container.find(class_=re.compile(r'(?i)(star|rating|static)'))
                if not rating_element:
                    rating_element = container.find(attrs={'aria-label': re.compile(r'\d+\s+of\s+5')})
                
                if rating_element:
                    rating_text = rating_element.get('aria-label') or rating_element.get('title') or rating_element.text
                    rating_match = re.search(r"(\d+)", rating_text)
                    review['rating'] = int(rating_match.group(1)) if rating_match else None
                else:
                    review['rating'] = None
                
                # Get review text
                review_text_elem = (
                    container.find('div', class_='Formatted') or
                    container.find('div', class_='ReviewText') or
                    container.find('span', class_='Formatted')
                )
                review['review_text'] = review_text_elem.text.strip() if review_text_elem else ''
                
                # Extract review date
                review_date = None
                # Look for any anchor with /review/show/ whose text matches Month Day, Year
                month_names = '(January|February|March|April|May|June|July|August|September|October|November|December)'
                date_pattern = re.compile(rf'^ {month_names} \s+ \d{{1,2}}, \s* \d{{4}} $', re.X)
                # Direct anchors
                for a in container.find_all('a', href=True):
                    if '/review/show/' in a['href']:
                        text = a.get_text(strip=True)
                        if re.match(rf'^{month_names} \s+ \d{{1,2}}, \d{{4}}$', text):
                            try:
                                review_date = datetime.strptime(text, '%B %d, %Y').date().isoformat()
                            except Exception:
                                review_date = text
                            break
                if not review_date:
                    # Try span wrapper pattern provided
                    span_date = container.find('span', class_='Text Text__body3')
                    if span_date:
                        a = span_date.find('a', href=True)
                        if a and '/review/show/' in a['href']:
                            text = a.get_text(strip=True)
                            if re.match(rf'^{month_names} \s+ \d{{1,2}}, \d{{4}}$', text):
                                try:
                                    review_date = datetime.strptime(text, '%B %d, %Y').date().isoformat()
                                except Exception:
                                    review_date = text
                review['review_date'] = review_date

                # Get likes
                review['likes'] = 0
                like_patterns = [
                    r'(\d+)\s*likes?',
                    r'(\d+)\s*people liked this'
                ]
                
                for text in container.stripped_strings:
                    for pattern in like_patterns:
                        match = re.search(pattern, text, re.I)
                        if match:
                            review['likes'] = int(match.group(1))
                            break
                    if review['likes'] > 0:
                        break
                
                # Check if review is unique and has content
                if review['review_text']:
                    review_identifier = review['review_text'].strip().lower()
                    
                    if review_identifier and review_identifier not in seen_review_texts:
                        seen_review_texts.add(review_identifier)
                        reviews_list.append(review)
                        new_reviews_this_iteration += 1
            
            print(f"  → Added {new_reviews_this_iteration} new unique reviews")
            print(f"  → Total unique reviews: {len(reviews_list)}/{num_reviews}")
            
            # Check if we got new reviews
            if new_reviews_this_iteration == 0:
                consecutive_no_new += 1
                print(f"  ⚠ No new reviews found ({consecutive_no_new}/{max_consecutive_no_new})")
                
                if consecutive_no_new >= max_consecutive_no_new:
                    print(f"\n⛔ Stopping: No new reviews after {max_consecutive_no_new} attempts")
                    break
            else:
                consecutive_no_new = 0
            
            # Check if we have enough reviews
            if len(reviews_list) >= num_reviews and clicks >= min_clicks:
                print(f"\n✓ Target reached (and min_clicks satisfied): {len(reviews_list)} unique reviews collected")
                break
            
            # Try to click "Show more reviews" button
            try:
                # Wait for the button to be present and clickable
                wait = WebDriverWait(driver, 10)
                
                # Try multiple selectors for the "Show more" button
                button = None
                button_selectors = [
                    (By.CSS_SELECTOR, "button[data-testid='loadMore']"),
                    (By.XPATH, "//button[contains(., 'Show more reviews')]|//button[contains(., 'more reviews')]")
                ]
                
                for by, selector in button_selectors:
                    try:
                        button = wait.until(EC.element_to_be_clickable((by, selector)))
                        break
                    except TimeoutException:
                        continue
                
                if button:
                    # Scroll to button
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                    time.sleep(0.3)
                    # aggressive scroll cycles if enabled
                    if aggressive:
                        for _ in range(3):
                            driver.execute_script("window.scrollBy(0, document.body.scrollHeight);")
                            time.sleep(0.25)
                            driver.execute_script("window.scrollBy(0, -400);")
                            time.sleep(0.25)
                    driver.execute_script("window.scrollBy(0, 200);")
                    
                    # Click the button
                    try:
                        button.click()
                    except ElementClickInterceptedException:
                        # Try JavaScript click if regular click fails
                        driver.execute_script("arguments[0].click();", button)
                    
                    clicks += 1
                    print(f"  ✓ Clicked 'Show more' button (click #{clicks})")
                    
                    # Wait for new content to load
                    # Wait for DOM change (increase in ReviewCard count)
                    prev_count = len(review_containers)
                    for _ in range(16):  # up to ~8s
                        time.sleep(0.5)
                        new_soup = BeautifulSoup(driver.page_source, 'lxml')
                        new_count = len(new_soup.find_all('div', class_='ReviewCard'))
                        if new_count > prev_count:
                            break
                        if aggressive:
                            driver.execute_script("window.scrollBy(0, document.body.scrollHeight);")
                else:
                    print("\n⛔ No 'Show more' button found - reached end of reviews")
                    break
                    
            except TimeoutException:
                print("\n⛔ Timeout waiting for 'Show more' button - no more reviews available")
                break
            except Exception as e:
                print(f"\n⚠ Error clicking button: {e}")
                break
        
        print(f"\n{'='*60}")
        print(f"✓ Successfully scraped {len(reviews_list)} unique reviews")
        print(f"  Total button clicks: {clicks}")
        print(f"{'='*60}")
        
        return reviews_list
    
    except Exception as e:
        print(f"\n✗ Error scraping reviews: {e}")
        return reviews_list
    
def main():
    parser = argparse.ArgumentParser(description="Goodreads Selenium Scraper")
    parser.add_argument('--url', default='https://www.goodreads.com/book/show/68427.Elantris', help='Goodreads book URL')
    parser.add_argument('--num-reviews', type=int, default=100, help='Target number of unique reviews to collect')
    parser.add_argument('--max-clicks', type=int, default=15, help='Max number of show-more clicks')
    parser.add_argument('--headless', action='store_true', help='Run browser headless')
    parser.add_argument('--capture-api', action='store_true', help='Capture GraphQL/XHR requests for reviews')
    parser.add_argument('--min-clicks', type=int, default=0, help='Force at least this many load-more clicks (even if target met)')
    parser.add_argument('--aggressive', action='store_true', help='Enable aggressive scrolling & extended waits to trigger network loads')
    args = parser.parse_args()

    print("Initializing Chrome WebDriver...")
    driver = setup_driver(headless=args.headless)

    try:
        if args.capture_api:
            enable_api_capture(driver)
        book_details = get_book_details_selenium(driver, args.url)
        if not book_details:
            print("Failed to retrieve book details.")
            return

        print("\nBook Details:")
        print(pd.Series(book_details))

        print("\n" + "=" * 60)
        print("Starting review scraping...")
        print("=" * 60)
        reviews = get_reviews_selenium(
            driver,
            args.url,
            num_reviews=args.num_reviews,
            max_clicks=args.max_clicks,
            min_clicks=args.min_clicks,
            aggressive=args.aggressive,
        )

        reviews_df = pd.DataFrame(reviews)
        if reviews_df.empty:
            print("No reviews scraped.")
            return

        reviews_df['book_title'] = book_details.get('title', 'Unknown')
        reviews_df['review_length'] = reviews_df['review_text'].apply(lambda x: len(str(x)))
        reviews_df['word_count'] = reviews_df['review_text'].apply(lambda x: len(str(x).split()))
        # Ensure missing column handling
        if 'review_date' not in reviews_df.columns:
            reviews_df['review_date'] = None
        reviews_df = reviews_df[['rating', 'review_text', 'review_date', 'likes', 'review_length', 'book_title', 'word_count']]

        print("\n" + "=" * 60)
        print("RESULTS SUMMARY")
        print("=" * 60)
        print(f"Total reviews collected: {len(reviews_df)}")
        print(f"\nColumns: {list(reviews_df.columns)}")
        print("\nFirst 5 reviews:")
        print(reviews_df.head())

        # Save outputs
        safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', book_details.get('title', 'unknown'))
        pd.DataFrame([book_details]).to_csv(f'{safe_title}_details_selenium.csv', index=False)
        reviews_df.to_csv(f'{safe_title}_reviews_selenium.csv', index=False)
        print(f"\n✓ Data saved to {safe_title}_details_selenium.csv and {safe_title}_reviews_selenium.csv")

        if args.capture_api:
            captured = get_captured_requests(driver)
            api_log_file = f'{safe_title}_api_capture.json'
            with open(api_log_file, 'w', encoding='utf-8') as f:
                json.dump(captured, f, ensure_ascii=False, indent=2)
            print(f"✓ Captured {len(captured)} API request(s) -> {api_log_file}")
    finally:
        print("\nClosing browser...")
        driver.quit()
        print("Done!")

if __name__ == '__main__':
    # Suppress insecure request warnings for verify=False
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    main()