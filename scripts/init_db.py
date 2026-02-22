#!/usr/bin/env python3
"""Veritabanini elle baslatmak icin yardimci script.

Kullanim:
    python scripts/init_db.py
"""

import os
import sys

# Proje kokunu Python path'e ekle
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config
from src.database import init_db


def main():
    config = load_config()
    db_path = config.database.path
    print(f"Veritabani baslatiliyor: {db_path}")
    init_db(db_path)
    print("Veritabani basariyla olusturuldu.")


if __name__ == "__main__":
    main()
