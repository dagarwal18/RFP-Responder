"""Allow running as: python -m rfp_automation"""

from rfp_automation.main import run, serve
import sys

if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve()
    else:
        file_arg = sys.argv[1] if len(sys.argv) > 1 else ""
        run(file_arg)
