"""Create SQLite gradebook.db from CSV files in my-pfio.

Usage:
    python scripts/init_db.py --csv-dir ../my-pfio --out gradebook.db

This script creates tables: students (from admission.csv), academic_records (from academic_records.csv),
and submissions (from test.csv if present).
"""
import os
import sqlite3
import csv
import argparse


def create_tables(conn):
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS students(
        id TEXT PRIMARY KEY,
        nam_tuyensinh INTEGER,
        ptxt TEXT,
        tohoptxt TEXT,
        diem_trungtuyen REAL,
        diem_chuan REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS academic_records(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        hoc_ky TEXT,
        cpa REAL,
        gpa REAL,
        tc_dangky REAL,
        tc_hoanthan REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS submissions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        assignment TEXT,
        timestamp TEXT,
        filepath TEXT,
        raw_score REAL
    )
    """)
    conn.commit()


def ingest_admission(conn, csv_path):
    cur = conn.cursor()
    with open(csv_path, newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        rows = 0
        for r in reader:
            cur.execute(
                "REPLACE INTO students(id, nam_tuyensinh, ptxt, tohoptxt, diem_trungtuyen, diem_chuan) VALUES (?, ?, ?, ?, ?, ?)",
                (r.get('MA_SO_SV'), int(r.get('NAM_TUYENSINH') or 0), r.get('PTXT'), r.get('TOHOP_XT'),
                 float(r.get('DIEM_TRUNGTUYEN') or 0), float(r.get('DIEM_CHUAN') or 0))
            )
            rows += 1
    conn.commit()
    print(f"Inserted/Updated {rows} students from {csv_path}")


def ingest_academic(conn, csv_path):
    cur = conn.cursor()
    with open(csv_path, newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        rows = 0
        for r in reader:
            cur.execute(
                "INSERT INTO academic_records(student_id, hoc_ky, cpa, gpa, tc_dangky, tc_hoanthan) VALUES (?, ?, ?, ?, ?, ?)",
                (r.get('MA_SO_SV'), r.get('HOC_KY'), float(r.get('CPA') or 0), float(r.get('GPA') or 0),
                 float(r.get('TC_DANGKY') or 0), float(r.get('TC_HOANTHAN') or 0))
            )
            rows += 1
    conn.commit()
    print(f"Inserted {rows} academic records from {csv_path}")


def ingest_submissions(conn, csv_path):
    # test.csv may have different schema; attempt common fields
    cur = conn.cursor()
    with open(csv_path, newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        rows = 0
        for r in reader:
            student_id = r.get('student_id') or r.get('MA_SO_SV') or r.get('id')
            assignment = r.get('assignment') or r.get('assignment_name') or r.get('task')
            timestamp = r.get('timestamp') or r.get('time') or None
            filepath = r.get('filepath') or r.get('path') or None
            raw_score = r.get('raw_score') or r.get('score') or None
            try:
                raw_score = float(raw_score) if raw_score not in (None, '') else None
            except Exception:
                raw_score = None
            cur.execute(
                "INSERT INTO submissions(student_id, assignment, timestamp, filepath, raw_score) VALUES (?, ?, ?, ?, ?)",
                (student_id, assignment, timestamp, filepath, raw_score)
            )
            rows += 1
    conn.commit()
    print(f"Inserted {rows} submissions from {csv_path}")


def main(csv_dir, out_db):
    if not os.path.isdir(csv_dir):
        raise SystemExit(f"CSV directory not found: {csv_dir}")

    conn = sqlite3.connect(out_db)
    create_tables(conn)

    adm = os.path.join(csv_dir, 'admission.csv')
    ac = os.path.join(csv_dir, 'academic_records.csv')
    test = os.path.join(csv_dir, 'test.csv')

    if os.path.exists(adm):
        ingest_admission(conn, adm)
    else:
        print("admission.csv not found; skipping students ingestion")

    if os.path.exists(ac):
        ingest_academic(conn, ac)
    else:
        print("academic_records.csv not found; skipping academic ingestion")

    if os.path.exists(test):
        ingest_submissions(conn, test)
    else:
        print("test.csv not found; skipping submissions ingestion")

    conn.close()
    print(f"Database created at {out_db}")


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--csv-dir', default=os.path.join(os.path.dirname(__file__), '..', 'my-pfio'), help='Path to CSV folder')
    p.add_argument('--out', default='gradebook.db', help='Output SQLite DB path')
    args = p.parse_args()
    main(args.csv_dir, args.out)
