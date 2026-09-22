import os
import json
import csv
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime, timezone

from src.config_loader import resolve_path


class DataStore:
    """Append-only, idempotent storage of data layers as CSV/JSONL files."""

    def __init__(self):
        pass

    @staticmethod
    def _path(layer: str, filename: str) -> str:
        dirname = resolve_path(layer)
        os.makedirs(dirname, exist_ok=True)
        return os.path.join(dirname, filename)

    def write_rows_csv(self, layer: str, filename: str, rows: List[Dict]):
        if not rows:
            return 0
        path = self._path(layer, filename)
        df = pd.DataFrame(rows)
        if os.path.exists(path):
            existing = pd.read_csv(path, dtype=str)
            combined = pd.concat([existing, df], ignore_index=True)
            combined = combined.drop_duplicates(
                subset=([c for c in ("record_id", "post_id", "comment_id") if c in combined.columns]),
                keep="last",
            )
        else:
            combined = df
        combined.to_csv(path, index=False, encoding="utf-8-sig")
        return len(rows)

    def append_rows_jsonl(self, layer: str, filename: str, rows: List[Dict]):
        if not rows:
            return
        path = self._path(layer, filename)
        with open(path, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")

    def read_csv(self, layer: str, filename: str) -> Optional[pd.DataFrame]:
        path = self._path(layer, filename)
        if not os.path.exists(path):
            return None
        return pd.read_csv(path, dtype=str)

    def read_jsonl(self, layer: str, filename: str) -> List[Dict]:
        path = self._path(layer, filename)
        if not os.path.exists(path):
            return []
        out = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def export_xlsx(self, layer: str, filename: str) -> str:
        path = self._path(layer, filename)
        df = self.read_csv(layer, filename)
        if df is None or df.empty:
            return ""
        excel_path = path.rsplit(".", 1)[0] + ".xlsx"
        df.to_excel(excel_path, index=False)
        return excel_path

    def list_files(self, layer: str) -> List[str]:
        dirname = resolve_path(layer)
        if not os.path.isdir(dirname):
            return []
        return sorted(os.listdir(dirname))