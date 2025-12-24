#!/usr/bin/env python3
"""
Clog.py - A script to add website entries to the clog database.

Usage:
    python clog.py [URL] [options]

This script will:
1. Fetch the title of the provided URL
2. Confirm the title with the user
3. Optionally ask for notes about the link
4. Add an entry to _db/clog.db with Link, Title, Type, Authors, Notes, and AddedAt (UTC)
5. Git commit and push the changes (only if --commit is specified)
"""

import argparse
import datetime
import os
import sqlite3
import subprocess
import sys
from urllib.parse import urlparse

import bibtexparser
import requests
from bibtexparser.bparser import BibTexParser
from bs4 import BeautifulSoup


def get_website_title(url):
    """Fetch the title of a website from its URL."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, "html.parser")
        title = soup.find("title")

        if title:
            return title.get_text().strip()
        else:
            return "No title found"

    except requests.RequestException as e:
        print(f"Error fetching URL: {e}")
        return None
    except Exception as e:
        print(f"Error parsing title: {e}")
        return None


def confirm_title(title):
    """Ask user to confirm or edit the title."""
    print(f"Detected title: {title}")
    response = input("Is this correct? (y/n/edit): ").lower().strip()

    if response == "y" or response == "yes":
        return title
    elif response == "edit" or response == "e":
        new_title = input("Enter the correct title: ").strip()
        return new_title if new_title else title
    else:
        print("Operation cancelled.")
        return None


def get_notes():
    """Ask user for optional notes about the link."""
    response = input("Add notes about this link? (y/n): ").lower().strip()

    if response == "y" or response == "yes":
        notes = input("Enter your notes: ").strip()
        return notes if notes else None
    else:
        return None


def parse_bibtex(bibtex):
    """Parse bibtex entry and extract title, authors, and URL."""
    parser = BibTexParser()
    bib_database = bibtexparser.loads(bibtex, parser=parser)
    assert len(bib_database.entries) == 1

    entry = bib_database.entries[0]
    return entry["title"], entry["author"], entry["url"]


def get_bibtex():
    """Get bibtex entry from user."""
    print("Please paste the bibtex entry (end with empty line):")
    lines = []
    while True:
        line = input()
        if line.strip() == "":
            break
        lines.append(line)

    bibtex = "\n".join(lines)
    if not bibtex.strip():
        return None

    return bibtex


def init_database(db_path):
    """Initialize the database with the required table if it doesn't exist."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Link TEXT NOT NULL,
            Title TEXT NOT NULL,
            Type TEXT NOT NULL DEFAULT 'post',
            Authors TEXT,
            Bibtex TEXT,
            Notes TEXT,
            AddedAt TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def add_entry(
    db_path, link, title, entry_type="post", authors=None, bibtex=None, notes=None
):
    """Add a new entry to the clog database."""
    current_utc = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO clog (Link, Title, Type, Authors, Bibtex, Notes, AddedAt) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (link, title, entry_type, authors, bibtex, notes, current_utc),
    )

    conn.commit()
    conn.close()

    authors_display = f" by {authors}" if authors else ""
    notes_display = f" with notes: {notes}" if notes else ""
    print(
        f"Added entry [{entry_type}]: {title}{authors_display} -> {link} at {current_utc}{notes_display}"
    )


def git_commit_and_push(db_path):
    """Git commit and push the database file."""
    try:
        # Get the directory containing this script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        repo_dir = os.path.dirname(script_dir)  # Go up one level to the repo root

        # Change to repo directory
        os.chdir(repo_dir)

        # Add the database file
        subprocess.run(["git", "add", "_db/clog.db"], check=True)

        # Commit with a descriptive message
        commit_msg = "Add new clog entry"
        subprocess.run(["git", "commit", "-m", commit_msg], check=True)

        # Push to remote
        subprocess.run(["git", "push"], check=True)

        print("Successfully committed and pushed changes to git.")

    except subprocess.CalledProcessError as e:
        print(f"Git operation failed: {e}")
    except Exception as e:
        print(f"Error during git operations: {e}")


def main():
    """Main function to orchestrate the clog entry process."""
    parser = argparse.ArgumentParser(
        description="Add website entries to the clog database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python clog.py https://example.com
  python clog.py example.com --commit
  python clog.py https://example.com -t blog
  python clog.py BIBTEX_ENTRY --type paper
        """,
    )

    parser.add_argument("input", nargs="?", help="The URL to add to the clog")
    parser.add_argument(
        "-t",
        "--type",
        choices=["post", "blog", "paper"],
        default="post",
        help="Type of entry (default: post)",
    )
    parser.add_argument(
        "--commit", action="store_true", help="Commit and push changes to git"
    )

    args = parser.parse_args()
    input_value = args.input

    # Get the database path relative to the script location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(os.path.dirname(script_dir), "_db", "clog.db")

    # Handle papers differently
    if args.type == "paper":
        bibtex = get_bibtex()
        if not bibtex:
            print("No bibtex provided. Exiting.")
            sys.exit(1)

        title, authors, url = parse_bibtex(bibtex)
        if title is None:
            print("Failed to parse bibtex. Exiting.")
            sys.exit(1)

        print("Parsed from bibtex:")
        print(f"  Title: {title}")
        print(f"  Authors: {authors}")
        print(f"  URL: {url}")

        # Confirm title with user
        confirmed_title = confirm_title(title)
        if confirmed_title is None:
            sys.exit(1)
    else:
        # Handle regular URLs
        url = input_value
        # Add protocol if missing
        if not urlparse(url).scheme:
            url = "https://" + url

        bibtex = None
        authors = None

        print(f"Fetching title for: {url}")

        # Get website title
        title = get_website_title(url)
        if title is None:
            print("Failed to fetch website title. Exiting.")
            sys.exit(1)

        # Confirm title with user
        confirmed_title = confirm_title(title)
        if confirmed_title is None:
            sys.exit(1)

    # Get optional notes
    notes = get_notes()

    # Initialize database (creates table if needed)
    init_database(db_path)

    # Add entry to database
    try:
        add_entry(db_path, url, confirmed_title, args.type, authors, bibtex, notes)
    except Exception as e:
        print(f"Error adding entry to database: {e}")
        sys.exit(1)

    # Git commit and push (only if --commit is specified)
    if args.commit:
        git_commit_and_push(db_path)
        print("Clog entry successfully added and pushed!")
    else:
        print("Clog entry successfully added (not committed to git)!")


if __name__ == "__main__":
    main()
