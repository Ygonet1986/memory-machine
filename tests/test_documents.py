from pathlib import Path

from memory_machine.documents import (
    add_document,
    list_documents,
    remove_all_documents,
    remove_document,
    retrieve,
)


def test_add_and_retrieve(tmp_path):
    base = Path(tmp_path)
    src = tmp_path / "guide.txt"
    src.write_text(
        "Postgres is the primary database. Use connection pooling to avoid churn.\n\n"
        "Auth uses OAuth flows."
    )
    res = add_document(base, src)
    assert res["ok"] is True
    assert list_documents(base)[0]["name"] == "guide.txt"

    text = retrieve(base, "how should we connect to the database?")
    assert "Postgres" in text
    assert "connection pooling" in text


def test_retrieve_filters_irrelevant(tmp_path):
    base = Path(tmp_path)
    (tmp_path / "a.txt").write_text("This is about gardening and tomatoes.")
    text = retrieve(base, "database connection pooling")
    assert text == ""


def test_add_rejects_non_txt(tmp_path):
    base = Path(tmp_path)
    src = tmp_path / "a.md"
    src.write_text("x")
    assert add_document(base, src)["ok"] is False


def test_add_duplicate_renames(tmp_path):
    base = Path(tmp_path)
    src = tmp_path / "a.txt"
    src.write_text("hello")
    assert add_document(base, src)["ok"] is True
    res2 = add_document(base, src)
    assert res2["ok"] is True
    assert res2["name"] == "a-2.txt"
    assert len(list_documents(base)) == 2


def test_retrieve_no_docs(tmp_path):
    assert retrieve(Path(tmp_path), "anything") == ""


def test_remove(tmp_path):
    base = Path(tmp_path)
    src = tmp_path / "a.txt"
    src.write_text("hello world test")
    add_document(base, src)
    assert remove_document(base, "a.txt") is True
    assert remove_document(base, "a.txt") is False


def test_remove_all(tmp_path):
    base = Path(tmp_path)
    for name in ("a.txt", "b.txt"):
        src = tmp_path / name
        src.write_text("hello world test")
        add_document(base, src)
    assert remove_all_documents(base) == 2
    assert list_documents(base) == []
    assert remove_all_documents(base) == 0
