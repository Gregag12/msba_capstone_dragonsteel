"""
Goodreads GraphQL Review Scraper
Direct API access using discovered AppSync endpoint - bypasses Selenium pagination limits.
"""

import requests
import pandas as pd
import re
import time
import argparse
import json
from datetime import datetime
from typing import Optional, Dict, List

# Goodreads AppSync GraphQL endpoint
GRAPHQL_URL = "https://kxbwmqov6jgg3daaamb744ycu4.appsync-api.us-east-1.amazonaws.com/graphql"
API_KEY = "da2-xpgsdydkbregjhpr6ejzqdhuwy"

HEADERS = {
    'authority': 'kxbwmqov6jgg3daaamb744ycu4.appsync-api.us-east-1.amazonaws.com',
    'accept': '*/*',
    'accept-language': 'en-US,en;q=0.9',
    'content-type': 'application/json',
    'origin': 'https://www.goodreads.com',
    'referer': 'https://www.goodreads.com/',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
    'x-api-key': API_KEY,
}

GRAPHQL_QUERY = """
query getReviews($filters: BookReviewsFilterInput!, $pagination: PaginationInput) {
  getReviews(filters: $filters, pagination: $pagination) {
    ...BookReviewsFragment
    __typename
  }
}

fragment BookReviewsFragment on BookReviewsConnection {
  totalCount
  edges {
    node {
      ...ReviewCardFragment
      __typename
    }
    __typename
  }
  pageInfo {
    prevPageToken
    nextPageToken
    __typename
  }
  __typename
}

fragment ReviewCardFragment on Review {
  __typename
  id
  creator {
    ...ReviewerProfileFragment
    __typename
  }
  recommendFor
  updatedAt
  createdAt
  spoilerStatus
  lastRevisionAt
  text
  rating
  shelving {
    shelf {
      name
      displayName
      editable
      default
      actionType
      sortOrder
      webUrl
      __typename
    }
    taggings {
      tag {
        name
        webUrl
        __typename
      }
      __typename
    }
    webUrl
    __typename
  }
  likeCount
  commentCount
}

fragment ReviewerProfileFragment on User {
  id: legacyId
  imageUrlSquare
  isAuthor
  ...SocialUserFragment
  textReviewsCount
  name
  webUrl
  contributor {
    id
    works {
      totalCount
      __typename
    }
    __typename
  }
  __typename
}

fragment SocialUserFragment on User {
  followersCount
  __typename
}
"""


def extract_work_id_from_url(book_url: str) -> Optional[str]:
    """
    Extract work ID from Goodreads book page HTML.
    This requires fetching the page and parsing embedded JSON.
    """
    try:
        resp = requests.get(book_url, timeout=30, verify=False)
        resp.raise_for_status()
        html = resp.text
        
        # Look for __NEXT_DATA__ script containing work ID
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
        if match:
            data = json.loads(match.group(1))
            # Navigate through the structure to find work ID
            # Typical path: props.pageProps.apolloState.Book:kca://book/....__ref -> Work:kca://work/...
            apollo_state = data.get('props', {}).get('pageProps', {}).get('apolloState', {})
            
            # Find Work key
            for key in apollo_state:
                if key.startswith('Work:kca://work/'):
                    work_id = key.replace('Work:', '')
                    print(f"✓ Extracted work ID: {work_id}")
                    return work_id
            
            # Alternative: look in book object for work reference
            for key, value in apollo_state.items():
                if key.startswith('Book:') and isinstance(value, dict):
                    work_ref = value.get('work', {})
                    if isinstance(work_ref, dict) and '__ref' in work_ref:
                        work_id = work_ref['__ref'].replace('Work:', '')
                        print(f"✓ Extracted work ID from book reference: {work_id}")
                        return work_id
        
        print("⚠ Could not find work ID in page data")
        return None
    except Exception as e:
        print(f"✗ Error extracting work ID: {e}")
        return None


def get_reviews_graphql(work_id: str, num_reviews: int = 1000, batch_size: int = 30, delay: float = 0.5) -> List[Dict]:
    """
    Fetch reviews using GraphQL API with cursor pagination.
    
    Args:
        work_id: Goodreads work resource ID (e.g., "kca://work/amzn1.gr.work.v1.xxx")
        num_reviews: Target number of reviews to collect
        batch_size: Reviews per request (Goodreads default is 30)
        delay: Seconds to wait between requests
    
    Returns:
        List of review dictionaries
    """
    reviews = []
    cursor = None
    page = 0
    
    while len(reviews) < num_reviews:
        page += 1
        print(f"\n📄 Page {page}: Fetching up to {batch_size} reviews (cursor: {cursor[:20] if cursor else 'None'}...)")
        
        variables = {
            "filters": {
                "resourceType": "WORK",
                "resourceId": work_id
            },
            "pagination": {
                "limit": batch_size
            }
        }
        
        if cursor:
            variables["pagination"]["after"] = cursor
        
        payload = {
            "operationName": "getReviews",
            "query": GRAPHQL_QUERY,
            "variables": variables
        }
        
        try:
            response = requests.post(GRAPHQL_URL, headers=HEADERS, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if not data or 'data' not in data or data.get('data') is None:
                print(f"  ✗ No data in response")
                if 'errors' in data:
                    print(f"  ✗ GraphQL errors: {data['errors'][:2]}")  # Show first 2 errors
                break
            
            reviews_data = data.get('data', {}).get('getReviews', {})
            edges = reviews_data.get('edges', [])
            page_info = reviews_data.get('pageInfo', {})
            total_count = reviews_data.get('totalCount', 0)
            
            if not edges:
                print("  ⛔ No more reviews returned")
                break
            
            print(f"  ✓ Received {len(edges)} reviews (Total available: {total_count})")
            
            # Extract review data
            for edge in edges:
                node = edge.get('node', {})
                creator = node.get('creator', {})
                
                # Parse timestamps (milliseconds since epoch)
                created_at = node.get('createdAt')
                updated_at = node.get('updatedAt')
                
                if created_at:
                    try:
                        created_at = datetime.fromtimestamp(int(created_at) / 1000).date().isoformat()
                    except (ValueError, TypeError):
                        created_at = None
                
                if updated_at:
                    try:
                        updated_at = datetime.fromtimestamp(int(updated_at) / 1000).date().isoformat()
                    except (ValueError, TypeError):
                        updated_at = None
                
                # Strip HTML from review text
                review_text = node.get('text', '')
                if review_text:
                    # Simple HTML tag removal
                    review_text = re.sub(r'<[^>]+>', '', review_text)
                    review_text = review_text.replace('&nbsp;', ' ').replace('&amp;', '&')
                    review_text = review_text.replace('&lt;', '<').replace('&gt;', '>')
                    review_text = review_text.strip()
                
                review = {
                    'review_id': node.get('id'),
                    'rating': node.get('rating'),
                    'review_text': review_text,
                    'created_at': created_at,
                    'updated_at': updated_at,
                    'likes': node.get('likeCount', 0),
                    'comment_count': node.get('commentCount', 0),
                    'spoiler_status': node.get('spoilerStatus'),
                    'reviewer_name': creator.get('name', ''),
                    'reviewer_id': creator.get('id'),
                    'reviewer_url': creator.get('webUrl', ''),
                }
                
                reviews.append(review)
            
            # Check for next page
            next_token = page_info.get('nextPageToken')
            if not next_token:
                print("  ⛔ No nextPageToken - reached end of reviews")
                break
            
            cursor = next_token
            
            if len(reviews) >= num_reviews:
                print(f"\n✓ Target reached: {len(reviews)} reviews collected")
                break
            
            # Rate limiting
            time.sleep(delay)
            
        except requests.exceptions.RequestException as e:
            print(f"  ✗ Request error: {e}")
            break
        except (KeyError, json.JSONDecodeError) as e:
            print(f"  ✗ Parse error: {e}")
            break
    
    print(f"\n{'='*60}")
    print(f"✓ Total reviews collected: {len(reviews)}")
    print(f"{'='*60}")
    
    return reviews


def get_book_details(book_url: str) -> Dict:
    """Fetch basic book metadata from the book page (non-GraphQL fallback)."""
    try:
        resp = requests.get(book_url, timeout=30, verify=False)
        resp.raise_for_status()
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, 'lxml')
        
        details = {}
        
        title_elem = soup.find('h1', class_='Text__title1')
        details['title'] = title_elem.text.strip() if title_elem else 'Unknown'
        
        author_elem = soup.find('span', class_='ContributorLink__name')
        details['author'] = author_elem.text.strip() if author_elem else 'Unknown'
        
        rating_div = soup.find('div', class_='RatingStatistics__rating')
        if rating_div:
            try:
                details['overall_rating'] = float(rating_div.text.strip())
            except ValueError:
                details['overall_rating'] = None
        else:
            details['overall_rating'] = None
        
        reviews_elem = soup.find('div', {'data-testid': 'reviewsCount'})
        if reviews_elem:
            reviews_text = reviews_elem.text.strip()
            reviews_count = ''.join(filter(str.isdigit, reviews_text))
            details['overall_reviews'] = int(reviews_count) if reviews_count else 0
        else:
            details['overall_reviews'] = 0
        
        print(f"✓ Book details: {details['title']} by {details['author']}")
        return details
        
    except Exception as e:
        print(f"✗ Error fetching book details: {e}")
        return {'title': 'Unknown', 'author': 'Unknown', 'overall_rating': None, 'overall_reviews': 0}


def scrape_single_book(book_url: str, num_reviews: int, batch_size: int, delay: float) -> tuple[pd.DataFrame, Dict]:
    """Scrape a single book and return DataFrame of reviews and book details dict."""
    # Get book details
    book_details = get_book_details(book_url)
    
    # Extract work ID
    print("\nExtracting work ID from page...")
    work_id = extract_work_id_from_url(book_url)
    
    if not work_id:
        print("✗ Failed to extract work ID. Skipping.")
        return None, None
    
    # Fetch reviews via GraphQL
    print(f"\nFetching reviews via GraphQL API...")
    reviews = get_reviews_graphql(work_id, num_reviews=num_reviews, batch_size=batch_size, delay=delay)
    
    if not reviews:
        print("✗ No reviews collected.")
        return None, book_details
    
    # Convert to DataFrame
    df = pd.DataFrame(reviews)
    
    # Add book metadata
    df['book_title'] = book_details['title']
    df['book_author'] = book_details['author']
    
    # Add computed columns
    df['review_length'] = df['review_text'].apply(lambda x: len(str(x)) if x else 0)
    df['word_count'] = df['review_text'].apply(lambda x: len(str(x).split()) if x else 0)
    
    # Reorder columns for readability
    column_order = [
        'rating', 'review_text', 'created_at', 'likes', 'comment_count',
        'review_length', 'word_count', 'book_title', 'book_author',
        'reviewer_name', 'reviewer_id', 'review_id', 'spoiler_status'
    ]
    df = df[[col for col in column_order if col in df.columns]]
    
    return df, book_details


def main():
    parser = argparse.ArgumentParser(description="Goodreads GraphQL Review Scraper")
    parser.add_argument('--url', help='Single Goodreads book URL')
    parser.add_argument('--batch-file', help='CSV file with book URLs (columns: url, optional: num_reviews)')
    parser.add_argument('--num-reviews', type=int, default=1000, help='Target number of reviews per book')
    parser.add_argument('--batch-size', type=int, default=30, help='Reviews per API request')
    parser.add_argument('--delay', type=float, default=0.5, help='Delay between requests (seconds)')
    parser.add_argument('--book-delay', type=float, default=2.0, help='Delay between books in batch mode (seconds)')
    parser.add_argument('--output', help='Output CSV filename (auto-generated if not specified)')
    args = parser.parse_args()
    
    if not args.url and not args.batch_file:
        parser.error("Either --url or --batch-file must be provided")
    
    if args.url and args.batch_file:
        parser.error("Cannot use both --url and --batch-file; choose one")
    if args.url and args.batch_file:
        parser.error("Cannot use both --url and --batch-file; choose one")
    
    print("="*60)
    print("Goodreads GraphQL Review Scraper")
    print("="*60)
    
    # BATCH MODE
    if args.batch_file:
        print(f"\n📚 BATCH MODE: Processing books from {args.batch_file}")
        
        try:
            # Read batch file
            batch_df = pd.read_csv(args.batch_file)
            
            if 'url' not in batch_df.columns:
                print("✗ Error: CSV must have a 'url' column")
                return
            
            total_books = len(batch_df)
            print(f"Found {total_books} books to process\n")
            
            all_reviews = []
            all_book_details = []
            success_count = 0
            
            for idx, row in batch_df.iterrows():
                book_num = idx + 1
                book_url = row['url']
                
                # Per-book custom review count if provided
                book_num_reviews = int(row['num_reviews']) if 'num_reviews' in row and pd.notna(row['num_reviews']) else args.num_reviews
                
                print(f"\n{'='*60}")
                print(f"📖 Book {book_num}/{total_books}: {book_url}")
                print(f"   Target: {book_num_reviews} reviews")
                print(f"{'='*60}")
                
                try:
                    df, details = scrape_single_book(book_url, book_num_reviews, args.batch_size, args.delay)
                    
                    if df is not None and not df.empty:
                        all_reviews.append(df)
                        success_count += 1
                        print(f"✓ Collected {len(df)} reviews")
                    
                    if details:
                        all_book_details.append(details)
                    
                except Exception as e:
                    print(f"✗ Error processing book: {e}")
                
                # Rate limiting between books
                if book_num < total_books:
                    print(f"\n⏳ Waiting {args.book_delay}s before next book...")
                    time.sleep(args.book_delay)
            
            # Combine all results
            if all_reviews:
                print(f"\n{'='*60}")
                print("📊 COMBINING RESULTS")
                print(f"{'='*60}")
                
                combined_reviews = pd.concat(all_reviews, ignore_index=True)
                combined_details = pd.DataFrame(all_book_details)
                
                print(f"✓ Total reviews collected: {len(combined_reviews)}")
                print(f"✓ Books successfully scraped: {success_count}/{total_books}")
                print(f"\nReviews per book:")
                print(combined_reviews.groupby('book_title').size().sort_values(ascending=False))
                
                # Save combined files
                output_reviews = args.output if args.output else 'combined_reviews_graphql.csv'
                output_details = output_reviews.replace('_reviews_', '_details_')
                
                combined_reviews.to_csv(output_reviews, index=False, encoding='utf-8')
                combined_details.to_csv(output_details, index=False, encoding='utf-8')
                
                print(f"\n✓ Combined reviews saved to: {output_reviews}")
                print(f"✓ Combined details saved to: {output_details}")
            else:
                print("\n✗ No reviews collected from any books")
        
        except FileNotFoundError:
            print(f"✗ Error: File '{args.batch_file}' not found")
        except Exception as e:
            print(f"✗ Error in batch processing: {e}")
        
        return
    
    # SINGLE BOOK MODE
    print(f"\n📖 SINGLE BOOK MODE")
    df, book_details = scrape_single_book(args.url, args.num_reviews, args.batch_size, args.delay)
    
    if df is None or df.empty:
        print("✗ No reviews collected.")
        return
    
    # Display summary
    print("\n" + "="*60)
    print("RESULTS SUMMARY")
    print("="*60)
    print(f"Total reviews: {len(df)}")
    print(f"Columns: {list(df.columns)}")
    print("\nFirst 5 reviews:")
    print(df[['rating', 'review_text', 'created_at', 'likes']].head())
    print("\nRating distribution:")
    print(df['rating'].value_counts().sort_index())
    
    # Save to CSV
    if args.output:
        output_file = args.output
    else:
        safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', book_details['title'])
        output_file = f"{safe_title}_reviews_graphql.csv"
    
    df.to_csv(output_file, index=False, encoding='utf-8')
    print(f"\n✓ Data saved to {output_file}")
    
    # Also save book details
    details_file = output_file.replace('_reviews_', '_details_')
    pd.DataFrame([book_details]).to_csv(details_file, index=False)
    print(f"✓ Book details saved to {details_file}")


if __name__ == '__main__':
    # Suppress SSL warnings
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()
