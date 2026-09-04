from __future__ import annotations

import argparse

import uvicorn

from .api import create_app
from .database import Base, make_engine
from .legacy import import_legacy_state


def main() -> None:
    parser = argparse.ArgumentParser(description="Yonc local project graph")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Run the local web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8765, type=int)
    importer = sub.add_parser("import-legacy", help="Import current JSON state into SQLite")
    importer.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.command == "serve":
        uvicorn.run(create_app(), host=args.host, port=args.port)
    else:
        engine = make_engine()
        Base.metadata.create_all(engine)
        from sqlalchemy.orm import sessionmaker
        with sessionmaker(bind=engine)() as session:
            result = import_legacy_state(session)
            if args.dry_run:
                session.rollback()
                result["dry_run"] = True
            else:
                session.commit()
            print(result)


if __name__ == "__main__":
    main()
