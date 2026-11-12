"""Apple TV for guest-tv: "tv_kind": "appletv". Cut down from couch-tv's bridge/appletv.py
(github.com/Seagey/couch-tv, written there from the public notes on Apple's Companion Link protocol,
the one the iPhone's Control Centre remote uses). Nothing here is copied from another project and no
key of Apple's is included: pairing makes a pair of keys on this computer and the Apple TV is asked to
trust them once, with the 4 digit PIN it shows on screen. The keys stay in data/ (git ignored, 0600).

The Companion link is TCP, on a port the Apple TV announces on the network (often 49153; give the TV's
address as "<tv address>:<port>" when it is another). Each frame is one byte of type, three bytes of
length, then the payload. After pairing the payloads are ChaCha20-Poly1305 sealed and carry a small
binary format (OPACK). couch-tv's link is asyncio, so this file runs it on a private event loop on a
daemon thread and keeps every public method sync, like the other drivers.

What it does: remote keys, volume keys, sleep and wake (is_on reads asleep or awake), the app list
(couch-tv's bundle ids, then the Apple TV's own names), opening an app by bundle id, and opening
guest-tv's own tvOS app (tv-apps/tvos, "Guest TV") over Apple's home.

What it cannot: say which app is on screen (so the hook opens guest-tv each time the Apple TV wakes),
mute (the Siri remote has no mute over this link), open a show inside an app (the app opens on its own
home: couch-tv does the same on tvOS), type text, screenshots, the Guest profile picker. Apple's Home
button still opens Apple's home: tvOS lets no app replace it.

Checked against a stand-in Apple TV on the computer (tools/appletv_test.py), as couch-tv's driver was.
First reports from real Apple TVs wanted (docs/APPLE-TV.md).
"""
import asyncio, concurrent.futures, hashlib, hmac, json, os, re, secrets, shutil, struct, subprocess, sys, tempfile, threading, time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import tvbrands
import tvctl
from tvbrands import TVUnavailable, _Base

# guest-tv's own tvOS app (tv-apps/tvos). A free Apple ID needs a bundle id nobody else has registered,
# so owners add their own ending (dev.guesttv.appletv.<something>); any id starting with this counts.
GUEST_BUNDLE = "dev.guesttv.appletv"
TVOS = os.path.join(tvbrands.HERE, "tv-apps", "tvos")
SIGNING = os.path.join(TVOS, "Config", "Signing.mine.xcconfig")   # the owner's own (git ignored)
BUILD = os.path.join(tvbrands.HERE, "build")
HOME_XCCONFIG = os.path.join(BUILD, "tvos", "Home.xcconfig")   # where the app finds the computer (git ignored)
RESIGN = os.path.join(tvbrands.HERE, "tools", "appletv-resign.sh")

# Bundle ids of well known tvOS apps (from couch-tv's bridge/appletv.py), for the apps in tvctl.APPS.
# The rest are found by the name the Apple TV lists them under.
BUNDLE_IDS = {
    "netflix": "com.netflix.Netflix", "youtube": "com.google.ios.youtube", "disney-plus": "com.disney.disneyplus",
    "prime-video": "com.amazon.aiv.AIVApp", "apple-tv": "com.apple.TVWatchList", "spotify": "com.spotify.client",
}
BUNDLE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-_]{2,149}")
PIN_RE = re.compile(r"\d{4}")

# ---------- frames ----------
F_PS_START, F_PS_NEXT, F_PV_START, F_PV_NEXT = 3, 4, 5, 6
F_U_OPACK, F_E_OPACK = 7, 8
MAX_FRAME = 1 << 20

# the Companion link's button codes
HID = {"up": 1, "down": 2, "left": 3, "right": 4, "menu": 5, "select": 6, "home": 7,
       "volume_up": 8, "volume_down": 9, "siri": 10, "screensaver": 11, "sleep": 12, "wake": 13,
       "play_pause": 14, "channel_up": 15, "channel_down": 16, "guide": 17, "page_up": 18, "page_down": 19}
# guest key -> HID name. The link has no skip keys: next and fast forward press right, previous and
# rewind press left, which is what the Siri remote's ring does in most tvOS players (a short skip).
KEYS = {"up": "up", "down": "down", "left": "left", "right": "right", "ok": "select", "back": "menu",
        "play_pause": "play_pause", "next": "right", "fast_forward": "right", "previous": "left", "rewind": "left",
        "volume_up": "volume_up", "volume_down": "volume_down"}

# FetchAttentionState: asleep, screensaver, awake
ASLEEP, SCREENSAVER, AWAKE = 1, 2, 3


class AppleTVError(TVUnavailable):
    """The Apple TV answered something unexpected, or the connection broke."""


class Refused(AppleTVError):
    """The Apple TV answered, and said no (an app it would not open). The connection is fine."""


class PairingError(AppleTVError):
    """Pairing failed: usually a wrong PIN."""


# ---------- OPACK ----------
def opack_encode(v):
    """Python value -> OPACK bytes. None, bool, non negative int, float, str, bytes, list and dict."""
    if v is None:
        return b"\x04"
    if v is True:
        return b"\x01"
    if v is False:
        return b"\x02"
    if isinstance(v, int):
        if v < 0:
            raise ValueError("OPACK here has no negative integers")
        if v < 40:
            return bytes([0x08 + v])
        for tag, size in ((0x30, 1), (0x31, 2), (0x32, 4), (0x33, 8)):
            if v < 1 << (8 * size):
                return bytes([tag]) + v.to_bytes(size, "little")
        raise ValueError("integer too large")
    if isinstance(v, float):
        return b"\x36" + struct.pack("<d", v)
    if isinstance(v, str):
        raw = v.encode()
        return _sized(raw, 0x40, 0x61, 0x20) + raw
    if isinstance(v, (bytes, bytearray)):
        raw = bytes(v)
        return _sized(raw, 0x70, 0x91, 0x20) + raw
    if isinstance(v, (list, tuple)):
        body = b"".join(opack_encode(x) for x in v)
        return (bytes([0xD0 + len(v)]) + body) if len(v) < 15 else b"\xdf" + body + b"\x03"
    if isinstance(v, dict):
        body = b"".join(opack_encode(k) + opack_encode(x) for k, x in v.items())
        return (bytes([0xE0 + len(v)]) + body) if len(v) < 15 else b"\xef" + body + b"\x03"
    raise TypeError("cannot OPACK a %s" % type(v).__name__)


def _sized(raw, short_base, long_base, short_max):
    n = len(raw)
    if n <= short_max:
        return bytes([short_base + n])
    for i, size in enumerate((1, 2, 3, 4)):
        if n < 1 << (8 * size):
            return bytes([long_base + i]) + n.to_bytes(size, "little")
    raise ValueError("too long")


def opack_decode(data):
    """OPACK bytes -> Python value. Understands what the encoder writes, plus floats, UUIDs, endless
    collections and back references, which an Apple TV may send."""
    objects = []

    def take(pos):
        tag = data[pos]
        pos += 1
        if tag == 0x01:
            return True, pos
        if tag == 0x02:
            return False, pos
        if tag in (0x03, 0x04):
            return None, pos
        if tag == 0x05:
            return bytes(data[pos:pos + 16]), pos + 16       # a UUID
        if 0x08 <= tag <= 0x2F:
            return tag - 8, pos
        if 0x30 <= tag <= 0x33:
            n = 1 << (tag - 0x30)
            val = int.from_bytes(data[pos:pos + n], "little")
            objects.append(val)
            return val, pos + n
        if tag == 0x35:
            val = struct.unpack("<f", data[pos:pos + 4])[0]
            objects.append(val)
            return val, pos + 4
        if tag == 0x36:
            val = struct.unpack("<d", data[pos:pos + 8])[0]
            objects.append(val)
            return val, pos + 8
        if 0x40 <= tag <= 0x64 or 0x70 <= tag <= 0x94:
            text = tag <= 0x64
            first = 0x40 if text else 0x70
            if tag <= first + 0x20:
                n = tag - first
            else:
                size = tag - first - 0x20
                n, pos = int.from_bytes(data[pos:pos + size], "little"), pos + size
            if pos + n > len(data):
                raise IndexError
            val = bytes(data[pos:pos + n])
            val = val.decode() if text else val
            objects.append(val)
            return val, pos + n
        if 0xA0 <= tag <= 0xC0:
            return objects[tag - 0xA0], pos
        if 0xC1 <= tag <= 0xC4:
            n = tag - 0xC0
            return int.from_bytes(data[pos:pos + n], "little"), pos + n
        if 0xD0 <= tag <= 0xDF:
            items, count = [], tag - 0xD0
            while (count != 15 and len(items) < count) or (count == 15 and data[pos] != 0x03):
                val, pos = take(pos)
                items.append(val)
            return items, pos + (1 if count == 15 else 0)
        if 0xE0 <= tag <= 0xEF:
            out, count = {}, tag - 0xE0
            while (count != 15 and len(out) < count) or (count == 15 and data[pos] != 0x03):
                k, pos = take(pos)
                val, pos = take(pos)
                out[k if isinstance(k, (str, int, bytes)) else str(k)] = val
            return out, pos + (1 if count == 15 else 0)
        raise AppleTVError("OPACK tag 0x%02x not understood" % tag)

    try:
        val, _ = take(0)
    except (IndexError, struct.error, UnicodeDecodeError, RecursionError):
        raise AppleTVError("the Apple TV sent a message that could not be read") from None
    return val


# ---------- TLV8 (HomeKit pairing's small container) ----------
T_METHOD, T_IDENTIFIER, T_SALT, T_PUBLIC_KEY, T_PROOF, T_ENCRYPTED, T_SEQ, T_ERROR, T_SIGNATURE = 0, 1, 2, 3, 4, 5, 6, 7, 10


def tlv_encode(items):
    """[(type, bytes)] -> bytes. A value over 255 bytes is split into runs."""
    out = b""
    for t, v in items:
        v = bytes(v)
        if not v:
            out += bytes([t, 0])
        for i in range(0, len(v), 255):
            chunk = v[i:i + 255]
            out += bytes([t, len(chunk)]) + chunk
    return out


def tlv_decode(data):
    out, i, last = {}, 0, None
    while i + 2 <= len(data):
        t, n = data[i], data[i + 1]
        chunk = data[i + 2:i + 2 + n]
        out[t] = out[t] + chunk if (t == last and t in out) else chunk
        last, i = t, i + 2 + n
    return out


# ---------- SRP-6a, 3072 bit, SHA-512 (the pairing PIN proof) ----------
# The 3072 bit safe prime of RFC 3526 (group 15, the same as RFC 5054's 3072 bit group), generator 5.
SRP_N = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3DC2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
    "83655D23DCA3AD961C62F356208552BB9ED529077096966D670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2BCBF6955817183995497CEA956AE515D2261898FA0510"
    "15728E5A8AAAC42DAD33170D04507A33A85521ABDF1CBA64ECFB850458DBEF0A8AEA71575D060C7DB3970F85A6E1E4C7"
    "ABF5AE8CDB0933D71E8C94E04A25619DCEE3D2261AD2EE6BF12FFA06D98A0864D87602733EC86A64521F2B18177B200C"
    "BBE117577A615D6C770988C0BAD946E208E24FA074E5AB3143DB5BFCE0FD108E4B82D120A93AD2CAFFFFFFFFFFFFFFFF", 16)
SRP_G = 5
SRP_LEN = 384


def _h(*parts):
    return hashlib.sha512(b"".join(parts)).digest()


def _i2b(n, pad=False):
    raw = n.to_bytes((n.bit_length() + 7) // 8 or 1, "big")
    return raw.rjust(SRP_LEN, b"\0") if pad else raw


def _b2i(b):
    return int.from_bytes(b, "big")


def srp_k():
    return _b2i(_h(_i2b(SRP_N), _i2b(SRP_G, True)))


def srp_x(salt, user, password):
    return _b2i(_h(salt, _h(user + b":" + password)))


def srp_u(a_pub, b_pub):
    return _b2i(_h(_i2b(a_pub, True), _i2b(b_pub, True)))


def srp_m1(user, salt, a_pub, b_pub, key):
    hn_xor_hg = bytes(x ^ y for x, y in zip(_h(_i2b(SRP_N)), _h(_i2b(SRP_G))))
    return _h(hn_xor_hg, _h(user), salt, _i2b(a_pub), _i2b(b_pub), key)


def srp_m2(a_pub, m1, key):
    return _h(_i2b(a_pub), m1, key)


class SRPClient:
    """The controller (guest-tv) side of the pairing PIN proof."""

    def __init__(self, user=b"Pair-Setup", password=b""):
        self.user, self.password = user, password
        self.a = _b2i(secrets.token_bytes(64)) % SRP_N or 1
        self.a_pub = pow(SRP_G, self.a, SRP_N)

    def process(self, salt, b_pub_bytes):
        b_pub = _b2i(b_pub_bytes)
        if b_pub % SRP_N == 0:
            raise PairingError("the Apple TV sent an invalid key")
        x = srp_x(salt, self.user, self.password)
        u = srp_u(self.a_pub, b_pub)
        s = pow((b_pub - srp_k() * pow(SRP_G, x, SRP_N)) % SRP_N, self.a + u * x, SRP_N)
        self.key = _h(_i2b(s))
        self.m1 = srp_m1(self.user, salt, self.a_pub, b_pub, self.key)
        return self.m1

    def verify_server(self, m2):
        return hmac.compare_digest(m2, srp_m2(self.a_pub, self.m1, self.key))


# ---------- the HomeKit style key steps ----------
def hkdf(secret, salt, info, n=32):
    return HKDF(algorithm=hashes.SHA512(), length=n, salt=salt, info=info).derive(secret)


def _nonce(label):
    return b"\0" * 4 + label if len(label) == 8 else label.rjust(12, b"\0")


def seal(key, label, data):
    return ChaCha20Poly1305(key).encrypt(_nonce(label), data, b"")


def unseal(key, label, data):
    try:
        return ChaCha20Poly1305(key).decrypt(_nonce(label), data, b"")
    except Exception:
        raise AppleTVError("the Apple TV's reply did not check out") from None


def raw_public(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def raw_private(key):
    return key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())


# ---------- one Companion connection (asyncio, run on the private loop below) ----------
class Link:
    """Framing, pairing, the sealed session, request and reply."""

    def __init__(self, host, port, timeout=6):
        self.host, self.port, self.timeout = host, port, timeout
        self.r = self.w = None
        self.out_key = self.in_key = None
        self.out_n = self.in_n = 0
        self.xid = secrets.randbelow(0xFFFF)

    @property
    def alive(self):
        """Open, and the Apple TV has not closed its side (a key press sent into a closed connection
        would be lost without an error, because presses get no answer)."""
        return bool(self.w) and not self.w.is_closing() and not self.r.at_eof()

    async def open(self):
        try:
            self.r, self.w = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), self.timeout)
        except (OSError, asyncio.TimeoutError) as e:
            raise TVUnavailable("the Apple TV did not answer (%s)" % type(e).__name__) from None

    async def close(self):
        if self.w:
            self.w.close()
            try:
                await self.w.wait_closed()
            except Exception:
                pass
        self.r = self.w = None
        self.out_key = self.in_key = None

    async def send(self, ftype, payload):
        if self.out_key:
            header = bytes([ftype]) + (len(payload) + 16).to_bytes(3, "big")
            nonce = self.out_n.to_bytes(12, "little")
            self.out_n += 1
            payload = ChaCha20Poly1305(self.out_key).encrypt(nonce, payload, header)
        try:
            self.w.write(bytes([ftype]) + len(payload).to_bytes(3, "big") + payload)
            await self.w.drain()
        except (OSError, AttributeError) as e:
            raise AppleTVError("the Apple TV closed the connection (%s)" % type(e).__name__) from None

    async def recv(self):
        try:
            header = await asyncio.wait_for(self.r.readexactly(4), self.timeout)
            n = int.from_bytes(header[1:], "big")
            if n > MAX_FRAME:
                raise AppleTVError("a frame that is too big")
            payload = await asyncio.wait_for(self.r.readexactly(n), self.timeout)
        except (asyncio.IncompleteReadError, OSError, asyncio.TimeoutError, AttributeError) as e:
            raise AppleTVError("the Apple TV stopped answering (%s)" % type(e).__name__) from None
        if self.in_key:
            nonce = self.in_n.to_bytes(12, "little")
            self.in_n += 1
            try:
                payload = ChaCha20Poly1305(self.in_key).decrypt(nonce, payload, header)
            except Exception:
                raise AppleTVError("a sealed message from the Apple TV did not check out") from None
        return header[0], payload

    async def step(self, ftype, fields):
        """Send an OPACK dict, read one OPACK dict back (the pairing steps)."""
        await self.send(ftype, opack_encode(fields))
        _, payload = await self.recv()
        return opack_decode(payload)

    def _tlv(self, msg, seq):
        t = tlv_decode(msg.get("_pd", b"")) if isinstance(msg, dict) else {}
        if T_ERROR in t:
            raise PairingError("the Apple TV refused (error %d). Start again and use the PIN it shows now." % t[T_ERROR][0])
        if t.get(T_SEQ) != bytes([seq]):
            raise AppleTVError("the Apple TV answered the wrong pairing step")
        return t

    # ----- pairing: once, with the PIN on screen -----
    async def pair_setup_start(self):
        m2 = await self.step(F_PS_START, {"_pd": tlv_encode([(T_METHOD, b"\0"), (T_SEQ, b"\1")]), "_pwTy": 1})
        return self._tlv(m2, 2)

    async def pair_setup_finish(self, t2, pin):
        srp = SRPClient(password=str(pin).encode())
        m1 = srp.process(t2[T_SALT], t2[T_PUBLIC_KEY])
        m4 = await self.step(F_PS_NEXT, {"_pd": tlv_encode([(T_SEQ, b"\3"), (T_PUBLIC_KEY, _i2b(srp.a_pub)),
                                                           (T_PROOF, m1)]), "_pwTy": 1})
        try:
            t4 = self._tlv(m4, 4)
        except PairingError:
            raise PairingError("the Apple TV did not accept that PIN. Run pair again and type the PIN it shows then.") from None
        if not srp.verify_server(t4[T_PROOF]):
            raise PairingError("the Apple TV's proof did not match")
        ltsk = Ed25519PrivateKey.generate()
        ltpk = raw_public(ltsk)
        client_id = secrets.token_hex(8).upper().encode()
        x = hkdf(srp.key, b"Pair-Setup-Controller-Sign-Salt", b"Pair-Setup-Controller-Sign-Info")
        sub = tlv_encode([(T_IDENTIFIER, client_id), (T_PUBLIC_KEY, ltpk),
                          (T_SIGNATURE, ltsk.sign(x + client_id + ltpk))])
        enc_key = hkdf(srp.key, b"Pair-Setup-Encrypt-Salt", b"Pair-Setup-Encrypt-Info")
        m6 = await self.step(F_PS_NEXT, {"_pd": tlv_encode([(T_SEQ, b"\5"), (T_ENCRYPTED, seal(enc_key, b"PS-Msg05", sub))]),
                                         "_pwTy": 1})
        t6 = self._tlv(m6, 6)
        acc = tlv_decode(unseal(enc_key, b"PS-Msg06", t6[T_ENCRYPTED]))
        ax = hkdf(srp.key, b"Pair-Setup-Accessory-Sign-Salt", b"Pair-Setup-Accessory-Sign-Info")
        try:
            Ed25519PublicKey.from_public_bytes(acc[T_PUBLIC_KEY]).verify(acc[T_SIGNATURE], ax + acc[T_IDENTIFIER] + acc[T_PUBLIC_KEY])
        except (InvalidSignature, KeyError, ValueError):
            raise PairingError("the Apple TV's signature did not check out") from None
        return {"client_id": client_id.decode(), "ltsk": raw_private(ltsk).hex(),
                "atv_id": acc[T_IDENTIFIER].decode(errors="replace"), "atv_ltpk": acc[T_PUBLIC_KEY].hex()}

    # ----- pair verify: every connection, with what pairing kept -----
    async def verify(self, cred):
        eph = X25519PrivateKey.generate()
        pub = raw_public(eph)
        m2 = await self.step(F_PV_START, {"_pd": tlv_encode([(T_SEQ, b"\1"), (T_PUBLIC_KEY, pub)]), "_auTy": 4})
        t2 = self._tlv(m2, 2)
        server_pub = t2[T_PUBLIC_KEY]
        try:
            shared = eph.exchange(X25519PublicKey.from_public_bytes(server_pub))
        except ValueError:
            raise AppleTVError("the Apple TV sent an invalid key") from None
        key = hkdf(shared, b"Pair-Verify-Encrypt-Salt", b"Pair-Verify-Encrypt-Info")
        inner = tlv_decode(unseal(key, b"PV-Msg02", t2[T_ENCRYPTED]))
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(cred["atv_ltpk"])).verify(
                inner[T_SIGNATURE], server_pub + inner[T_IDENTIFIER] + pub)
        except (InvalidSignature, KeyError, ValueError):
            raise PairingError("this is not the Apple TV that was paired (or it was reset): pair again") from None
        client_id = cred["client_id"].encode()
        ltsk = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(cred["ltsk"]))
        sub = tlv_encode([(T_IDENTIFIER, client_id), (T_SIGNATURE, ltsk.sign(pub + client_id + server_pub))])
        m4 = await self.step(F_PV_NEXT, {"_pd": tlv_encode([(T_SEQ, b"\3"), (T_ENCRYPTED, seal(key, b"PV-Msg03", sub))])})
        try:
            self._tlv(m4, 4)
        except PairingError:
            raise PairingError("the Apple TV does not know this pairing any more: pair again") from None
        self.out_key = hkdf(shared, b"", b"ClientEncrypt-main")
        self.in_key = hkdf(shared, b"", b"ServerEncrypt-main")
        self.out_n = self.in_n = 0

    # ----- requests -----
    async def ask(self, name, content=None, kind=2, wait=True):
        self.xid = (self.xid + 1) & 0xFFFF
        await self.send(F_E_OPACK, opack_encode({"_i": name, "_x": self.xid, "_t": kind, "_c": content if content is not None else {}}))
        if not wait:
            return None
        for _ in range(20):     # events may arrive between: skip them
            _, payload = await self.recv()
            msg = opack_decode(payload)
            if isinstance(msg, dict) and msg.get("_x") == self.xid and msg.get("_t") in (3, 4):
                if msg.get("_t") == 4 or "_em" in msg:
                    raise Refused(str(msg.get("_em") or "the Apple TV refused")[:120])
                return msg.get("_c") or {}
        raise AppleTVError("no answer to " + name)

    async def start_session(self):
        await self.ask("_systemInfo", {"_bf": 0, "_cf": 512, "_clFl": 128, "_i": "guest-tv", "_idsID": secrets.token_hex(8),
                                       "_pubID": "guest-tv", "_sf": 256, "_sv": "170.18", "model": "iPhone10,6",
                                       "name": "guest-tv"})
        sid = secrets.randbits(32)
        reply = await self.ask("_sessionStart", {"_srvT": "com.apple.tvremoteservices", "_sid": sid})
        self.sid = (int(reply.get("_sid") or 0) << 32) | sid
        try:
            await self.ask("TVRCSessionStart", {"ProtocolVersionKey": "1.2"})   # older tvOS answers an error: fine
        except Refused:
            pass


# ---------- the private event loop: one daemon thread for every Apple TV ----------
_loop = None
_loop_lock = threading.Lock()


def _run(coro, timeout=20):
    global _loop
    with _loop_lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, name="appletv-link", daemon=True).start()
    fut = asyncio.run_coroutine_threadsafe(coro, _loop)
    try:
        return fut.result(timeout)
    except concurrent.futures.TimeoutError:
        fut.cancel()
        raise TVUnavailable("the Apple TV did not answer in time") from None


def _signing_bundle(path):
    """PRODUCT_BUNDLE_IDENTIFIER from the owner's Signing.mine.xcconfig, when it is a usable id."""
    try:
        text = open(path).read()
    except OSError:
        return None
    m = re.search(r"^\s*PRODUCT_BUNDLE_IDENTIFIER\s*=\s*([A-Za-z0-9.\-_]+)\s*$", text, re.M)
    b = m.group(1) if m else None
    return b if b and BUNDLE_RE.fullmatch(b) and not b.endswith(".yourname") else None


class AppleTV(_Base):
    kind = "appletv"
    KEYS = KEYS
    pairing = "pin"
    sees_front = False     # the Companion link cannot say which app is in front
    GONE_IS_OFF = 60       # an asleep Apple TV still answers, so a short silence is a Wi-Fi dropout
    SETTLE = 1.5
    PORT = 49153           # the usual Companion port (tools/appletv_test.py moves it)
    TIMEOUT = 6
    APP_ID = None          # guest-tv's bundle id when it is not found by itself (see guest_id)
    SIGNING = SIGNING

    def __init__(self, ip):
        super().__init__(ip)
        m = re.fullmatch(r"(.+):(\d{2,5})", ip or "")
        self.host, self.port = (m.group(1), int(m.group(2))) if m else (ip, None)
        self.key_file = tvbrands._token_file("appletv", ip)
        self.listed = (0.0, {})   # (when, {bundle id: name}) as the Apple TV lists them
        self._link = None
        self._pairing = None

    # ---------- the pairing, kept in data/ (git ignored, 0600), never printed or logged ----------
    def _cred(self):
        try:
            c = json.loads(tvbrands._read(self.key_file) or "{}")
        except ValueError:
            return None
        return c if all(k in c for k in ("client_id", "ltsk", "atv_id", "atv_ltpk")) else None

    @property
    def paired(self):
        return bool(self._cred())

    def pair_start(self):
        """Ask the Apple TV to show its PIN. It must be awake (Settings, Remotes and Devices helps)."""
        with self.lock:
            _run(self._pair_start(), 20)

    def pair_finish(self, pin):
        pin = str(pin or "").strip()
        if not PIN_RE.fullmatch(pin):
            raise TVUnavailable("the PIN is the 4 digits the Apple TV shows")
        with self.lock:
            cred = _run(self._pair_finish(pin), 30)
            tvbrands._keep(self.key_file, json.dumps(cred))
            _run(self._drop(), 5)
        self.found, self.listed = (0.0, {}), (0.0, {})
        return True

    async def _pair_start(self):
        link = Link(self.host, self.port or self.PORT, self.TIMEOUT)
        await link.open()
        try:
            t2 = await link.pair_setup_start()
        except Exception:
            await link.close()
            raise
        if self._pairing:
            await self._pairing[0].close()
        self._pairing = (link, t2)

    async def _pair_finish(self, pin):
        if not self._pairing:
            raise PairingError("ask the Apple TV for a PIN first (pair_start)")
        link, t2 = self._pairing
        self._pairing = None
        try:
            return await link.pair_setup_finish(t2, pin)
        finally:
            await link.close()

    # ---------- the sealed session, opened when needed and kept ----------
    async def _session(self):
        if self._link and self._link.alive:
            return self._link, False
        cred = self._cred()
        if not cred:
            raise TVUnavailable("this Apple TV is not paired with guest-tv yet: tools/tv_app.py pair (docs/APPLE-TV.md)")
        link = Link(self.host, self.port or self.PORT, self.TIMEOUT)
        await link.open()
        try:
            await link.verify(cred)
            await link.start_session()
        except Exception:
            await link.close()
            raise
        self._link = link
        return link, True

    async def _drop(self):
        if self._link:
            await self._link.close()
        self._link = None

    async def _ask(self, name, content=None, wait=True):
        for attempt in (1, 2):
            link, fresh = await self._session()
            try:
                return await link.ask(name, content, wait=wait)
            except Refused:
                raise
            except TVUnavailable:
                await self._drop()
                if fresh or attempt == 2:   # a kept connection the Apple TV closed: one new one
                    raise

    def _call(self, name, content=None, wait=True, timeout=20):
        with self.lock:
            return _run(self._ask(name, content, wait), timeout)

    async def _press_async(self, code):
        c = HID[code]
        await self._ask("_hidC", {"_hBtS": 1, "_hidC": c}, wait=False)
        await asyncio.sleep(0.05)
        await self._ask("_hidC", {"_hBtS": 2, "_hidC": c}, wait=False)

    # ---------- what the hook and the Guest remote call ----------
    def attention(self):
        """ASLEEP, SCREENSAVER, AWAKE, or None when it does not answer or is not paired."""
        if not self.paired:
            return None
        try:
            c = self._call("FetchAttentionState", timeout=15)
        except TVUnavailable:
            return None
        s = c.get("state")
        return s if s in (ASLEEP, SCREENSAVER, AWAKE) else None

    def is_on(self):
        """Awake or showing its screensaver: on. Asleep: standby. None: no answer (or not paired yet).
        couch-tv counts the screensaver as off; here it counts as on, because the hook cannot see the
        screen and must not open guest-tv over a paused show when a guest wakes the screensaver."""
        a = self.attention()
        return None if a is None else a != ASLEEP

    def front(self):
        return None    # the Companion link does not say which app is in front

    def apps_listed(self, force=False):
        """{bundle id: name} as the Apple TV lists them, every 30 min. Ids that are not plain bundle
        ids are dropped here, so nothing odd the Apple TV sends goes back to it."""
        at, listed = self.listed
        if listed and not force and time.time() - at < 1800:
            return listed
        c = self._call("FetchLaunchableApplicationsEvent")
        listed = {b: t for b, t in (c or {}).items()
                  if isinstance(b, str) and isinstance(t, str) and BUNDLE_RE.fullmatch(b)}
        if listed:
            self.listed = (time.time(), listed)
        return listed

    def app_ids(self):
        """The guest apps on the Apple TV: couch-tv's bundle ids first, then by the name it lists."""
        at, found = self.found
        if found and time.time() - at < 1800:
            return found
        listed = self.apps_listed(force=True)
        names = {tvbrands.plain(a["name"]): a["id"] for a in tvctl.APPS}
        by_bundle = {b: aid for aid, b in BUNDLE_IDS.items()}
        found = {}
        for bundle, title in listed.items():
            aid = by_bundle.get(bundle) or names.get(tvbrands.plain(title))
            if aid and aid not in found:
                found[aid] = bundle
        if found:
            self.found = (time.time(), found)
        return found

    def launch(self, bundle):
        if not isinstance(bundle, str) or not BUNDLE_RE.fullmatch(bundle):
            raise ValueError("not a bundle id")
        try:
            self._call("_launchApp", {"_bundleID": bundle})
        except Refused as e:
            raise TVUnavailable("the Apple TV would not open %s (%s)" % (bundle, e)) from None

    def button(self, code):
        if code not in HID:
            raise KeyError(code)
        with self.lock:
            _run(self._press_async(code), 15)

    def volume(self, up):
        """The remote's volume keys: they change the TV's volume only when the Apple TV is set to control
        it (HDMI-CEC or a learned IR remote, in the Apple TV's Settings)."""
        self.button("volume_up" if up else "volume_down")

    def mute(self, on=None):
        raise TVUnavailable("an Apple TV has no mute over the network: turn the volume down, or use the TV's own remote")

    def sleep(self):
        self.quiet_until = 0.0
        self.button("sleep")

    def wake(self):
        self.button("wake")

    def open_link(self, uri, app_id):
        """tvOS gives no way in from outside to a show inside another app, so the app opens on its own
        home and the guest picks the show there (couch-tv does the same on an Apple TV)."""
        self.quiet(40)
        tid = self.app_ids().get(app_id)
        if not tid:
            raise TVUnavailable("%s is not on this TV" % tvctl.BY_ID[app_id]["name"])
        self.launch(tid)
        return "app"

    # ---------- guest-tv's own tvOS app ----------
    def guest_id(self):
        """guest-tv's bundle id: APP_ID, GUEST_TV_APPLETV_APP, the owner's Signing.mine.xcconfig, else
        the app on the Apple TV whose id is dev.guesttv.appletv or starts with it."""
        for b in (self.APP_ID, os.environ.get("GUEST_TV_APPLETV_APP"), _signing_bundle(self.SIGNING)):
            if b and BUNDLE_RE.fullmatch(b):
                return b
        for b in self.listed[1]:
            if b == GUEST_BUNDLE or b.startswith(GUEST_BUNDLE + "."):
                return b
        return GUEST_BUNDLE

    def open_guest_app(self):
        listed = self.apps_listed()
        bundle = self.guest_id()
        if listed and bundle not in listed:
            listed = self.apps_listed(force=True)   # it may have just been installed
            bundle = self.guest_id()
        if listed and bundle not in listed:
            raise TVUnavailable("guest-tv's app is not on this Apple TV yet: tools/tv_app.py install (docs/APPLE-TV.md)")
        self.launch(bundle)


# ---------------------------------------------------------------- putting Guest TV on the Apple TV

SETUP = """Apple TV (tvOS 17 or newer), once:
1. A Mac with Xcode, signed in to the owner's own Apple ID (Xcode, Settings, Accounts). A free Apple ID works.
2. Pair the Apple TV with Xcode: Apple TV Settings, Remotes and Devices, Remote App and Devices; Xcode, Window, Devices and Simulators, Pair.
3. Copy tv-apps/tvos/Config/Signing.example.xcconfig to Signing.mine.xcconfig and put in the team id and a bundle id of your own.
4. tools/tv_app.py install (builds Guest TV, signs it, puts it on the Apple TV), then pair (type the PIN the Apple TV shows), then open.
5. A free signature lasts 7 days: run tools/appletv-resign.sh twice a week from launchd (docs/APPLE-TV.md)."""


def _check_url(url, home_id):
    m = re.fullmatch(r"(https?)://([\w.:-]+)", url or "")
    if not m or not re.fullmatch(r"[a-z0-9-]+", home_id or ""):
        raise SystemExit("bad --url or --home")
    return m.group(1), m.group(2)


def write_home(url, home_id):
    """build/tvos/Home.xcconfig: where Guest TV finds this computer and which home it shows. Xcode reads
    it through tv-apps/tvos/Config/Base.xcconfig into the app's Info.plist. build/ is git ignored."""
    scheme, host = _check_url(url, home_id)
    os.makedirs(os.path.dirname(HOME_XCCONFIG), exist_ok=True)
    with open(HOME_XCCONFIG, "w") as f:
        f.write("// Written by tools/tv_app.py (tv_appletv.write_home). Where Guest TV finds the house computer.\n"
                "GUESTTV_SCHEME = %s\nGUESTTV_HOST = %s\nGUESTTV_HOME = %s\n" % (scheme, host, home_id))
    return HOME_XCCONFIG


def _xcode():
    if sys.platform != "darwin" or not shutil.which("xcodebuild"):
        raise SystemExit("Building the Apple TV app needs a Mac with Xcode (free from the App Store). docs/APPLE-TV.md")


def build(url, home_id, signed=None):
    """Build Guest TV for a real Apple TV into build/tvos-device and return the .app. Signed with the
    owner's Apple ID when tv-apps/tvos/Config/Signing.mine.xcconfig is there, else unsigned (a check
    that it compiles; it cannot go on an Apple TV like that)."""
    _xcode()
    write_home(url, home_id)
    if signed is None:
        signed = _signing_bundle(SIGNING) is not None
    out = os.path.join(BUILD, "tvos-device")
    cmd = ["xcodebuild", "-project", os.path.join(TVOS, "GuestTV.xcodeproj"), "-scheme", "GuestTV",
           "-configuration", "Release", "-destination", "generic/platform=tvOS", "-derivedDataPath", out]
    cmd += ["-allowProvisioningUpdates", "-allowProvisioningDeviceRegistration"] if signed else ["CODE_SIGNING_ALLOWED=NO"]
    log = os.path.join(BUILD, "appletv-build.log")
    with open(log, "w") as fh:
        r = subprocess.run(cmd + ["build"], stdout=fh, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        raise SystemExit("The Apple TV build failed. The end of build/appletv-build.log says why "
                         "(often: Xcode is not signed in, or the bundle id is taken).")
    if not signed:
        print("Built unsigned (no tv-apps/tvos/Config/Signing.mine.xcconfig yet): fine as a check, "
              "but install needs your own signing settings (docs/APPLE-TV.md).")
    return os.path.join(out, "Build", "Products", "Release-appletvos", "GuestTV.app")


def _device(name=""):
    """The Apple TV paired with Xcode: APPLETV_DEVICE, else the only one (or the one whose name holds
    APPLETV_NAME)."""
    if os.environ.get("APPLETV_DEVICE"):
        return os.environ["APPLETV_DEVICE"]
    tmp = os.path.join(tempfile.mkdtemp(prefix="guest-tv-devices-"), "d.json")
    subprocess.run(["xcrun", "devicectl", "list", "devices", "--json-output", tmp], capture_output=True)
    try:
        devices = json.load(open(tmp))["result"]["devices"]
    except Exception:
        devices = []
    want = (name or os.environ.get("APPLETV_NAME") or "").lower()
    tvs = [d for d in devices if (d.get("hardwareProperties") or {}).get("platform") == "tvOS"
           and want in ((d.get("deviceProperties") or {}).get("name") or "").lower()]
    if len(tvs) != 1:
        raise SystemExit("No single Apple TV paired with Xcode was found (%d). Pair it in Xcode, Window, Devices and "
                         "Simulators, or set APPLETV_NAME to part of its name." % len(tvs))
    return tvs[0]["identifier"]


def install(ip, url, home_id):
    """Build, sign with the owner's Apple ID, put Guest TV on the Apple TV and open it, with
    tools/appletv-resign.sh (the same script the weekly job runs)."""
    _xcode()
    write_home(url, home_id)
    if _signing_bundle(SIGNING) is None:
        raise SystemExit("First copy tv-apps/tvos/Config/Signing.example.xcconfig to Signing.mine.xcconfig and put in "
                         "your team id and a bundle id of your own (docs/APPLE-TV.md).")
    r = subprocess.run(["/bin/sh", RESIGN] + ([os.environ["APPLETV_NAME"]] if os.environ.get("APPLETV_NAME") else []))
    if r.returncode != 0:
        raise SystemExit("The install stopped: build/appletv-resign.log says why.")
    print("Guest TV is on the Apple TV. Now: tools/tv_app.py pair (type the PIN the Apple TV shows), then open.\n"
          "A free Apple ID signature lasts 7 days: set up the weekly job in docs/APPLE-TV.md.")


def uninstall(ip):
    """Take Guest TV off the Apple TV (Xcode's devicectl). The pairing stays until it is removed on the
    Apple TV (Settings, Remotes and Devices) and data/appletv-<address>.key is deleted."""
    _xcode()
    bundle = os.environ.get("GUEST_TV_APPLETV_APP") or _signing_bundle(SIGNING) or GUEST_BUNDLE
    if not BUNDLE_RE.fullmatch(bundle):
        raise SystemExit("bad bundle id")
    r = subprocess.run(["xcrun", "devicectl", "device", "uninstall", "app", "--device", _device(), bundle])
    print("Guest TV removed from the Apple TV." if r.returncode == 0 else "The Apple TV did not remove it (is it awake?).")
    print("Also: stop the weekly job (launchctl bootout, docs/APPLE-TV.md), and remove this computer in the Apple TV's "
          "Settings, Remotes and Devices.")
