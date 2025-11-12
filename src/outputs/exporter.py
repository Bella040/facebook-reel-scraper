from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import pandas as pd

class Exporter:
    def __init__(self) -> None:
        pass

    @staticmethod
    def _ensure_dir(path: str) -> None:
        d = os.path.dirname(path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)

    def to_json(self, records: List[Dict[str, Any]], path: str) -> None:
        self._ensure_dir(path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

    def to_csv(self, records: List[Dict[str, Any]], path: str) -> None:
        self._ensure_dir(path)
        df = pd.DataFrame(records)
        df.to_csv(path, index=False)

    def to_excel(self, records: List[Dict[str, Any]], path: str) -> None:
        self._ensure_dir(path)
        df = pd.DataFrame(records)
        df.to_excel(path, index=False, engine="openpyxl")

    def to_html(self, records: List[Dict[str, Any]], path: str, title: str = "Results") -> None:
        self._ensure_dir(path)
        df = pd.DataFrame(records)
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 8px; }}
th {{ background: #f4f4f4; text-align: left; }}
</style>
</head>
<body>
<h1>{title}</h1>
{df.to_html(index=False, escape=False)}
</body>
</html>
"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)