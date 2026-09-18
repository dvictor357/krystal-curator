"""Sign-In with Ethereum (EIP-4361): parse the signed text and recover the signer.

Pure functions, no I/O. Nonce issue/consume and the session live in web_auth.
Only externally-owned accounts are supported (ECDSA over EIP-191); smart-contract
wallets (EIP-1271) would need an RPC round-trip and are rejected as invalid.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_keys.exceptions import BadSignature
from eth_utils import is_checksum_address

HEADER = " wants you to sign in with your Ethereum account:"
MAX_LENGTH = 4000
CLOCK_SKEW = timedelta(minutes=10)
_NONCE = re.compile(r"^[A-Za-z0-9]{8,}$")
_FIELD = re.compile(r"^([A-Za-z ]+): (.*)$")


class SiweError(ValueError):
    """Message text or signature not acceptable; the text is safe to show the user."""


@dataclass(frozen=True)
class SiweMessage:
    domain: str
    address: str
    uri: str
    version: str
    chain_id: int
    nonce: str
    issued_at: datetime
    statement: str | None = None
    expiration_time: datetime | None = None
    not_before: datetime | None = None
    request_id: str | None = None
    resources: tuple[str, ...] = field(default_factory=tuple)


def _timestamp(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise SiweError(f"{name} is not an RFC 3339 timestamp") from None
    if parsed.tzinfo is None:
        raise SiweError(f"{name} must carry a timezone")
    return parsed.astimezone(UTC)


def parse(text: str) -> SiweMessage:
    """Parse EIP-4361 text; raises SiweError on anything off-spec."""
    if len(text) > MAX_LENGTH:
        raise SiweError("Sign-in message is too long")
    lines = text.split("\n")
    if len(lines) < 9 or not lines[0].endswith(HEADER):
        raise SiweError("Not a Sign-In with Ethereum message")
    domain = lines[0][: -len(HEADER)]
    if "://" in domain:
        domain = domain.split("://", 1)[1]
    if not domain or " " in domain:
        raise SiweError("Invalid domain")
    address = lines[1]
    if not is_checksum_address(address):
        raise SiweError("Address is not EIP-55 checksummed")
    if lines[2] != "":
        raise SiweError("Malformed message")
    statement: str | None = None
    cursor = 3
    if lines[cursor] != "":
        statement = lines[cursor]
        cursor += 1
    if lines[cursor] != "":
        raise SiweError("Malformed message")
    cursor += 1
    fields: dict[str, str] = {}
    resources: list[str] = []
    while cursor < len(lines):
        line = lines[cursor]
        cursor += 1
        if line.startswith("- ") and "Resources" in fields:
            resources.append(line[2:])
            continue
        if line == "Resources:" and "Resources" not in fields:
            fields["Resources"] = ""
            continue
        match = _FIELD.match(line)
        if not match or match.group(1) in fields:
            raise SiweError("Malformed message")
        fields[match.group(1)] = match.group(2)
    try:
        uri, version = fields["URI"], fields["Version"]
        chain_id, nonce, issued_at = fields["Chain ID"], fields["Nonce"], fields["Issued At"]
    except KeyError as missing:
        raise SiweError(f"Missing field {missing.args[0]}") from None
    if version != "1":
        raise SiweError("Unsupported message version")
    if not chain_id.isdigit():
        raise SiweError("Invalid chain id")
    if not _NONCE.match(nonce):
        raise SiweError("Invalid nonce")
    if not urlsplit(uri).scheme:
        raise SiweError("Invalid URI")
    return SiweMessage(
        domain=domain,
        address=address,
        uri=uri,
        version=version,
        chain_id=int(chain_id),
        nonce=nonce,
        issued_at=_timestamp(issued_at, "Issued At"),
        statement=statement,
        expiration_time=(
            _timestamp(fields["Expiration Time"], "Expiration Time")
            if "Expiration Time" in fields
            else None
        ),
        not_before=_timestamp(fields["Not Before"], "Not Before")
        if "Not Before" in fields
        else None,
        request_id=fields.get("Request ID"),
        resources=tuple(resources),
    )


def check_origin(message: SiweMessage, origin: str) -> None:
    """The message must have been produced for our site, not replayed from another."""
    expected = urlsplit(origin)
    if not expected.scheme or not expected.netloc:
        raise SiweError("Sign-in origin is not configured")
    if message.domain != expected.netloc:
        raise SiweError("Message was issued for a different site")
    actual = urlsplit(message.uri)
    if (actual.scheme, actual.netloc) != (expected.scheme, expected.netloc):
        raise SiweError("Message URI does not match this site")


def check_time(message: SiweMessage, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    if message.issued_at > now + CLOCK_SKEW:
        raise SiweError("Message is issued in the future")
    if message.expiration_time is None:
        if message.issued_at < now - CLOCK_SKEW:
            raise SiweError("Message has expired")
    elif message.expiration_time <= now:
        raise SiweError("Message has expired")
    if message.not_before is not None and message.not_before > now:
        raise SiweError("Message is not valid yet")


def verify_signature(text: str, message: SiweMessage, signature: str) -> str:
    """Recover the EIP-191 signer of `text`; must equal the address in the message."""
    try:
        signer = Account.recover_message(encode_defunct(text=text), signature=signature)
    except (BadSignature, ValueError, TypeError):
        raise SiweError("Signature is invalid") from None
    if signer != message.address:
        raise SiweError("Signature does not match the address")
    return signer
