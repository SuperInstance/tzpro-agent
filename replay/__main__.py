"""replay.__main__ — entry point for python -m replay."""
from .cli import main
import sys

if __name__ == "__main__":
    sys.exit(main())
