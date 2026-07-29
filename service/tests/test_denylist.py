from service.app.denylist import is_denylisted


def test_flags_url_matching_denylisted_domain():
    assert is_denylisted("https://malware-example.test/payload", ["malware-example.test"]) is True


def test_allows_url_not_matching_any_entry():
    assert is_denylisted("https://example.com/page", ["malware-example.test"]) is False


def test_match_is_case_insensitive():
    assert is_denylisted("https://MALWARE-EXAMPLE.test/x", ["malware-example.test"]) is True


def test_empty_denylist_allows_everything():
    assert is_denylisted("https://malware-example.test/x", []) is False
