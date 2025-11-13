# Goodreads GraphQL Review Scraper

Direct API scraper using Goodreads AppSync GraphQL endpoint. Bypasses Selenium limitations and can fetch unlimited reviews per book.

## Features

- ✅ **Direct GraphQL API** - No browser required
- ✅ **Unlimited pagination** - Cursor-based iteration through all reviews
- ✅ **Clean data** - HTML stripped, proper date parsing
- ✅ **Batch mode** - Process multiple books from CSV
- ✅ **Combined output** - Master CSV with all books

## Quick Start

### Single Book
```powershell
python graphql_scraper.py --url https://www.goodreads.com/book/show/68427.Elantris --num-reviews 1000
```

### Batch Processing (57 Books)
1. Create CSV file with your book URLs:
```csv
url,num_reviews
https://www.goodreads.com/book/show/68427.Elantris,1000
https://www.goodreads.com/book/show/17332218.The_Way_of_Kings,1000
...
```

2. Run batch scraper:
```powershell
python graphql_scraper.py --batch-file book_urls.csv --delay 0.2 --book-delay 2
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--url` | Single book URL | - |
| `--batch-file` | CSV with book URLs | - |
| `--num-reviews` | Reviews per book | 1000 |
| `--batch-size` | Reviews per API request | 30 |
| `--delay` | Seconds between API requests | 0.5 |
| `--book-delay` | Seconds between books (batch) | 2.0 |
| `--output` | Custom output filename | auto-generated |

## Output Files

### Single Book Mode
- `{BookTitle}_reviews_graphql.csv` - Review data (13 columns)
- `{BookTitle}_details_graphql.csv` - Book metadata

### Batch Mode
- `combined_reviews_graphql.csv` - All reviews from all books
- `combined_details_graphql.csv` - Metadata for all books

## CSV Input Format

**Minimal** (uses default num_reviews):
```csv
url
https://www.goodreads.com/book/show/68427.Elantris
https://www.goodreads.com/book/show/17332218.The_Way_of_Kings
```

**With custom counts per book**:
```csv
url,num_reviews
https://www.goodreads.com/book/show/68427.Elantris,500
https://www.goodreads.com/book/show/17332218.The_Way_of_Kings,1500
```

## Review Columns

- `rating` - 1-5 stars (or 0 if no rating)
- `review_text` - Full review text (HTML stripped)
- `created_at` - Review date (ISO format: YYYY-MM-DD)
- `likes` - Number of likes
- `comment_count` - Number of comments
- `review_length` - Character count
- `word_count` - Word count
- `book_title` - Book title
- `book_author` - Author name
- `reviewer_name` - Reviewer username
- `reviewer_id` - Goodreads user ID
- `review_id` - Unique review ID
- `spoiler_status` - Spoiler flag

## Performance

- ~30 reviews per request (0.2-0.5s per request)
- ~1000 reviews/book in ~7 seconds
- 57 books × 1000 reviews = ~57,000 reviews in ~10-15 minutes

## Example: Full Project Run

```powershell
# Process all 57 books, 1000 reviews each
python graphql_scraper.py --batch-file my_57_books.csv --num-reviews 1000 --delay 0.3 --book-delay 2 --output dragonsteel_reviews.csv
```

Result: `dragonsteel_reviews.csv` with ~57,000 reviews across all books.
