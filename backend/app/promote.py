"""Make an existing account an administrator from the server shell:

    docker exec subnet-scout python -m app.promote <username or email>
"""
import os, sys
from pathlib import Path

from .auth import AuthDB

def main(login):
    data = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "var"))
    data.mkdir(parents=True, exist_ok=True)
    db = AuthDB(data / "auth.db")
    u = db.find(login)
    if not u: sys.exit(f"No account {login}")
    if db.auth_method() == "2fa" and not u["totp_enabled"]: sys.exit("That account hasn't finished two-factor setup yet.")
    db.q("UPDATE users SET role='admin' WHERE id=?", (u["id"],))
    db.log("role.admin", "server shell", u["username"])
    print(f"{u['username']} is now an administrator.")

if __name__ == "__main__":
    main(sys.argv[1])
