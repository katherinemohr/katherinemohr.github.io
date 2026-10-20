#!/usr/bin/env python3
"""Open Hacker News's submission form for a link.

Usage:
    hn.py LINK

The title is fetched and confirmed locally before the prefilled Hacker News
submission form opens in the default browser. The browser handles login and
the final submission.
"""

import argparse
import sys
import webbrowser
from urllib.parse import urlencode, urlparse

if __package__:
    from .link_title import confirm_title, get_website_title
else:
    from link_title import confirm_title, get_website_title


HN_SUBMIT_URL = "https://news.ycombinator.com/submitlink"


def normalize_url(url):
    """Add an HTTPS scheme when the supplied link does not have one."""
    if not urlparse(url).scheme:
        return "https://" + url
    return url


def build_submission_url(url, title):
    """Build Hacker News's prefilled link-submission URL."""
    return f"{HN_SUBMIT_URL}?{urlencode({'u': url, 't': title})}"


def post_to_hacker_news(url, title, opener=webbrowser.open_new_tab):
    """Open a prefilled HN submission form; return whether it was opened."""
    return opener(build_submission_url(url, title))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fetch a link's title and open it for submission to Hacker News"
    )
    parser.add_argument("link", help="The link to submit")
    args = parser.parse_args(argv)

    url = normalize_url(args.link)
    print(f"Fetching title for: {url}")

    title = get_website_title(url)
    if title is None:
        print("Failed to fetch website title. Exiting.")
        return 1

    confirmed_title = confirm_title(title)
    if confirmed_title is None:
        return 1

    submission_url = build_submission_url(url, confirmed_title)
    print("Opening the Hacker News submission form in your browser...")
    if not post_to_hacker_news(url, confirmed_title):
        print("Could not open a browser. Open this URL manually:")
        print(submission_url)
        return 1

    print("Review the prefilled link and title, then click submit on Hacker News.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
