from jarvis_home.app import create_session_cookie, valid_session_cookie


def test_signed_session_cookie_is_valid_before_expiry():
    cookie = create_session_cookie(2_000_000_000)
    assert valid_session_cookie(cookie, now=1_900_000_000)


def test_session_cookie_rejects_tampering_and_expiry():
    cookie = create_session_cookie(2_000_000_000)
    assert not valid_session_cookie(cookie + "x", now=1_900_000_000)
    assert not valid_session_cookie(cookie, now=2_000_000_001)
    assert not valid_session_cookie("bad-cookie", now=1)
