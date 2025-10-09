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
        self.stderr_is_tty = bool(sys.stderr and sys.stderr.isatty())
        self.last_message = ""

    def _display_progress(self, message: str) -> None:
        """Display a progress message on a single updating line."""
        if self.stderr_is_tty:
            clear_line()
            sys.stderr.write(f"  {message}")
            sys.stderr.flush()
            self.last_message = message
        else:
            # Non-TTY: only print if message changed to avoid spam
            if message != self.last_message:
                sys.stderr.write(f"  {message}\n")
                sys.stderr.flush()
                self.last_message = message

    def parse_line(self, line: str) -> None:
        """Parse a line of pip output and update progress display."""
        line = line.strip()
        if not line:
            return

        # Match progress bar format: "5.0/17.3 MB" or percentage "50%"
        # First try explicit percentage
        percentage_match = re.search(r'(\d+)%', line)
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
        
        # Try to match progress bar format with downloaded/total sizes
        progress_bar_match = re.search(r'(\d+\.?\d*)/(\d+\.?\d*)\s+(MB|KB|GB)', line)
        if progress_bar_match and self.current_package and self.current_action == "Downloading":
            downloaded = float(progress_bar_match.group(1))
            total = float(progress_bar_match.group(2))
            unit = progress_bar_match.group(3)
            if total > 0:
                percentage = int((downloaded / total) * 100)
                if self.stderr_is_tty:
                    self._display_progress(f"Downloading {self.current_package}... {percentage}% ({downloaded:.1f}/{total:.1f} {unit})")
                return

        # Match "Collecting package-name"
        collecting_match = re.match(r"Collecting\s+([^\s(]+)", line)
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

        # Match "Downloading package-name-version.whl (size)"
        downloading_match = re.match(r"Downloading\s+([^\s]+)", line)
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

        # Match "Installing collected packages: ..."
        installing_match = re.match(r"Installing collected packages:\s+(.+)", line)
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

        # Match "Successfully installed ..."
        success_match = re.match(r"Successfully installed\s+(.+)", line)
        if success_match:
            packages = success_match.group(1)
            self.current_action = "Completed"
            
            # Clear the progress line
            if self.stderr_is_tty:
                clear_line()
            
            # Don't display the package list - it will be shown in the final summary
            return

        # Match "Building wheel for ..."
        building_match = re.match(r"Building wheel for\s+([^\s(]+)", line)
        if building_match:
            package = building_match.group(1)
            self.current_package = package
            self.current_action = "Building"
            # Don't display, just track
            return

        # Match "Using cached ..."
        cached_match = re.match(r"Using cached\s+([^\s]+)", line)
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
        if self.stderr_is_tty:
            clear_line()
