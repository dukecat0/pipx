"""Progress tracking and display for package installation."""

import re
import sys
from typing import Optional, Set

from pipx.animate import clear_line


class InstallProgress:
    """Track and display installation progress for pip packages."""

    def __init__(self, package_name: str):
        self.package_name = package_name
        self.current_package: Optional[str] = None
        self.current_action: Optional[str] = None
        self.seen_packages: Set[str] = set()
        self.collecting_shown = False
        self.downloading_shown = False
        self.installing_shown = False
        # Check if stderr is a TTY (terminal) for proper progress display
        self.stderr_is_tty = bool(sys.stderr and hasattr(sys.stderr, 'isatty') and sys.stderr.isatty())
        self.last_message = ""

    def _display_progress(self, message: str) -> None:
        """Display a progress message on a single updating line."""
        # Always update last_message to track state
        if message == self.last_message:
            return  # Don't redisplay the same message
        
        self.last_message = message
        
        if self.stderr_is_tty:
            clear_line()
            sys.stderr.write(f"  {message}\r")
            sys.stderr.flush()
        else:
            # Non-TTY: print each new message on its own line
            sys.stderr.write(f"  {message}\n")
            sys.stderr.flush()

    def parse_line(self, line: str) -> None:
        """Parse a line of pip output and update progress display."""
        line = line.strip()
        if not line:
            return

        # Optimization: Check first character for quick filtering
        first_char = line[0] if line else ''
        
        # Match progress bar format: "5.0/17.3 MB" or percentage "50%"
        # First try explicit percentage (only if line might contain progress)
        if first_char in ' \u2501━':  # Space or progress bar characters
            percentage_match = re.search(r'(\d+)%', line)
        else:
            percentage_match = None
            
        if percentage_match:
            percentage = percentage_match.group(1)
            # Show percentage for any current package being processed
            if self.current_package and self.stderr_is_tty:
                if self.current_action == "Downloading":
                    self._display_progress(f"Downloading {self.current_package}... {percentage}%")
                    return
                elif self.current_action == "Collecting":
                    self._display_progress(f"Resolving {self.current_package}... {percentage}%")
                    return
        
        # Try to match progress bar format with downloaded/total sizes (only if downloading)
        # Format: "15.2/69.2 MB 350.1 kB/s eta 0:02:35"
        if self.current_action == "Downloading" and self.current_package:
            progress_bar_match = re.search(r'(\d+\.?\d*)/(\d+\.?\d*)\s+(MB|KB|GB)', line)
        else:
            progress_bar_match = None
            
        if progress_bar_match:
            downloaded = float(progress_bar_match.group(1))
            total = float(progress_bar_match.group(2))
            unit = progress_bar_match.group(3)
            if total > 0:
                percentage = int((downloaded / total) * 100)
                
                # Try to extract ETA if available
                eta_match = re.search(r'eta\s+([\d:]+)', line)
                if eta_match and self.stderr_is_tty:
                    eta = eta_match.group(1)
                    self._display_progress(f"Downloading {self.current_package}... {percentage}% ({downloaded:.1f}/{total:.1f} {unit}) ETA: {eta}")
                elif self.stderr_is_tty:
                    self._display_progress(f"Downloading {self.current_package}... {percentage}% ({downloaded:.1f}/{total:.1f} {unit})")
                return

        # Match "Collecting package-name" (only check if line starts with 'C')
        if first_char == 'C' and line.startswith('Collecting'):
            collecting_match = re.match(r"Collecting\s+([^\s(]+)", line)
        else:
            collecting_match = None
            
        if collecting_match:
            package = collecting_match.group(1)
            
            # Only track packages we haven't seen yet
            if package not in self.seen_packages:
                self.seen_packages.add(package)
                self.current_package = package
                self.current_action = "Collecting"
                self.collecting_shown = True
                
                # Show a simple message about what we're collecting
                count = len(self.seen_packages)
                self._display_progress(f"📦 Resolving dependencies... ({count} found)")
            return

        # Match "Downloading package-name-version.whl (size)" (only check if line starts with 'D')
        if first_char == 'D' and line.startswith('Downloading'):
            downloading_match = re.match(r"Downloading\s+([^\s]+)", line)
        else:
            downloading_match = None
            
        if downloading_match:
            if not self.downloading_shown:
                self.downloading_shown = True
                # Clear the resolving dependencies message
                if self.stderr_is_tty and self.collecting_shown:
                    clear_line()
            
            filename = downloading_match.group(1)
            # Extract package name from filename if possible
            package_match = re.match(r"([^-]+)", filename)
            if package_match:
                package = package_match.group(1)
                self.current_package = package
                self.current_action = "Downloading"
                # Show initial download message
                # Extract size if available (not always present, e.g., when using cached files)
                size_match = re.search(r'\(([^)]+)\)', line)
                if size_match:
                    size = size_match.group(1)
                    self._display_progress(f"⬇️  Downloading {package} ({size})...")
                else:
                    self._display_progress(f"⬇️  Downloading {package}...")
            return

        # Match "Installing collected packages: ..." (only check if line starts with 'I')
        if first_char == 'I' and line.startswith('Installing'):
            installing_match = re.match(r"Installing collected packages:\s+(.+)", line)
        else:
            installing_match = None
            
        if installing_match:
            packages_list = installing_match.group(1)
            self.current_action = "Installing"
            if not self.installing_shown:
                self.installing_shown = True
                # Clear any previous message (resolving or downloading)
                if self.stderr_is_tty:
                    clear_line()
                # Show which packages are being installed
                self._display_progress(f"📦 Installing: {packages_list}")
            return

        # Match "Successfully installed ..." (only check if line starts with 'S')
        if first_char == 'S' and line.startswith('Successfully'):
            success_match = re.match(r"Successfully installed\s+(.+)", line)
        else:
            success_match = None
            
        if success_match:
            packages = success_match.group(1)
            self.current_action = "Completed"
            
            # Clear the progress line
            if self.stderr_is_tty:
                clear_line()
            
            # Don't display the package list - it will be shown in the final summary
            return

        # Match "Building wheel for ..." (only check if line starts with 'B')
        if first_char == 'B' and line.startswith('Building'):
            building_match = re.match(r"Building wheel for\s+([^\s(]+)", line)
        else:
            building_match = None
            
        if building_match:
            package = building_match.group(1)
            self.current_package = package
            self.current_action = "Building"
            # Don't display, just track
            return

        # Match "Using cached ..." (only check if line starts with 'U')
        if first_char == 'U' and line.startswith('Using'):
            cached_match = re.match(r"Using cached\s+([^\s]+)", line)
        else:
            cached_match = None
            
        if cached_match:
            if not self.downloading_shown:
                self.downloading_shown = True
                # Clear the resolving dependencies message
                if self.stderr_is_tty and self.collecting_shown:
                    clear_line()
            
            filename = cached_match.group(1)
            package_match = re.match(r"([^-]+)", filename)
            if package_match:
                package = package_match.group(1)
                self.current_package = package
                self.current_action = "Using cached"
                # Show that we're using cached version
                self._display_progress(f"💾 Using cached {package}...")
            return

    def finish(self) -> None:
        """Finish the progress display and clear any remaining messages."""
        if self.stderr_is_tty and self.last_message:
            clear_line()
            sys.stderr.flush()
