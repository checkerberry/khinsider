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
  -i, --images    Download album images (default: enabled; use --no-images to disable)
  -v, --verbose   Show detailed progress (default: enabled; use --no-verbose to disable)

Examples:
    Download Aquaplus Vocal Collection Vol. 4 in FLAC:
        python khinsider.py --format flac "aquaplus-vocal-collection-vol.4"
    Download Minecraft OST in FLAC or MP3, plus images:
        python khinsider.py https://downloads.khinsider.com/game-soundtracks/album/minecraft -f flac,mp3 -i -v

Report issues: https://github.com/obskyr/khinsider/issues
"""

import os
import re
import sys
import argparse
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, List, Optional
import importlib.util
from urllib.parse import unquote, urljoin
from dataclasses import dataclass
from urllib.parse import urlsplit


# ------------------------------------------------------------------------------
# Dependency bootstrap
# ------------------------------------------------------------------------------

_REQUIRED_PKGS = {
    "requests": "requests>=2.0,<3.0",
    "bs4": "beautifulsoup4>=4.4,<5.0",
}


def _in_venv() -> bool:
    """Return True if running inside a virtual environment."""
    base = getattr(sys, "base_prefix", sys.prefix)
    return sys.prefix != base or hasattr(sys, "real_prefix")


def _ensure_pip_available(verbose: bool = False) -> None:
    """Ensure 'pip' is importable for 'python -m pip' invocations."""
    try:
        import pip  # noqa: F401  # pylint: disable=unused-import
        return
    except Exception:
        pass

    try:
        import ensurepip  # type: ignore  # noqa: F401
    except Exception as exc:
        # Use RuntimeError here to avoid depending on later exception classes.
        raise RuntimeError(
            "pip is not available and the standard library 'ensurepip' module "
            "could not be imported to bootstrap it."
        ) from exc

    if verbose:
        print("Bootstrapping pip via ensurepip...", file=sys.stderr)
    subprocess.check_call(
        [sys.executable, "-m", "ensurepip", "--upgrade"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _install_with_pip(specs: List[str], verbose: bool = True) -> None:
    """Install the given requirement specs using pip.

    Uses --user when not in a virtualenv to avoid admin rights.
    """
    env = os.environ.copy()
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")

    cmd = [sys.executable, "-m", "pip", "install", "--upgrade"]
    if not _in_venv():
        cmd.append("--user")
    cmd.extend(specs)

    if verbose:
        print("Installing required packages: " + ", ".join(specs), file=sys.stderr)

    try:
        subprocess.check_call(
            cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "Automatic dependency installation failed. "
            "Install manually:\n  " + " ".join(cmd)
        ) from exc


def _ensure_runtime_dependencies(verbose: bool = True) -> None:
    """Ensure third-party dependencies exist; auto-install if missing.

    KHI_NO_AUTO_INSTALL=1 to skip auto-install.
    """
    if os.environ.get("KHI_NO_AUTO_INSTALL") == "1":
        return

    missing = [name for name in _REQUIRED_PKGS if importlib.util.find_spec(name) is None]
    if not missing:
        return

    _ensure_pip_available(verbose=verbose)
    specs = [_REQUIRED_PKGS[name] for name in missing]
    _install_with_pip(specs, verbose=verbose)


# Call the bootstrap BEFORE third-party imports.
_ensure_runtime_dependencies(verbose=True)

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

class SearchError(ScriptError):
    """Raised when a search operation cannot return results."""


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

_ALBUM_URL_RE = re.compile(
    r"^https?://(?:www\.)?downloads\.khinsider\.com/"
    r"game-soundtracks/album/([^/?#]+)(?:/)?$",
    flags=re.IGNORECASE,
)

def _extract_id_and_url(value: str) -> tuple[str, Optional[str]]:
    """Return (album_id, full_url_if_given_or_None) from user input."""
    value = value.strip()
    m = _ALBUM_URL_RE.match(value)
    if m:
        return m.group(1), value  # (id, full_url)
    return value, None

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
            response = session.get(url, timeout=30)
            response.raise_for_status()
        data = response.content
        data = _PRE_TD_RE.sub(b"", data)
        data = _INVALID_ENTITY_RE.sub(b"&amp;#\\1", data)
        return BeautifulSoup(data, "html.parser")
    except requests.RequestException as e:
        raise NetworkError(f"Failed to fetch {url}: {str(e)}") from e

def _soup_from_bytes(data: bytes) -> BeautifulSoup:
    """Parse HTML bytes into BeautifulSoup after KHInsider-specific fixes.

    Args:
        data: Raw response content.

    Returns:
        Parsed BeautifulSoup object.
    """
    fixed = _PRE_TD_RE.sub(b"", data)
    fixed = _INVALID_ENTITY_RE.sub(b"&amp;#\\1", fixed)
    with suppress_output():
        return BeautifulSoup(fixed, "html.parser")


def extract_soundtrack_id(candidate: str) -> str:
    """Return a soundtrack ID from a user-supplied ID or album URL.

    If the string looks like a full KHInsider album URL, the final path segment
    is extracted; otherwise it is returned as-is.

    Args:
        candidate: ID or album URL.

    Returns:
        The soundtrack ID.
    """
    m = _ALBUM_URL_RE.match(candidate.strip())
    return m.group(1) if m else candidate.strip()


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
        resp = self.session.get(self.url, stream=True, timeout=90)
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
            name_tag = soup.find_all("p")[2].find("b")  # type: ignore
            self._name = sanitize_filename(name_tag.get_text(strip=True))  # type: ignore
        return self._name

    @property
    def files(self) -> List[AudioFile]:
        """List available audio format options."""
        if self._files is None:
            soup = self._load_soup()
            pattern = re.compile(r"/(?:soundtracks|ost)/")
            links = [a["href"] for a in soup.find_all("a", href=pattern)]  # type: ignore
            self._files = [
                AudioFile(urljoin(self.url, link), self.session)  # type: ignore
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
            title_text = self._soup.find("title").get_text()  # type: ignore
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
        album_id, full_url = _extract_id_and_url(soundtrack_id)
        self.id = album_id
        self.session = session
        # If the user passed a full album URL, use it verbatim. Otherwise build it.
        self.url = full_url or urljoin(BASE_URL, f"game-soundtracks/album/{self.id}")
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
                           for th in table.find_all("th")]  # type: ignore
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
                tr.find("a")["href"]  # type: ignore
                for tr in table.find_all("tr")  # type: ignore
                if tr.find("a")  # type: ignore
            ]
            self._songs = [
                Song(urljoin(self.url, link), self.session)  # type: ignore
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
                a for a in table.find_all("a")  # type: ignore
                if a.find("img")  # type: ignore
            ] if table else []
            self._images = [
                AudioFile(urljoin(self.url, a["href"]), self.session)  # type: ignore
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

@dataclass(frozen=True)
class SearchResults:
    """Container for search results."""
    albums: List["Soundtrack"]
    songs: List["Soundtrack"]


def search_soundtracks(term: str, session: requests.Session) -> SearchResults:
    """Search KHInsider for albums and songs matching a term.

    The search endpoint may redirect straight to an album page when there is
    an exact match; handle that by returning a single-album result.

    Args:
        term: Free-text search term.
        session: Shared HTTP session.

    Returns:
        SearchResults with albums and song-title matches.

    Raises:
        SearchError: If the search fails or returns no parsable results.
        NetworkError: If the request itself fails.
    """
    try:
        resp = session.get(
            urljoin(BASE_URL, "search"),
            params={"search": term},
            timeout=30,
            allow_redirects=True,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise NetworkError(f"Failed to search for '{term}': {str(e)}") from e

    # If we were redirected directly to an album page, return that album.
    path = urlsplit(resp.url).path
    if path.startswith("/game-soundtracks/album/"):
        ost_id = path.rstrip("/").rsplit("/", 1)[-1]
        return SearchResults(albums=[Soundtrack(ost_id, session)], songs=[])

    soup = _soup_from_bytes(resp.content)

    tables = soup.find_all("table", class_="albumList")
    if not tables:
        # Typical page contains a <p> with a human message.
        message_tag = soup.find("p")
        message = message_tag.get_text(strip=True) if message_tag else ""
        raise SearchError(message or "No results returned.")

    def _parse_table(table: BeautifulSoup) -> List[Soundtrack]:
        """Parse one albumList table into Soundtrack stubs.

        We assign the discovered name directly to avoid extra requests when
        printing results later.
        """
        rows = table.find_all("tr")[1:]  # skip header row
        found: List[Soundtrack] = []
        for tr in rows:
            tds = tr.find_all("td")  # type: ignore
            if len(tds) < 2:
                continue
            anchor = tds[1].find("a")  # type: ignore
            if not anchor or not anchor.get("href"):  # type: ignore
                continue
            album_id = anchor["href"].rstrip("/").rsplit("/", 1)[-1]  # type: ignore
            name_text = anchor.get_text(strip=True)  # type: ignore
            ost = Soundtrack(album_id, session)
            # Pre-populate the cached name to avoid fetching each album page.
            ost._name = sanitize_filename(name_text)
            found.append(ost)
        return found

    parsed_tables = [_parse_table(t) for t in tables]  # type: ignore
    if len(parsed_tables) == 1:
        # If the page wording says it's song results, keep it in songs.
        page_p = soup.find(id="pageContent")
        text = (page_p.find("p").get_text(strip=True)  # type: ignore
                if page_p and page_p.find("p") else "")  # type: ignore
        if "song" in text.lower():
            return SearchResults(albums=[], songs=parsed_tables[0])
        return SearchResults(albums=parsed_tables[0], songs=[])

    # Two tables: first albums, second songs.
    albums = parsed_tables[0]
    songs = parsed_tables[1] if len(parsed_tables) > 1 else []
    return SearchResults(albums=albums, songs=songs)


def print_search_results(results: SearchResults, file=sys.stdout) -> None:
    """Pretty-print search results, similar to the legacy script.

    Args:
        results: Search outcome to print.
        file: Target stream (stdout or stderr).
    """
    all_items = results.albums + results.songs
    if not all_items:
        print("No soundtracks found.", file=file)
        return

    pad = max((len(ost.id) for ost in all_items), default=0)

    def _print_group(title: str, items: List[Soundtrack]) -> None:
        if not items:
            return
        print(title, file=file)
        for ost in items:
            dots = "." * (pad - len(ost.id) + 1)
            # ost.name is often pre-populated; if not, it will fetch lazily.
            print(f"{ost.id} {dots} {ost.name}", file=file)
        print("", file=file)

    _print_group("Album title results:", results.albums)
    _print_group("Song name results:", results.songs)


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
    "-i",
    "--images",
    action=argparse.BooleanOptionalAction,
    default=True,
    help="Download album images (default: enabled; use --no-images to disable).",
    )
    parser.add_argument(
    "-v",
    "--verbose",
    action=argparse.BooleanOptionalAction,
    default=True,
    help="Show detailed progress (default: enabled; use --no-verbose to disable).",
    )
    parser.add_argument(
        "-s", "--search",
        action="store_true",
        help=(
            "Search for soundtracks instead of downloading. "
            "Also used automatically if the supplied soundtrack ID "
            "does not exist."
        ),
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
                "Referer": BASE_URL,
            })

            # Normalize possible full album URL to an ID.
            user_input = args.soundtrack
            soundtrack_id = extract_soundtrack_id(user_input)

            # If explicitly asked to search, do that and exit.
            if args.search:
                try:
                    results = search_soundtracks(user_input, session)
                except (SearchError, NetworkError) as e:
                    print(f"Search failed: {e}", file=sys.stderr)
                    sys.exit(1)
                print(
                    "Soundtracks found (to download, run "
                    '"python khinsider.py <soundtrack_id>"):\n'
                )
                print_search_results(results)
                sys.exit(0)

            # Otherwise, attempt normal download; on missing album, fall back to
            # an automatic search using a friendlier term.
            try:
                ost = Soundtrack(soundtrack_id, session)
                out_dir = args.output or Path(sanitize_filename(ost.name))

                ok = ost.download(
                    output_dir=out_dir,
                    formats=args.format.split(",") if args.format else None,
                    download_images=args.images,
                    verbose=args.verbose,
                )
                if ok:
                    print("\nDownload completed successfully!")
                    sys.exit(0)
                print("\nDownload completed with some errors.", file=sys.stderr)
                sys.exit(1)

            except InvalidSoundtrackError:
                # Friendly automatic search, similar to legacy behavior.
                search_term = user_input.replace("-", " ")
                try:
                    results = search_soundtracks(search_term, session)
                except (SearchError, NetworkError):
                    print(
                        f'The soundtrack "{soundtrack_id}" does not seem to exist, '
                        "and a search could not be performed.",
                        file=sys.stderr,
                    )
                    sys.exit(1)

                print(
                    f'The soundtrack "{soundtrack_id}" does not seem to exist.\n',
                    file=sys.stderr,
                )
                print(
                    'These exist, though (run "python khinsider.py <soundtrack_id>"):',
                    file=sys.stderr,
                )
                print_search_results(results, file=sys.stderr)
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
