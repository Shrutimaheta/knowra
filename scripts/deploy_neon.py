"""Deploy with existing ignored settings; never print credential values."""

import shutil
import subprocess
import sys

from check_ai import load_local_settings

if __name__ == "__main__":
    load_local_settings()
    executable = shutil.which("neon.cmd") or shutil.which("neon")
    if not executable:
        raise SystemExit("Install the Neon CLI before deployment.")
    raise SystemExit(subprocess.run([executable, "deploy", "--env", ".env", *sys.argv[1:]]).returncode)
