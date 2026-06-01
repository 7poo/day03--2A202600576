import os
import sqlite3
import csv
from typing import Any, Dict, List, Optional
from src.telemetry.logger import logger


class DataAccess:
    """Simple data access helper supporting SQLite and CSV for demo/testing.

    Usage:
      - If `db_path` provided and file exists -> opens SQLite DB.
      - Else if `csv_dir` provided -> reads CSV files named `students.csv`, `submissions.csv`.
    """

    def __init__(self, db_path: Optional[str] = None, csv_dir: Optional[str] = None):
        self.db_path = db_path
        self.csv_dir = csv_dir
        self.conn = None
        if db_path and os.path.exists(db_path):
            try:
                self.conn = sqlite3.connect(db_path)
                logger.log_event("DATA_ACCESS_INIT", {"backend": "sqlite", "db_path": db_path})
            except Exception as e:
                logger.log_event("DATA_ACCESS_ERROR", {"error": str(e)})
        elif csv_dir and os.path.isdir(csv_dir):
            logger.log_event("DATA_ACCESS_INIT", {"backend": "csv", "csv_dir": csv_dir})
        else:
            logger.log_event("DATA_ACCESS_INIT", {"backend": "none", "note": "no datasource found"})

    def get_student(self, student_id: str) -> Optional[Dict[str, Any]]:
        """Return student record by id."""
        if self.conn:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM students WHERE id = ?", (student_id,))
            row = cur.fetchone()
            if not row:
                return None
            cols = [c[0] for c in cur.description]
            return dict(zip(cols, row))

        if self.csv_dir:
            path = os.path.join(self.csv_dir, "students.csv")
            if not os.path.exists(path):
                return None
            with open(path, newline='', encoding='utf-8') as fh:
                reader = csv.DictReader(fh)
                for r in reader:
                    if r.get('id') == student_id:
                        return r
        return None

    def list_students(self) -> List[Dict[str, Any]]:
        if self.conn:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM students")
            rows = cur.fetchall()
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in rows]

        results = []
        if self.csv_dir:
            path = os.path.join(self.csv_dir, "students.csv")
            if os.path.exists(path):
                with open(path, newline='', encoding='utf-8') as fh:
                    reader = csv.DictReader(fh)
                    for r in reader:
                        results.append(r)
        return results

    def get_submissions(self, student_id: str) -> List[Dict[str, Any]]:
        """Return list of submission records for a student from `submissions.csv` or DB table."""
        if self.conn:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM submissions WHERE student_id = ?", (student_id,))
            rows = cur.fetchall()
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in rows]

        results = []
        if self.csv_dir:
            path = os.path.join(self.csv_dir, "submissions.csv")
            if os.path.exists(path):
                with open(path, newline='', encoding='utf-8') as fh:
                    reader = csv.DictReader(fh)
                    for r in reader:
                        if r.get('student_id') == student_id:
                            results.append(r)
        return results


def example_usage():
    da = DataAccess(csv_dir="./data")
    students = da.list_students()
    logger.log_event("EXAMPLE_DATA_ACCESS", {"students_count": len(students)})


if __name__ == "__main__":
    example_usage()
