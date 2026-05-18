import sys
import os
print("sys.executable =", sys.executable)
print("sys.prefix     =", sys.prefix)
print("PATH head      =", os.environ.get("PATH", "")[:500])