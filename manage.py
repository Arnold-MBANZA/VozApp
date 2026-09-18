from __future__ import annotations

import argparse

import database


def main() -> None:
    parser = argparse.ArgumentParser(description="Administration locale de VozLocal")
    subparsers = parser.add_subparsers(dest="command", required=True)
    promote = subparsers.add_parser("promote", help="Promouvoir un compte administrateur")
    promote.add_argument("email")
    args = parser.parse_args()

    database.initialize_database()
    if args.command == "promote":
        if database.promote_user(args.email):
            print(f"Le compte {args.email} est maintenant administrateur.")
        else:
            raise SystemExit("Aucun compte ne correspond à cette adresse e-mail.")


if __name__ == "__main__":
    main()
