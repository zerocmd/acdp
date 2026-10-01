"""Identity: key, DID, fingerprint, and signatures."""

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from arena.identity import Identity, canonical, fingerprint_jwk, verify_signature

X = "iojj3XQJ8ZX9UtstPLpdcspnCb8dlBIb83SIAbQPb1w"
FP = "NHUPmL1Z_PyUbaRaqr6TO-FUpLUJThxKv0KGZQXzyX4"


def fixed_identity():
    key = Ed25519PrivateKey.from_private_bytes(bytes([1]) * 32)
    return Identity("halcyon-intel", "halcyon-intel.example", key)


def test_known_key_vector():
    ident = fixed_identity()
    assert ident.public_jwk() == {"kty": "OKP", "crv": "Ed25519", "x": X}
    assert ident.fingerprint() == FP
    assert fingerprint_jwk(ident.public_jwk()) == FP
    assert len(FP) == 43


def test_agent_id_and_did():
    ident = fixed_identity()
    assert ident.agent_id == "halcyon-intel.halcyon-intel.example"
    assert ident.did == "did:web:halcyon-intel.example:agents:halcyon-intel"


def test_new_identities_get_distinct_keys():
    a = Identity("a", "x.example")
    b = Identity("a", "x.example")
    assert a.fingerprint() != b.fingerprint()


def test_canonical_form_ignores_key_order_and_sig():
    assert canonical({"b": 1, "a": "é", "sig": "zz"}) == '{"a":"é","b":1}'.encode()


def test_sign_and_verify_round_trip():
    ident = fixed_identity()
    payload = {"thread_id": "t1", "body": "Two sender domains seen."}
    signed = dict(payload, sig=ident.sign(payload))
    assert verify_signature(signed, ident.public_jwk())


def test_tampered_payload_fails():
    ident = fixed_identity()
    payload = {"thread_id": "t1", "body": "original"}
    signed = dict(payload, sig=ident.sign(payload), body="changed")
    assert not verify_signature(signed, ident.public_jwk())


def test_other_key_fails():
    ident = fixed_identity()
    payload = {"body": "x"}
    signed = dict(payload, sig=ident.sign(payload))
    assert not verify_signature(signed, Identity("o", "o.example").public_jwk())


def test_missing_garbage_sig_or_bad_jwk_fails_without_raising():
    ident = fixed_identity()
    assert not verify_signature({"body": "x"}, ident.public_jwk())
    assert not verify_signature({"body": "x", "sig": "!!!"}, ident.public_jwk())
    assert not verify_signature({"body": "x", "sig": "AAAA"}, {"x": "short"})
    assert not verify_signature({"body": "x", "sig": "AAAA"}, {})
