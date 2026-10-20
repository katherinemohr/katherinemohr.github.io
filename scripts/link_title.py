"""Helpers for fetching and confirming webpage titles."""

import requests
from bs4 import BeautifulSoup


def get_website_title(url):
    """Fetch the title of a website from its URL."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 "
            "Safari/537.36"
        }

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, "html.parser")
        title = soup.find("title")

        if title:
            return title.get_text().strip()
        return "No title found"

    except requests.RequestException as error:
        print(f"Error fetching URL: {error}")
        return None
    except Exception as error:
        print(f"Error parsing title: {error}")
        return None


def confirm_title(title):
    """Ask the user to confirm or edit a title."""
    print(f"Detected title: {title}")
    response = input("Is this correct? (y/n/edit): ").lower().strip()

    if response in ("y", "yes"):
        return title
    if response in ("edit", "e"):
        new_title = input("Enter the correct title: ").strip()
        return new_title if new_title else title

    print("Operation cancelled.")
    return None
