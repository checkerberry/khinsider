#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download full soundtracks from KHInsider.

This script allows users to download entire music albums from KHInsider by
specifying the album ID found in the website's URL. It supports multiple audio
formats, optional album image download, and includes error handling for network
issues and invalid inputs.

Features:
  - Automatic directory creation with sanitized names
  - Format selection prioritization
  - Optional download of album images (e.g., cover art)
  - Connection reuse for improved performance
  - Comprehensive error reporting

Usage:
    python khinsider.py <soundtrack_id> [-o OUTPUT_DIR] [-f FORMATS] [-i] [-v]

Options:
  -o, --output    Output directory (default: sanitized album name)
  -f, --format    Preferred formats, comma-separated (e.g. 'flac,mp3')
  -i, --images    Download album images as well (e.g., cover art)
  -v, --verbose   Show detailed progress output

Examples:
    Download Aquaplus Vocal Collection Vol. 4 in FLAC:
        python khinsider.py --format flac "aquaplus-vocal-collection-vol.4"
    Download Minecraft OST in FLAC or MP3, plus images:
        python khinsider.py minecraft -f flac,mp3 -i -v

Report issues: https://github.com/obskyr/khinsider/issues
"""

import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, List, Optional
from urllib.parse import unquote, urljoin

import argparse
import requests
from bs4 import BeautifulSoup

# ------------------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------------------

BASE_URL = "https://downloads.khinsider.com/"
MAX_RETRIES = 3
CHUNK_SIZE = 64 * 1024  # 64KB
REPORT_URL = "https://github.com/obskyr/khinsider/issues"

# Precompiled regex patterns
_PRE_TD_RE = re.compile(br"^</td>\s*$", flags=re.MULTILINE)
_INVALID_ENTITY_RE = re.compile(br"&#([^0-9x]|x[^0-9A-Fa-f])")
_FILENAME_INVALID_RE = re.compile(r'[<>:"/\\|?*]')


# ------------------------------------------------------------------------------
# Exceptions
# ------------------------------------------------------------------------------

class ScriptError(Exception):
    """Base exception for script-specific errors."""


class NetworkError(ScriptError):
    """Raised when network operations fail after multiple attempts."""


class InvalidSoundtrackError(ScriptError):
    """Raised when the requested soundtrack doesn't exist or is unavailable."""


class InvalidFormatError(ScriptError):
    """Raised when none of the requested audio formats are available."""


# ------------------------------------------------------------------------------
# Utility Functions
# ------------------------------------------------------------------------------

@contextmanager
def suppress_output() -> Generator[None, None, None]:
    """Suppress stdout and stderr temporarily.

    Yields:
        None
    """
    with open(os.devnull, "w") as null:
        orig_stdout, orig_stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = null, null
        try:
            yield
        finally:
            sys.stdout, sys.stderr = orig_stdout, orig_stderr


def sanitize_filename(name: str) -> str:
    """Convert a string to a safe filesystem filename.

    Invalid characters are replaced with hyphens, trailing spaces or dots are
    removed, and Windows reserved names are suffixed with an underscore.

    Args:
        name: Original filename to sanitize.

    Returns:
        Sanitized filename.

    Examples:
        >>> sanitize_filename('A/B?C*.txt')
        'A-B-C-.txt'
    """
    sanitized = _FILENAME_INVALID_RE.sub("-", name).rstrip(" .")
    reserved = (
        {"", ".", "..", "~", "CON", "PRN", "AUX", "NUL"}
        | {f"COM{i}" for i in range(1, 10)}
        | {f"LPT{i}" for i in range(1, 10)}
    )
    if sanitized.upper() in reserved:
        return f"{sanitized}_"
    return sanitized


def get_soup(url: str, session: requests.Session) -> BeautifulSoup:
    """Fetch and parse HTML content from a URL using a persistent session.

    Applies preprocessing to fix known HTML issues before parsing.

    Args:
        url: The URL to fetch.
        session: Session object for HTTP requests.

    Returns:
        Parsed BeautifulSoup object.

    Raises:
        NetworkError: If the request fails or returns a bad status.
    """
    try:
        with suppress_output():
            response = session.get(url, timeout=15)
            response.raise_for_status()
        data = response.content
        data = _PRE_TD_RE.sub(b"", data)
        data = _INVALID_ENTITY_RE.sub(b"&amp;#\\1", data)
        return BeautifulSoup(data, "html.parser")
    except requests.RequestException as e:
        raise NetworkError(f"Failed to fetch {url}: {str(e)}") from e


# ------------------------------------------------------------------------------
# Core Classes
# ------------------------------------------------------------------------------


class AudioFile:
    """Metadata and download logic for a single file (audio or image).

    Args:
        url: Direct download URL.
        session: Shared HTTP session.

    Attributes:
        url: Download URL.
        filename: Decoded filename from the URL.
        extension: File extension (lowercase).
    """

    def __init__(self, url: str, session: requests.Session):
        self.url = url
        self.session = session
        self.filename = unquote(Path(url).name)
        self.extension = Path(url).suffix.lstrip(".").lower()

    def download(self, dest: Path) -> None:
        """Stream the file to disk.

        Args:
            dest: Destination path.

        Raises:
            requests.RequestException: On network error.
        """
        resp = self.session.get(self.url, stream=True, timeout=30)
        resp.raise_for_status()
        with dest.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    f.write(chunk)


class Song:
    """Represents a single track with multiple format options.

    Args:
        url: URL of the track detail page.
        session: Shared HTTP session.
    """

    def __init__(self, url: str, session: requests.Session):
        self.url = url
        self.session = session
        self._soup: Optional[BeautifulSoup] = None
        self._name: Optional[str] = None
        self._files: Optional[List[AudioFile]] = None

    @property
    def name(self) -> str:
        """Extract and sanitize the track name."""
        if self._name is None:
            soup = self._load_soup()
            name_tag = soup.find_all("p")[2].find("b")
            self._name = sanitize_filename(name_tag.get_text(strip=True))
        return self._name

    @property
    def files(self) -> List[AudioFile]:
        """List available audio format options."""
        if self._files is None:
            soup = self._load_soup()
            pattern = re.compile(r"/(?:soundtracks|ost)/")
            links = [a["href"] for a in soup.find_all("a", href=pattern)]
            self._files = [
                AudioFile(urljoin(self.url, link), self.session)
                for link in links
            ]
        return self._files

    def _load_soup(self) -> BeautifulSoup:
        """Lazy-load and cache the BeautifulSoup for this track page.

        Raises:
            InvalidSoundtrackError: If the page returns a 404-like title.
        """
        if self._soup is None:
            self._soup = get_soup(self.url, self.session)
            title_text = self._soup.find("title").get_text()
            if "404" in title_text:
                raise InvalidSoundtrackError(f"Track not found: {self.url}")
        return self._soup


class Soundtrack:
    """Handles album metadata and bulk download operations.

    Args:
        soundtrack_id: Album ID from KHInsider URL.
        session: Shared HTTP session.

    Attributes:
        id: Album identifier.
        url: Full album page URL.
    """

    def __init__(self, soundtrack_id: str, session: requests.Session):
        self.id = soundtrack_id
        self.session = session
        self.url = urljoin(BASE_URL, f"game-soundtracks/album/{self.id}")
        self._soup: Optional[BeautifulSoup] = None
        self._name: Optional[str] = None
        self._formats: Optional[List[str]] = None
        self._songs: Optional[List[Song]] = None
        self._images: Optional[List[AudioFile]] = None

    @property
    def name(self) -> str:
        """Get the official album name, sanitized for filesystem use.

        Raises:
            InvalidSoundtrackError: If the album page is invalid.
        """
        if self._name is None:
            soup = self._get_page()
            name_tag = soup.find("h2")
            if name_tag is None:
                raise InvalidSoundtrackError(f"Album page invalid: {self.url}")
            self._name = sanitize_filename(name_tag.get_text(strip=True))
        return self._name

    @property
    def formats(self) -> List[str]:
        """List available audio formats (e.g., ['mp3', 'flac'])."""
        if self._formats is None:
            soup = self._get_page()
            table = soup.find("table", id="songlist")
            if table is None:
                self._formats = ["mp3"]
            else:
                headers = [th.get_text(strip=True).lower()
                           for th in table.find_all("th")]
                self._formats = [
                    h for h in headers
                    if h not in {"track", "song name", "download", "size"}
                ] or ["mp3"]
        return self._formats

    @property
    def songs(self) -> List[Song]:
        """List Song objects for each track in the album."""
        if self._songs is None:
            soup = self._get_page()
            table = soup.find("table", id="songlist")
            links = [
                tr.find("a")["href"]
                for tr in table.find_all("tr")
                if tr.find("a")
            ]
            self._songs = [
                Song(urljoin(self.url, link), self.session)
                for link in links
            ]
        return self._songs

    @property
    def images(self) -> List[AudioFile]:
        """List album image files available for download."""
        if self._images is None:
            soup = self._get_page()
            table = soup.find("table")
            anchors = [
                a for a in table.find_all("a")
                if a.find("img")
            ] if table else []
            self._images = [
                AudioFile(urljoin(self.url, a["href"]), self.session)
                for a in anchors
            ]
        return self._images

    def _get_page(self) -> BeautifulSoup:
        """Lazy-load and validate the album page HTML.

        Raises:
            InvalidSoundtrackError: If the album is not found.
        """
        if self._soup is None:
            self._soup = get_soup(self.url, self.session)
            if self._soup.find(string="No such album"):
                raise InvalidSoundtrackError(f"Album not found: {self.id}")
        return self._soup

    def download(self,
                 output_dir: Path,
                 formats: Optional[List[str]] = None,
                 download_images: bool = False,
                 verbose: bool = False) -> bool:
        """Download the entire soundtrack and optionally album images.

        Args:
            output_dir: Directory to save tracks (and images) into.
            formats: Preferred audio formats in priority order.
            download_images: If True, also download album images.
            verbose: If True, show per-file progress.

        Returns:
            True if all requested files downloaded successfully.

        Raises:
            InvalidFormatError: If no requested audio formats are available.
            OSError: If output directory creation fails.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        if formats and not set(formats).intersection(self.formats):
            raise InvalidFormatError(f"Available formats: {', '.join(self.formats)}")

        total_tracks = len(self.songs)
        pad_tracks = len(str(total_tracks))
        success = True

        # Download audio tracks
        for idx, song in enumerate(self.songs, start=1):
            try:
                chosen = self._select_best(song, formats or [])
                if not self._save_item(chosen, output_dir, idx, total_tracks, pad_tracks, verbose):
                    success = False
            except Exception as e:
                success = False
                if verbose:
                    print(f"Error downloading track {idx}: {str(e)}", file=sys.stderr)

        # Download images if requested
        if download_images:
            total_imgs = len(self.images)
            pad_imgs = len(str(total_imgs))
            for idx, img in enumerate(self.images, start=1):
                try:
                    if not self._save_item(img, output_dir, idx, total_imgs, pad_imgs, verbose):
                        success = False
                except Exception as e:
                    success = False
                    if verbose:
                        print(f"Error downloading image {idx}: {str(e)}", file=sys.stderr)

        return success

    def _select_best(self, song: Song, prefs: List[str]) -> AudioFile:
        """Choose the highest-priority available AudioFile for a song."""
        if not prefs:
            return song.files[0]
        for fmt in prefs:
            for f in song.files:
                if f.extension == fmt.lower():
                    return f
        return song.files[0]

    def _save_item(self,
                   item: AudioFile,
                   output_dir: Path,
                   idx: int,
                   total: int,
                   pad: int,
                   verbose: bool) -> bool:
        """Download a single file with retry logic.

        Args:
            item: AudioFile object to download.
            output_dir: Destination directory.
            idx: Index of this file in its category.
            total: Total number of files in its category.
            pad: Width for zero-padding progress numbers.
            verbose: If True, print progress messages.

        Returns:
            True if download succeeded or was skipped.
        """
        dest = output_dir / sanitize_filename(item.filename)
        if dest.exists():
            if verbose:
                print(f"Skipping existing: {dest.name}")
            return True

        if verbose:
            label = f"[{idx:0{pad}d}/{total}]"
            print(f"{label} Downloading {dest.name}...")

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                item.download(dest)
                return True
            except requests.RequestException:
                if verbose and attempt < MAX_RETRIES:
                    print(f"Retry {attempt}/{MAX_RETRIES} for {dest.name}")
        return False


# ------------------------------------------------------------------------------
# Main Entry Point
# ------------------------------------------------------------------------------

def main() -> None:
    """Parse CLI args, configure session, and download the soundtrack."""
    parser = argparse.ArgumentParser(
        description="Download KHInsider soundtracks (spoofing Chrome UA)",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=f"Report issues: {REPORT_URL}"
    )
    parser.add_argument(
        "soundtrack",
        help=(
            "Album ID from KHInsider URL\n"
            "(e.g. 'kh2fm-soundtrack' from "
            "https://downloads.khinsider.com/game-soundtracks/album/kh2fm-soundtrack)"
        )
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Output directory (default: album name)"
    )
    parser.add_argument(
        "-f", "--format",
        help="Preferred audio formats, comma-separated (e.g. 'flac,mp3')"
    )
    parser.add_argument(
        "-i", "--images",
        action="store_true",
        help="Download album images as well (e.g., cover art)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed progress output"
    )

    args = parser.parse_args()

    try:
        with requests.Session() as session:
            session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/114.0.0.0 Safari/537.36"
                ),
                "Referer": BASE_URL
            })

            ost = Soundtrack(args.soundtrack, session)
            out_dir = args.output or Path(sanitize_filename(ost.name))

            if ost.download(
                output_dir=out_dir,
                formats=args.format.split(",") if args.format else None,
                download_images=args.images,
                verbose=args.verbose
            ):
                print("\nDownload completed successfully!")
                sys.exit(0)
            else:
                print("\nDownload completed with some errors.", file=sys.stderr)
                sys.exit(1)

    except KeyboardInterrupt:
        print("\nDownload cancelled by user.", file=sys.stderr)
        sys.exit(1)
    except ScriptError as e:
        print(f"\nError: {str(e)}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
