# KHInsider Downloader

A command-line and library interface for mass-downloading full game soundtracks (and optional album images) from [KHInsider](https://downloads.khinsider.com/). Built for Python 3.

> **New to Python?** If you’ve never used Python before, [click here](#never-used-python-before) to get started.

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
- [requests](https://pypi.org/project/requests) 2.31.0 or later
- [beautifulsoup4](https://pypi.org/project/beautifulsoup4) 4.12.0 or later

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

Download **Minecraft OST** in FLAC or MP3, plus album images, with verbose output:

```bash
khinsider.py minecraft -f flac,mp3 -i -v
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
  
## Never used Python before?

If you’ve never used Python or the command line before, these steps will walk you through running the KHInsider Downloader on **Windows**, **macOS**, or **Linux**.

### 1. Install Python

- **Windows**  
  1. Go to https://www.python.org/downloads/windows/  
  2. Download the latest **“Windows installer (64-bit)”**.  
  3. Run the installer, **check “Add Python to PATH”**, then click **Install Now**.

- **macOS**  
  1. Open **Terminal** (Finder → Applications → Utilities → Terminal).  
  2. Check if Python is already installed:
     ```bash
     python3 --version
     ```
  3. If it’s not installed or you need a newer version, install via [Homebrew](https://brew.sh/):
     ```bash
     /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
     brew install python
     ```

- **Linux**  
  1. Open your terminal.  
  2. Update your package list and install Python 3 and pip:
     ```bash
     # Debian/Ubuntu
     sudo apt update && sudo apt install python3 python3-pip
     
     # Fedora
     sudo dnf install python3 python3-pip
     
     # Arch
     sudo pacman -S python python-pip
     ```

### 2. Open the Command Line / Terminal

- **Windows**: Press Win+R, type `cmd`, and press Enter.  
- **macOS**: Finder → Applications → Utilities → **Terminal**.  
- **Linux**: Your desktop’s **Terminal** app (often Ctrl+Alt+T).

### 3. Download the KHInsider Script

1. In your terminal, choose (or create) a folder where you want the tool to live. For example:
   ```bash
   cd ~/Downloads
   mkdir khinsider-tool && cd khinsider-tool
    ````

2. Clone the repository:

   ```bash
   git clone https://github.com/obskyr/khinsider.git
   cd khinsider
   ```

> **No Git?**
>
> * **Windows/macOS**: Install from [https://git-scm.com/downloads](https://git-scm.com/downloads)
> * **Linux**: `sudo apt install git` (or your distro’s equivalent)

### 4. Install Dependencies

Once inside the `khinsider` folder, run:

```bash
pip install --user -r requirements.txt
```

* The `--user` flag installs packages just for your user account (no need for administrator rights).

### 5. Make the Script Executable (macOS/Linux)

On **macOS** or **Linux**, you may need to give the script permission to run:

```bash
chmod +x khinsider.py
```

> **Windows users:** You can skip `chmod`; Windows will use the file association.

### 6. Run the Downloader

In the same terminal window, use:

```bash
# Basic usage: replace <album-id-or-url> with the soundtrack you want
python3 khinsider.py <album-id-or-url>
```

Or, if you added the tool to your PATH (see Installation instructions above):

```bash
khinsider.py <album-id-or-url>
```

#### Examples

* **Download in FLAC only**:

  ```bash
  python3 khinsider.py aquaplus-vocal-collection-vol.4 -f flac
  ```
* **Download FLAC or MP3 + album images + verbose output**:

  ```bash
  python3 khinsider.py minecraft -f flac,mp3 -i -v
  ```

---

That’s it! If you hit any errors, double-check that:

1. **Python 3.7+** is installed and on your PATH.
2. You ran `pip install -r requirements.txt`.
3. You’re in the right folder (`cd khinsider`).

## Support

* Report issues and request features on [GitHub Issues](https://github.com/obskyr/khinsider/issues).
* Reach out on Twitter [@obskyr](https://twitter.com/obskyr) or by email at [contact@obskyr.io](mailto:contact@obskyr.io).
