# KHInsider Downloader

A command-line and library interface for mass-downloading full game soundtracks (and optional album images) from [KHInsider](https://downloads.khinsider.com/). Built for Python 3 with best practices, Google-style documentation, and robust error handling.

---

## Features

- Download entire soundtrack albums by ID or URL
- Support for multiple audio formats (FLAC, MP3, etc.) with user-defined priority
- **New**: Optional download of album images (cover art, booklet scans)
- Automatic creation of sanitized output directories
- HTTP connection reuse for performance
- Retries on transient network failures
- Comprehensive error reporting and exit codes

---

## Requirements

- Python 3.7+
- [requests](https://pypi.org/project/requests) 2.31.0 or later (< 3.0.0)
- [beautifulsoup4](https://pypi.org/project/beautifulsoup4) 4.12.0 or later (< 5.0.0)

Install dependencies with:

```bash
pip install -r requirements.txt
````

---

## Installation

Clone the repository or download the latest release ZIP:

```bash
git clone https://github.com/obskyr/khinsider.git
cd khinsider
```

Ensure the script is executable:

```bash
chmod +x khinsider.py
```

Optionally, install into your `$PATH`:

```bash
pip install .
```

---

## Usage

### Command-Line Interface

```bash
khinsider.py <album-id-or-url> [OPTIONS]
```

**Positional arguments**

* `<album-id-or-url>`
  The soundtrack identifier (e.g. `kh2fm-soundtrack`) or full URL.

**Options**

* `-o, --output DIR`
  Output directory (default: sanitized album name).
* `-f, --format FORMATS`
  Comma-separated list of preferred audio formats, in priority order (e.g. `flac,mp3`).
* `-i, --images`
  Download album images (cover, booklet, etc.) in addition to audio.
* `-v, --verbose`
  Show detailed progress and retry messages.
* `-h, --help`
  Show usage information and exit.

**Exit codes**

* `0` All files downloaded successfully
* `1` Completed with errors or unexpected exception
* `2` Invalid arguments or help request

#### Examples

Download the **Aquaplus Vocal Collection Vol. 4** in FLAC:

```bash
khinsider.py aquaplus-vocal-collection-vol.4 -f flac
```

Download **KH3 OST** in FLAC or MP3, plus album images, with verbose output:

```bash
khinsider.py kh3-ost -f flac,mp3 -i -v
```

---

### Library Interface

Use the core classes directly in your own code:

```python
from pathlib import Path
import requests
from khinsider import Soundtrack

# Create an HTTP session
session = requests.Session()

# Instantiate a Soundtrack by its ID (or URL segment)
ost = Soundtrack("jumping-flash", session)

# Download audio only (default formats)
ost.download(
    output_dir=Path("Jumping Flash OST"),
    formats=None,
    download_images=False,
    verbose=True,
)

# Download only MP3s plus album images
ost.download(
    output_dir=Path("Mother 3 OST"),
    formats=["mp3"],
    download_images=True,
    verbose=False,
)
````

If you prefer a single‐function entry point, add this to your module:

```python
import requests
from khinsider import Soundtrack
from pathlib import Path
from typing import List, Optional

def download(
    soundtrack_id: str,
    output_dir: Path,
    formats: Optional[List[str]] = None,
    download_images: bool = False,
    verbose: bool = False
) -> bool:
    """Convenience wrapper around Soundtrack.download()."""
    session = requests.Session()
    ost = Soundtrack(soundtrack_id, session)
    return ost.download(output_dir, formats, download_images, verbose)
```

Then call:

```python
import khinsider
from pathlib import Path

khinsider.download(
    "jumping-flash",
    Path("Jumping Flash OST"),
    formats=None,
    download_images=False,
    verbose=True,
)
```

---

### API

#### `Soundtrack.download`

```python
def download(
    self,
    output_dir: Path,
    formats: Optional[List[str]] = None,
    download_images: bool = False,
    verbose: bool = False
) -> bool:
    """Download all tracks and optional album images.

    Args:
        output_dir: Destination directory for files.
        formats: List of preferred audio extensions (e.g., ['flac', 'mp3']); defaults to all.
        download_images: If True, also download cover art and other images.
        verbose: If True, print per-file progress and retry messages.

    Returns:
        True if all requested files succeeded, False otherwise.

    Raises:
        InvalidFormatError: If none of the requested audio formats are available.
        OSError: If the output directory cannot be created.
    """
```

#### `Song` and `AudioFile`

* Use `Song` when you need per-track metadata:

  ```python
  for song in ost.songs:
      print(song.name, [f.extension for f in song.files])
  ```
* Use `AudioFile` to inspect or download individual URLs:

  ```python
  file = ost.songs[0].files[0]
  file.download(Path("myfile.mp3"))
  ```

## Support

* Report issues and request features on [GitHub Issues](https://github.com/obskyr/khinsider/issues).
* Reach out on Twitter [@obskyr](https://twitter.com/obskyr) or by email at [contact@obskyr.io](mailto:contact@obskyr.io).
