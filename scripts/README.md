# Link Scripts

## Hacker News

Fetch and confirm a page title, then open Hacker News's prefilled submission
form in your default browser:

```bash
./hn.py https://example.com
```

You must be logged in to Hacker News in that browser. Review the title and URL,
then click `submit` to finish posting. `post_to_hacker_news(url, title)` is kept
separate so it can also be called from `clog.py` in a future `--hn_post` flow.

## Clog

A Python script for adding website entries to the clog database.

## Setup

1. Install the required dependencies:
```bash
pip install -r requirements.txt
```

2. Make sure you're in a git repository with the `_db/clog.db` file.

## Usage

```bash
python clog.py [URL]
```

Example:
```bash
python clog.py https://example.com
python clog.py example.com  # Protocol will be added automatically
```

## What it does

1. Fetches the website title from the provided URL
2. Shows you the detected title and asks for confirmation
3. Allows you to edit the title if needed
4. Adds an entry to `_db/clog.db` with:
   - Link: The provided URL
   - Title: The confirmed title
   - AddedAt: Current UTC timestamp
5. Automatically commits and pushes the database changes to git

## Database Schema

The script creates a SQLite table with the following structure:

```sql
CREATE TABLE IF NOT EXISTS clog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    Link TEXT NOT NULL,
    Title TEXT NOT NULL,
    AddedAt TEXT NOT NULL
);
```

## Requirements

- Python 3.6+
- Git repository with push access
- Internet connection to fetch website titles
- Dependencies listed in `requirements.txt`
