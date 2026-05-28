from app.tools.archive_tool import check_archive_magic, guess_archive_type


def test_rar_magic_accepts_rar4_and_rar5_headers():
    assert check_archive_magic(b"Rar!\x1a\x07\x00extra", ".rar")
    assert check_archive_magic(b"Rar!\x1a\x07\x01\x00extra", ".rar")


def test_rar_magic_rejects_non_rar_header():
    assert not check_archive_magic(b"PK\x03\x04extra", ".rar")


def test_guess_archive_type_detects_rar_extension():
    assert guess_archive_type("/tmp/sample.rar") == "rar"
