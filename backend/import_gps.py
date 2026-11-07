"""Import timestamped GPS fixes for a CivicAI recording session."""
import argparse

from app.database.database import initialize_database
from app.geolocation.csv_import import import_gps_csv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--csv", required=True, dest="csv_path")
    parser.add_argument("--source", choices=("gps", "synthetic"), required=True)
    parser.add_argument("--simulated", action="store_true")
    args = parser.parse_args()
    if args.source == "synthetic" and not args.simulated:
        parser.error("--source synthetic requires --simulated")
    if args.source == "gps" and args.simulated:
        parser.error("--source gps cannot be marked --simulated")
    initialize_database()
    count = import_gps_csv(args.session_id, args.csv_path,
                           source=args.source, is_simulated=args.simulated)
    print(f"Imported or updated {count} GPS fixes for session {args.session_id}.")


if __name__ == "__main__":
    main()
