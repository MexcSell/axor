"""Create the initial administrator (or reset an account to admin) from the server shell:

    docker exec subnet-scout python -m app.create_admin admin            # by username
    docker exec subnet-scout python -m app.create_admin you@example.com  # by email

Prints a one-time password. The first sign-in with it requires choosing a new password
(and setting up an authenticator app when the sign-in method is "2fa").
"""
import os, sys
from pathlib import Path

from .auth import AuthDB

def main(login):
    data = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "var"))
    data.mkdir(parents=True, exist_ok=True)
    db = AuthDB(data / "auth.db")
    try:
        name, pw = db.create_admin(login)
    except ValueError as e:
        sys.exit(str(e))
    print(f"Admin username: {name}")
    print(f"One-time password: {pw}")
    print("Sign in, then choose a new password" + (" (after authenticator setup)." if db.auth_method() == "2fa" else "."))

if __name__ == "__main__":
    if len(sys.argv) != 2: sys.exit(__doc__)
    main(sys.argv[1])
