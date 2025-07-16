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

Use `khinsider.py` as a module in your own Python code:

```python
from pathlib import Path
import khinsider

# Download audio only, default formats
khinsider.download(
    soundtrack_id="jumping-flash",
    output_dir=Path("Jumping Flash OST"),
    formats=None,
    download_images=False,
    verbose=True,
)

# Download MP3s and images
khinsider.download(
    soundtrack_id="mother-3",
    output_dir=Path("Mother 3 Soundtrack"),
    formats=["mp3"],
    download_images=True,
    verbose=False,
)
```

#### API

```python
def download(
    soundtrack_id: str,
    output_dir: Path,
    formats: Optional[List[str]] = None,
    download_images: bool = False,
    verbose: bool = False
) -> bool:
    """Download a KHInsider soundtrack and optional images.

    Args:
        soundtrack_id: ID or URL segment of the album.
        output_dir: Directory to save files into.
        formats: Preferred audio formats in descending priority.
        download_images: If True, also download album images.
        verbose: If True, print progress to stdout.

    Returns:
        True if all requested files succeeded, False otherwise.
    """
```

---

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for:

* Bug reports and feature requests
* Coding style and testing conventions
* Pull request process

---

## License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.

---

## Support

* Report issues and request features on [GitHub Issues](https://github.com/obskyr/khinsider/issues).
* Reach out on Twitter [@obskyr](https://twitter.com/obskyr) or by email at [contact@obskyr.io](mailto:contact@obskyr.io).
