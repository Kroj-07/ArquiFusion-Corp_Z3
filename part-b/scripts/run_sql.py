import argparse
from pathlib import Path

from google.cloud import bigquery


def main():
    parser = argparse.ArgumentParser(description="Run a Part B SQL script in BigQuery Standard SQL")
    parser.add_argument("--project", required=True)
    parser.add_argument("--file", type=Path, required=True)
    args = parser.parse_args()
    if not args.file.is_file():
        raise SystemExit(f"SQL file does not exist: {args.file}")
    sql = args.file.read_text(encoding="utf-8")
    if not sql.strip():
        raise SystemExit(f"SQL file is empty: {args.file}")
    client = bigquery.Client(project=args.project)
    job = client.query(sql, job_config=bigquery.QueryJobConfig(use_legacy_sql=False))
    for row in job.result():
        print(dict(row.items()))
    print(f"Completed BigQuery job {job.job_id}")


if __name__ == "__main__":
    main()
