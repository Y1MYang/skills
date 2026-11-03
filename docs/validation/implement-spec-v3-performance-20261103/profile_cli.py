"""Profile a CLI without cProfile's swallowing of its SystemExit status."""
import cProfile
from pathlib import Path
import runpy
import sys

destination, script, *arguments = sys.argv[1:]
sys.argv = [script, *arguments]
sys.path.insert(0, str(Path(script).resolve().parent))
profile = cProfile.Profile()
profile.enable()
try:
    runpy.run_path(script, run_name="__main__")
finally:
    profile.disable()
    profile.dump_stats(destination)
