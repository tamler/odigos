"""Auto-install CLI tools for plugins."""
import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)


def is_installed(command: str) -> bool:
    """Check if a CLI command is available on PATH."""
    return shutil.which(command) is not None


def install_npm_package(package: str, command: str) -> bool:
    """Install an npm package globally. Returns True on success."""
    if is_installed(command):
        return True

    logger.info("Installing %s...", package)
    try:
        # For persistent CLIs, use npm install -g
        subprocess.run(
            ["npm", "install", "-g", package],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        logger.info("Successfully installed %s", package)
        return True
    except FileNotFoundError:
        logger.warning("npm not found -- cannot auto-install %s. Install Node.js first.", package)
        return False
    except subprocess.CalledProcessError as e:
        logger.warning("Failed to install %s: %s", package, e.stderr[:200])
        return False
    except subprocess.TimeoutExpired:
        logger.warning("Installation of %s timed out", package)
        return False
