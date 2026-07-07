"""Запуск DB Sentinel: python run.py [порт]"""
import os
import sys
from pathlib import Path

import uvicorn

# Позволяет запускать скрипт из любой папки
os.chdir(Path(__file__).resolve().parent)
sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    uvicorn.run("app.main:app", host="127.0.0.1", port=port)
