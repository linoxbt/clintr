import os
import time
from .db import Grid


def main():
    grid = Grid(os.environ.get("CLINTR_DATABASE_URL") or os.environ.get("CLINTR_DB", "/tmp/clintr-demo.sqlite3"))
    while True:
        print(grid.maintenance(), flush=True)
        time.sleep(10)


if __name__ == "__main__":
    main()
