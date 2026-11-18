"""A fake browser push service (and browser) for testing AXoR Push without Google, Mozilla or Apple.

It hands out push subscriptions like a browser's PushManager would (an endpoint plus the p256dh and auth keys), then
accepts Web Push deliveries for them the way a push service does: it checks the VAPID signature (RFC 8292) and
decrypts the aes128gcm payload (RFC 8291) with the device's private key, and keeps what arrived.

  GET  /new                -> {"endpoint", "p256dh", "auth"} for a new fake device
  POST /push/<id>          -> 201 (a delivery); /push/gone-<id> answers 410 like an ended subscription
  GET  /inbox/<id>         -> [{"payload", "headers", "vapid_ok"}] what that device received

Run: uvicorn fake_push_service:app --port 8832, and give AXoR Push PUSH_HOSTS=http://127.0.0.1:8832
"""
import base64, json, os, struct

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import FastAPI, HTTPException, Request

app = FastAPI()
DEVICES, INBOX = {}, {}
BASE = os.getenv("FAKE_PUSH_BASE", "http://127.0.0.1:8832")

def b64u(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def unb64u(s): return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
def point(k): return k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)

@app.get("/new")
def new():
    key, auth = ec.generate_private_key(ec.SECP256R1()), os.urandom(16)
    did = b64u(os.urandom(9))
    DEVICES[did] = (key, auth)
    return {"id": did, "endpoint": f"{BASE}/push/{did}", "p256dh": b64u(point(key)), "auth": b64u(auth)}

def vapid_ok(header, aud):
    try:
        parts = dict(p.strip().split("=", 1) for p in header.removeprefix("vapid ").split(","))
        head, body, sig = parts["t"].split(".")
        claims = json.loads(unb64u(body))
        pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(parts["k"]))
        raw = unb64u(sig)
        pub.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                   f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
        return claims["aud"] == aud and claims["sub"].startswith(("mailto:", "https:"))
    except (KeyError, ValueError, InvalidSignature):
        return False

def decrypt(key, auth, body):
    salt, rs, n = body[:16], struct.unpack("!I", body[16:20])[0], body[20]
    as_pub, ct = body[21:21 + n], body[21 + n:]
    shared = key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))
    hk = lambda salt, ikm, info, ln: HKDF(hashes.SHA256(), ln, salt, info).derive(ikm)
    ikm = hk(auth, shared, b"WebPush: info\x00" + point(key) + as_pub, 32)
    plain = AESGCM(hk(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)).decrypt(hk(salt, ikm, b"Content-Encoding: nonce\x00", 12), ct, None)
    assert len(body) <= rs + 21 + n and plain.endswith(b"\x02"), "not a single final record"
    return plain[:-1]

@app.post("/push/{did}", status_code=201)
async def push(did: str, req: Request):
    if did.startswith("gone-"): raise HTTPException(410, "push subscription has unsubscribed or expired")
    if did not in DEVICES: raise HTTPException(404, "no such subscription")
    if req.headers.get("content-encoding") != "aes128gcm" or "ttl" not in req.headers: raise HTTPException(400, "bad headers")
    key, auth, body = *DEVICES[did], await req.body()
    payload = json.loads(decrypt(key, auth, body))
    INBOX.setdefault(did, []).append({"payload": payload, "headers": dict(req.headers), "raw": b64u(body),
                                      "vapid_ok": vapid_ok(req.headers.get("authorization", ""), BASE)})
    return {}

@app.get("/inbox/{did}")
def inbox(did: str):
    return INBOX.get(did, [])

@app.get("/key/{did}")  # for cross-checking with another decryption library in tests
def key(did: str):
    k, auth = DEVICES[did]
    return {"private": b64u(k.private_numbers().private_value.to_bytes(32, "big")), "auth": b64u(auth)}
