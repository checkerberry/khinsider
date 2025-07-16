#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A script to download full soundtracks from KHInsider.

This script allows users to download entire music albums from KHInsider by 
specifying the album ID found in the website's URL. It supports multiple audio
formats and includes error handling for network issues and invalid inputs.

Features:
- Automatic directory creation with sanitized names
- Format selection prioritization
- Connection reuse for improved performance
- Comprehensive error reporting

Parameters:
  soundtrack_id    Soundtrack ID from KHInsider URL (e.g. "minecraft", always the last string in the url: https://downloads.khinsider.com/game-soundtracks/album/minecraft <--)
  -o, --output  Output directory (default: soundtrack name)
  -f, --format  Preferred formats, comma-separated (e.g. "flac,mp3")
  -v, --verbose Show detailed progress information

Usage:
    python khinsider_downloader.py <soundtrack_id> [-o OUTPUT_DIR] [-f FORMATS] [-v]

Examples:
    Download aquaplus vocal collections volume 4 in flac:
    >>> python khinsider_checkerberry.py --format flac "aquaplus-vocal-collection-vol.4"
    
    Download KH3 original soundtrack in MP3:
    >>> python khinsider_checkerberry.py kh3-ost -f flac,mp3 -v

.. codeauthor:: obskyr <contact@obskyr.io>
.. modernized:: Checkerberry
"""

import argparse
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional, Generator
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup

# Precompiled regex patterns for HTML preprocessing
PRE_TD_RE = re.compile(br"^</td>\s*$", flags=re.MULTILINE)
INVALID_ENTITY_RE = re.compile(br"&#([^0-9x]|x[^0-9A-Fa-f])")
FILENAME_INVALID_RE = re.compile(r'[<>:"/\\|?*]')

BASE_URL = 'https://downloads.khinsider.com/'
SCRIPT_NAME = Path(sys.argv[0]).name
REPORT_URL = "https://github.com/obskyr/khinsider/issues"
MAX_RETRIES = 3
CHUNK_SIZE = 65536  # 64KB chunks for download streaming


class ScriptError(Exception):
    """Base exception for script-specific errors."""


class NetworkError(ScriptError):
    """Raised when network operations fail after multiple attempts."""


class InvalidSoundtrackError(ScriptError):
    """Raised when requested soundtrack doesn't exist or is unavailable."""


class InvalidFormatError(ScriptError):
    """Raised when none of the requested audio formats are available."""


@contextmanager
def suppress_output() -> Generator[None, None, None]:
    """Context manager to suppress all stdout/stderr output.
    
    Yields:
        None: No value yielded, used for context management
    """
    with open(os.devnull, 'w') as null:
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        sys.stdout = null
        sys.stderr = null
        try:
            yield
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr


def sanitize_filename(name: str) -> str:
    """Convert string to a valid filesystem filename.
    
    Args:
        name: Original filename to sanitize
    
    Returns:
        Sanitized filename with invalid characters replaced
    
    Example:
        >>> sanitize_filename('A/B?C*.txt')
        'A-B-C-.txt'
    """
    sanitized = FILENAME_INVALID_RE.sub('-', name).rstrip(' .')
    reserved = {'', '.', '..', '~', 'CON', 'PRN', 'AUX', 'NUL'} | \
        {f'COM{i}' for i in range(1, 10)} | \
        {f'LPT{i}' for i in range(1, 10)}
    
    if sanitized.upper() in reserved:
        return f'{sanitized}_'
    return sanitized


def get_soup(url: str, session: requests.Session) -> BeautifulSoup:
    """Fetch and parse HTML content from URL using persistent session.
    
    Args:
        url: URL to fetch content from
        session: Requests session for connection reuse
    
    Returns:
        BeautifulSoup object containing parsed HTML
        
    Raises:
        NetworkError: If connection fails multiple times
    """
    try:
        with suppress_output():
            response = session.get(url, timeout=15)
            response.raise_for_status()
            
            # Preprocess HTML to fix common issues
            content = response.content
            content = PRE_TD_RE.sub(b'', content)
            content = INVALID_ENTITY_RE.sub(b'&amp;#\\1', content)
            
            return BeautifulSoup(content, 'html.parser')
    except requests.RequestException as e:
        raise NetworkError(f"Network error: {e}") from e


class Soundtrack:
    """Represents a KHInsider soundtrack album with download capabilities.
    
    Attributes:
        id (str): Soundtrack ID extracted from URL
        url (str): Full URL to the album page
        name (str): Sanitized official album name
        formats (List[str]): Available audio formats (e.g., ['mp3', 'flac'])
        songs (List[Song]): List of tracks in the album
    
    Example:
        >>> with requests.Session() as session:
        ...     ost = Soundtrack('kh2fm-soundtrack', session)
        ...     print(ost.name)
        Kingdom Hearts II FM Original Soundtrack
    """
    
    def __init__(self, soundtrack_id: str, session: requests.Session):
        """Initialize soundtrack with ID and persistent session.
        
        Args:
            soundtrack_id: Album ID from KHInsider URL
            session: Shared requests session for HTTP connections
        """
        self.id = soundtrack_id
        self.session = session
        self.url = urljoin(BASE_URL, f'game-soundtracks/album/{self.id}')
        self._soup = None
        self._name = None
        self._formats = None
        self._songs = None

    @property
    def name(self) -> str:
        """Get official soundtrack name with sanitization.
        
        Returns:
            Safe-to-use filename string
            
        Raises:
            InvalidSoundtrackError: If album page indicates missing content
        """
        if not self._name:
            soup = self._get_content()
            name_tag = soup.find('h2')
            if not name_tag:
                raise InvalidSoundtrackError(f"Invalid album page: {self.url}")
            self._name = sanitize_filename(name_tag.get_text(strip=True))
        return self._name

    @property
    def formats(self) -> List[str]:
        """Get available audio formats from album table headers.
        
        Returns:
            List of lowercase format identifiers
        """
        if not self._formats:
            soup = self._get_content()
            table = soup.find('table', id='songlist')
            if not table:
                return ['mp3']  # Default to MP3 if no table found
            
            headers = [th.get_text(strip=True).lower() 
                       for th in table.find_all('th')]
            self._formats = [
                h for h in headers 
                if h not in {'track', 'song name', 'download', 'size'}
            ] or ['mp3']
        return self._formats

    @property
    def songs(self) -> List['Song']:
        """Get list of Song objects from track links.
        
        Returns:
            List of Song instances representing album tracks
        """
        if not self._songs:
            soup = self._get_content()
            table = soup.find('table', id='songlist')
            links = [tr.find('a')['href'] 
                     for tr in table.find_all('tr') if tr.find('a')]
            self._songs = [
                Song(urljoin(self.url, link), self.session) 
                for link in links
            ]
        return self._songs

    def _get_content(self) -> BeautifulSoup:
        """Lazy-load and validate album page content.
        
        Returns:
            Parsed BeautifulSoup object of album page
            
        Raises:
            InvalidSoundtrackError: If page contains error messages
        """
        if not self._soup:
            self._soup = get_soup(self.url, self.session)
            error_text = self._soup.find("No such album")
            if error_text:
                raise InvalidSoundtrackError(f"Album {self.id} not found")
        return self._soup

    def download(
        self,
        output_dir: Path,
        formats: Optional[List[str]] = None,
        verbose: bool = False
    ) -> bool:
        """Download complete soundtrack with format prioritization.
        
        Args:
            output_dir: Target directory for downloaded files
            formats: Preferred formats in descending priority order
            verbose: Enable detailed progress output
            
        Returns:
            True if all tracks downloaded successfully
            
        Raises:
            InvalidFormatError: If no requested formats are available
            OSError: If directory creation fails
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        if formats and not set(formats).intersection(self.formats):
            raise InvalidFormatError(
                f"Available formats: {', '.join(self.formats)}"
            )

        success = True
        total = len(self.songs)
        pad = len(str(total))

        for idx, song in enumerate(self.songs, 1):
            try:
                file = self._select_best_file(song, formats or [])
                if not self._download_file(
                    file, 
                    output_dir,
                    idx,
                    total,
                    pad,
                    verbose
                ):
                    success = False
            except Exception as e:
                if verbose:
                    print(f"Error downloading song {idx}: {e}", file=sys.stderr)
                success = False

        return success

    def _select_best_file(self, song: 'Song', formats: List[str]) -> 'AudioFile':
        """Select highest priority available format for a track.
        
        Args:
            song: Track to select format from
            formats: Ordered list of preferred formats
            
        Returns:
            Best matching AudioFile instance
        """
        if not formats:
            return song.files[0]
            
        for fmt in formats:
            fmt_lower = fmt.lower()
            for file in song.files:
                if file.extension == fmt_lower:
                    return file
        return song.files[0]

    def _download_file(
        self,
        file: 'AudioFile',
        output_dir: Path,
        current: int,
        total: int,
        pad: int,
        verbose: bool
    ) -> bool:
        """Download individual track with retry logic.
        
        Args:
            file: AudioFile to download
            output_dir: Target directory
            current: Current track number
            total: Total tracks to download
            pad: String padding for progress display
            verbose: Enable status output
            
        Returns:
            True if download succeeded
        """
        dest = output_dir / sanitize_filename(file.filename)
        if dest.exists():
            if verbose:
                print(f"Skipping existing: {dest.name}")
            return True

        if verbose:
            progress = f"[{current:0{pad}d}/{total}]"
            print(f"{progress} Downloading {dest.name}...")

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                file.download(dest)
                return True
            except requests.RequestException as e:
                if verbose and attempt < MAX_RETRIES:
                    print(f"Retry {attempt}/{MAX_RETRIES} for {dest.name}")
        return False


class Song:
    """Represents a single track with multiple audio format options.
    
    Attributes:
        url (str): URL of track's detail page
        name (str): Sanitized track name
        files (List[AudioFile]): Available audio format options
    """
    
    def __init__(self, url: str, session: requests.Session):
        """Initialize track with URL and shared session.
        
        Args:
            url: Full URL to track's page
            session: Reusable requests session
        """
        self.url = url
        self.session = session
        self._soup = None
        self._name = None
        self._files = None

    @property
    def name(self) -> str:
        """Extract and sanitize track name from page content."""
        if not self._name:
            soup = self._get_soup()
            name_tag = soup.find_all('p')[2].find('b')
            self._name = sanitize_filename(name_tag.get_text(strip=True))
        return self._name

    @property
    def files(self) -> List['AudioFile']:
        """Extract available audio file links from page."""
        if not self._files:
            soup = self._get_soup()
            pattern = re.compile(r'/(?:soundtracks|ost)/')
            links = [a['href'] for a in soup.find_all('a', href=pattern)]
            self._files = [
                AudioFile(urljoin(self.url, link), self.session) 
                for link in links
            ]
        return self._files

    def _get_soup(self) -> BeautifulSoup:
        """Fetch and validate track page content."""
        if not self._soup:
            self._soup = get_soup(self.url, self.session)
            if '404' in self._soup.find('title').text:
                raise InvalidSoundtrackError(f"Invalid track URL: {self.url}")
        return self._soup


class AudioFile:
    """Represents a downloadable audio file with metadata.
    
    Attributes:
        url (str): Direct download URL
        filename (str): Original filename from URL
        extension (str): Lowercase file extension
    """
    
    def __init__(self, url: str, session: requests.Session):
        """Initialize with download URL and session.
        
        Args:
            url: Direct download URL
            session: Shared requests session
        """
        self.url = url
        self.session = session
        self.filename = unquote(Path(url).name)
        self.extension = Path(url).suffix[1:].lower()

    def download(self, dest: Path) -> None:
        """Stream file to disk with large chunk size.
        
        Args:
            dest: Path to save file
            
        Raises:
            requests.RequestException: For network errors
        """
        response = self.session.get(self.url, stream=True, timeout=30)
        response.raise_for_status()
        
        with dest.open('wb') as f:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:  # Filter out keep-alive chunks
                    f.write(chunk)


def main():
    """
    Command-line interface for KHInsider soundtrack downloads.

    This script now spoofs a Chrome browser User-Agent and sets a Referer header
    to avoid 403 Forbidden errors when fetching pages from KHInsider.

    Usage:
        python khinsider_checkerberry.py <soundtrack_id> [-o OUTPUT_DIR] [-f FORMATS] [-v]

    Positional arguments:
      soundtrack           Album ID from KHInsider URL
                           (e.g. 'kh2fm-soundtrack' from
                           https://downloads.khinsider.com/game-soundtracks/album/kh2fm-soundtrack)

    Optional arguments:
      -o, --output         Output directory (default: album name)
      -f, --format         Preferred formats, comma-separated (e.g. 'flac,mp3')
      -v, --verbose        Show detailed progress output
    """
    parser = argparse.ArgumentParser(
        description="Download KHInsider soundtracks (spoofing Chrome UA)",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=f"Report issues: {REPORT_URL}"
    )
    parser.add_argument(
        'soundtrack',
        help=(
            "Album ID from KHInsider URL\n"
            "(e.g. 'kh2fm-soundtrack' from\n"
            "https://downloads.khinsider.com/game-soundtracks/album/kh2fm-soundtrack)"
        )
    )
    parser.add_argument(
        '-o', '--output',
        type=Path,
        help="Output directory (default: album name)"
    )
    parser.add_argument(
        '-f', '--format',
        help="Preferred formats, comma-separated (e.g. 'flac,mp3')"
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help="Show detailed progress output"
    )

    args = parser.parse_args()

    try:
        with requests.Session() as session:
            session.headers.update({ # Spoof Chrome and set Referer
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/114.0.0.0 Safari/537.36'
                ),
                'Referer': 'https://downloads.khinsider.com/'
            })

            ost = Soundtrack(args.soundtrack, session)
            output_dir = args.output or Path(sanitize_filename(ost.name))

            if ost.download(
                output_dir=output_dir,
                formats=args.format.split(',') if args.format else None,
                verbose=args.verbose
            ):
                print("\nDownload completed successfully!")
                sys.exit(0)

            print("\nDownload completed with errors!", file=sys.stderr)
            sys.exit(1)

    except KeyboardInterrupt:
        print("\nDownload cancelled.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)

    """Command-line interface for soundtrack downloads."""
    parser = argparse.ArgumentParser(
        description="Download KHInsider soundtracks",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=f"Report issues: {REPORT_URL}"
    )
    parser.add_argument(
        'soundtrack',
        help="Album ID from KHInsider URL\n(e.g. 'kh2fm-soundtrack' from\nhttps://downloads.khinsider.com/game-soundtracks/album/kh2fm-soundtrack)"
    )
    parser.add_argument(
        '-o', '--output',
        type=Path,
        help="Output directory (default: album name)"
    )
    parser.add_argument(
        '-f', '--format',
        help="Preferred formats, comma-separated\n(e.g. 'flac,mp3')"
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help="Show detailed progress output"
    )
    
    args = parser.parse_args()
    
    try:
        with requests.Session() as session:
            ost = Soundtrack(args.soundtrack, session)
            output_dir = args.output or Path(sanitize_filename(ost.name))
            
            if ost.download(
                output_dir=output_dir,
                formats=args.format.split(',') if args.format else None,
                verbose=args.verbose
            ):
                print("\nDownload completed successfully!")
                sys.exit(0)
            print("\nDownload completed with errors!", file=sys.stderr)
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\nDownload cancelled.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()