from silicon_office.common.ipc import NDJSONBuffer, decode_message, encode_message


def test_encode_decode_round_trip():
    obj = {"v": 1, "type": "diff", "session_id": "abc", "op": "upsert"}
    encoded = encode_message(obj)
    assert encoded.endswith(b"\n")
    assert decode_message(encoded.rstrip(b"\n")) == obj


def test_decode_malformed_returns_none():
    assert decode_message(b"{not valid json") is None
    assert decode_message(b"\xff\xfe") is None


def test_buffer_single_message():
    buf = NDJSONBuffer()
    messages = buf.feed(encode_message({"a": 1}))
    assert messages == [{"a": 1}]


def test_buffer_split_across_two_feeds():
    buf = NDJSONBuffer()
    payload = encode_message({"a": 1, "b": "hello"})
    half = len(payload) // 2
    assert buf.feed(payload[:half]) == []
    assert buf.feed(payload[half:]) == [{"a": 1, "b": "hello"}]


def test_buffer_coalesced_messages_in_one_feed():
    buf = NDJSONBuffer()
    combined = encode_message({"a": 1}) + encode_message({"a": 2}) + encode_message({"a": 3})
    messages = buf.feed(combined)
    assert messages == [{"a": 1}, {"a": 2}, {"a": 3}]


def test_buffer_holds_back_trailing_partial_line():
    buf = NDJSONBuffer()
    combined = encode_message({"a": 1}) + b'{"a":2'  # partial second message
    messages = buf.feed(combined)
    assert messages == [{"a": 1}]
    # completing the partial line on the next feed should now parse it
    more = buf.feed(b'}\n')
    assert more == [{"a": 2}]


def test_buffer_skips_malformed_line_but_keeps_going():
    buf = NDJSONBuffer()
    combined = b"not json at all\n" + encode_message({"a": 1})
    messages = buf.feed(combined)
    assert messages == [{"a": 1}]
