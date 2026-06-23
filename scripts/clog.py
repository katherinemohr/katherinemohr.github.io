#!/usr/bin/env python3
"""
Clog.py - A script to add website entries to the clog database.

Usage:
    python clog.py [URL] [options]

This script will:
1. Fetch the title of the provided URL
2. Confirm the title with the user
3. Optionally ask for notes about the link
4. Add an entry to _db/clog.db with Link, Title, Type, Authors, Notes, and AddedAt
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
    """Initialize the database with the required tables if they don't exist."""
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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS unread (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Link TEXT NOT NULL UNIQUE,
            Title TEXT NOT NULL,
            Active INTEGER NOT NULL DEFAULT 1,
            AddedAt TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def add_entry(
    db_path, link, title, entry_type="post", authors=None, bibtex=None, notes=None
):
    """Add a new entry to the clog database."""
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO clog (Link, Title, Type, Authors, Bibtex, Notes, AddedAt) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (link, title, entry_type, authors, bibtex, notes, current_time),
    )

    conn.commit()
    conn.close()

    authors_display = f" by {authors}" if authors else ""
    notes_display = f" with notes: {notes}" if notes else ""
    print(
        f"Added entry [{entry_type}]: {title}{authors_display} -> {link} at {current_time}{notes_display}"
    )


def update_unread_list(db_path, entries):
    """Update the unread table based on the provided list of (title, link) entries.

    For every entry in the list:
    1. If the link isn't already present in the unread table, add a new row with Active=1.
    2. If the link is present in the table, mark it active and update the title.
    3. For all rows in the table that were not accessed, set Active to 0.
    """
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # unread table is created in init_database

    # Normalize entries (strip whitespace and drop empties)
    normalized_entries = []
    for title, link in entries:
        title = (title or "").strip()
        link = (link or "").strip()
        if not link:
            continue
        if not title:
            title = link
        normalized_entries.append((title, link))

    # Track which links we touched
    touched_links = set()

    for title, link in normalized_entries:
        # See if link already exists
        cursor.execute("SELECT id FROM unread WHERE Link = ?", (link,))
        row = cursor.fetchone()
        if row is None:
            # Insert new row as active with provided title
            cursor.execute(
                """
                INSERT INTO unread (Link, Title, Active, AddedAt)
                VALUES (?, ?, 1, ?)
                """,
                (link, title, current_time),
            )
        else:
            # Row exists: mark as active and refresh title
            cursor.execute(
                """
                UPDATE unread
                SET Active = 1,
                    Title = ?
                WHERE Link = ?
                """,
                (title, link),
            )

        touched_links.add(link)

    # Deactivate all rows not touched in this run
    if touched_links:
        # Use a parameterized NOT IN clause; only touch rows that are currently active
        placeholders = ",".join("?" for _ in touched_links)
        params = list(touched_links)
        cursor.execute(
            f"""
            UPDATE unread
            SET Active = 0
            WHERE Active = 1
              AND Link NOT IN ({placeholders})
            """,
            params,
        )
    else:
        # No entries: deactivate everything that is currently active
        cursor.execute(
            """
            UPDATE unread
            SET Active = 0
            WHERE Active = 1
            """
        )

    conn.commit()
    conn.close()


def git_commit_and_push(db_path):
    """Git commit and push the database file."""
    try:
        # Get the directory containing this script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        repo_dir = os.path.dirname(script_dir)  # Go up one level to the repo root

        # Change to repo directory
        os.chdir(repo_dir)

        # Switch to main branch if not already on it
        current_branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        switched_branch = current_branch != "main"
        if switched_branch:
            subprocess.run(
                ["git", "stash", "push", "-m", "switching to main to add to clog"],
                check=True,
            )
            subprocess.run(["git", "checkout", "main"], check=True)

        # Add the database file
        subprocess.run(["git", "add", "_db/clog.db"], check=True)

        # Commit with a descriptive message
        commit_msg = "Add new clog entry"
        subprocess.run(["git", "commit", "-m", commit_msg], check=True)

        # Push to remote
        subprocess.run(["git", "push"], check=True)

        print("Successfully committed and pushed changes to git.")

        # Restore original branch and stashed changes
        if switched_branch:
            subprocess.run(["git", "checkout", current_branch], check=True)
            subprocess.run(["git", "stash", "pop"], check=True)

    except subprocess.CalledProcessError as e:
        print(f"Git operation failed: {e}")
    except Exception as e:
        print(f"Error during git operations: {e}")


def main():
    """Main function to orchestrate the clog entry process."""
    parser = argparse.ArgumentParser(
        description="Add website entries to the clog database or manage the unread list",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python clog.py https://example.com
  python clog.py example.com --commit
  python clog.py https://example.com -t blog
  python clog.py BIBTEX_ENTRY --type paper

  # Unread mode: paste Safari-style Title/Link pairs, end with EOF (Ctrl-D)
  # Example:
  #
  #   random
  #
  #   Some Title
  #   https://example.com
  #
  #   Another Title
  #   https://example.org
  #
  python clog.py --type unread
        """,
    )

    parser.add_argument("input", nargs="?", help="The URL to add to the clog")
    parser.add_argument(
        "-t",
        "--type",
        choices=["post", "blog", "paper", "unread"],
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

    # Initialize database (creates tables if needed)
    init_database(db_path)

    # Handle unread list updates
    if args.type == "unread":
        print(
            "Paste Safari tab group export (Title/Link pairs). Press Ctrl-D (EOF) when done:"
        )
        stdin_data = sys.stdin.read()
        lines = [line.strip() for line in stdin_data.splitlines()]

        entries = []
        i = 0

        # Ignore leading blank lines and a single group name line (e.g., "random")
        while i < len(lines) and lines[i] == "":
            i += 1
        if i < len(lines) and lines[i] != "":
            # Treat this as the tab group name and skip it
            i += 1

        # Expect Title/Link pairs separated by blank lines
        while i < len(lines):
            # Skip any extra blank lines between entries
            while i < len(lines) and lines[i] == "":
                i += 1
            if i >= len(lines):
                break

            title = lines[i]
            i += 1

            # Skip blank lines between title and link
            while i < len(lines) and lines[i] == "":
                i += 1
            if i >= len(lines):
                break

            link = lines[i]
            i += 1

            entries.append((title, link))

        # Fallback: if nothing parsed but an input value was provided, treat it as a single link
        if not entries and input_value:
            entries = [(input_value, input_value)]

        if not entries:
            print("No Title/Link pairs provided for unread update. Exiting.")
            sys.exit(1)

        try:
            update_unread_list(db_path, entries)
        except Exception as e:
            print(f"Error updating unread list: {e}")
            sys.exit(1)

        if args.commit:
            git_commit_and_push(db_path)
            print("Unread list successfully updated and pushed!")
        else:
            print("Unread list successfully updated (not committed to git)!")
        return

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
