# Dragonsteel Capstone Project: Goodreads Data Analysis

## Overview
This project analyzes Goodreads data for Brandon Sanderson's books to explore reader engagement, sentiment, and trends. The project includes:

1. **Book Details**  
   - Author, title, published date, audience genre, description, average rating, total ratings, total reviews, non-audience genres, number currently reading, number who want to read, Goodreads book URL.

2. **Reviews**  
   - Review rating, review text, number of likes, review length, book title, word count.

## Project Structure

| Folder / File | Description |
|---------------|-------------|
| `Goodreads Data/` | Contains scraped CSVs and notebooks for combining & cleaning data. |
| `Details_Scraper.ipynb` | Notebook to scrape book details from Goodreads. |
| `Review_Scraper.ipynb` | Notebook to scrape book reviews. |
| `Combine_CSVs.ipynb` | Notebook to merge individual book CSVs into combined datasets. |
| `Reader_Engagement_and_Sentiment_Analysis.ipynb` | Analysis of reader engagement metrics and sentiment. |
| `Combined_Reviews.csv` | **Excluded from repo due to size**; keep locally or download separately. |
| `Combined_Details.csv` | Combined book details dataset. |
| `missing_ratings.csv` | Records of missing rating data handled during cleaning. |
| `.gitignore` | Ensures large files like `Combined_Reviews.csv` are not tracked. |

## Getting Started
1. Clone the repository:
```bash
git clone https://github.com/Gregag12/msba_capstone_dragonsteel.git
```
Download Combined_Reviews.csv from your local storage or cloud drive.

Run notebooks in the following order:

Combine_CSVs.ipynb

Reader_Engagement_and_Sentiment_Analysis.ipynb

Notes

The large dataset Combined_Reviews.csv is not included due to GitHub file size limits.

All other datasets, scripts, and notebooks are included for reproducibility.

---

## License
This project is licensed under the Apache License 2.0. See `LICENSE` for details.
