"""Progress tracking and display for package installation."""

import re
import sys
import threading
import time
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
        self._keep_alive_interval_seconds = 8.0
        self._keep_alive_started_at: Optional[float] = None
        self._last_output_at: Optional[float] = None
        self._keep_alive_stop_event = threading.Event()
        self._keep_alive_thread: Optional[threading.Thread] = None

    @staticmethod
    def _normalize_requirement_name(requirement: str) -> str:
        """Extract a likely package name from a pip requirement fragment."""
        requirement = requirement.strip()
        requirement = requirement.split("[", 1)[0]
        requirement = re.split(r"[<>=!~]", requirement, maxsplit=1)[0]
        return requirement.strip()

    @staticmethod
    def _package_from_artifact_name(artifact: str) -> Optional[str]:
        """Best-effort package name extraction from wheel/sdist artifact names."""
        artifact = artifact.strip().rsplit("/", 1)[-1]
        artifact = artifact.split("?", 1)[0].split("#", 1)[0]
        match = re.match(r"^(.+?)-\d", artifact)
        if match:
            return match.group(1).replace("_", "-")
        return None

    @staticmethod
    def _format_installing_packages(packages_list: str, max_packages: int = 5) -> str:
        """Format pip's "Installing collected packages" list for compact display."""
        packages = [p.strip() for p in packages_list.split(",") if p.strip()]
        if not packages:
            return "packages"
        if len(packages) <= max_packages:
            return ", ".join(packages)
        shown = ", ".join(packages[:max_packages])
        return f"{shown}, ... (+{len(packages) - max_packages} more)"

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

    def _build_keep_alive_message(self, elapsed_seconds: int) -> Optional[str]:
        """Build keep-alive message shown while pip is quiet."""
        if self.current_action == "Completed":
            return None
        if self.current_action == "Installing":
            return f"⏳ Still installing packages... ({elapsed_seconds}s elapsed)"
        return f"⏳ Still processing dependencies... ({elapsed_seconds}s elapsed)"

    def _keep_alive_loop(self) -> None:
        """Emit periodic keep-alive updates when pip output is idle."""
        while not self._keep_alive_stop_event.wait(self._keep_alive_interval_seconds):
            if not self.stderr_is_tty:
                continue

            now = time.monotonic()
            last_output_at = self._last_output_at
            started_at = self._keep_alive_started_at
            if last_output_at is None or started_at is None:
                continue
            if now - last_output_at < self._keep_alive_interval_seconds:
                continue

            elapsed_seconds = int(now - started_at)
            message = self._build_keep_alive_message(elapsed_seconds)
            if message:
                self._display_progress(message)

    def start_keep_alive(self, interval_seconds: float = 8.0) -> None:
        """Start background keep-alive updates for long silent install periods."""
        if not self.stderr_is_tty:
            return
        if self._keep_alive_thread and self._keep_alive_thread.is_alive():
            return

        self._keep_alive_interval_seconds = max(interval_seconds, 1.0)
        now = time.monotonic()
        self._keep_alive_started_at = now
        self._last_output_at = now
        self._keep_alive_stop_event.clear()
        self._keep_alive_thread = threading.Thread(target=self._keep_alive_loop, daemon=True)
        self._keep_alive_thread.start()

    def stop_keep_alive(self) -> None:
        """Stop background keep-alive updates."""
        self._keep_alive_stop_event.set()
        if self._keep_alive_thread and self._keep_alive_thread.is_alive():
            self._keep_alive_thread.join(timeout=0.5)
        self._keep_alive_thread = None

    def parse_line(self, line: str) -> None:
        """Parse a line of pip output and update progress display."""
        line = line.strip()
        if not line:
            return

        self._last_output_at = time.monotonic()

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
            raw_requirement = collecting_match.group(1)
            package = self._normalize_requirement_name(raw_requirement) or raw_requirement

            self.current_package = package
            self.current_action = "Collecting"
            
            # Only track packages we haven't seen yet
            if package not in self.seen_packages:
                self.seen_packages.add(package)
                self.collecting_shown = True

                count = len(self.seen_packages)
                self._display_progress(f"📦 Resolving dependency: {package} ({count} total)")
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
            package = self._package_from_artifact_name(filename)
            if package:
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
            else:
                self.current_package = None
                self.current_action = "Downloading"
                self._display_progress("⬇️  Downloading dependency...")
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
                formatted = self._format_installing_packages(packages_list)
                self._display_progress(f"📦 Installing: {formatted}")
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
            package = self._package_from_artifact_name(filename)
            if package:
                self.current_package = package
                self.current_action = "Using cached"
                # Show that we're using cached version
                self._display_progress(f"💾 Using cached {package}...")
            else:
                self.current_package = None
                self.current_action = "Using cached"
                self._display_progress("💾 Using cached dependency...")
            return

    def finish(self) -> None:
        """Finish the progress display and clear any remaining messages."""
        self.stop_keep_alive()
        if self.stderr_is_tty and self.last_message:
            clear_line()
            sys.stderr.flush()
