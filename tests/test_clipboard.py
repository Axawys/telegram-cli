import pytest

from telega import clipboard


def test_image_file_from_uris(tmp_path):
    img = tmp_path / "фото 1.png"
    img.write_bytes(b"x")
    other = tmp_path / "doc.txt"
    other.write_text("x")
    uris = f"# comment\nfile://{other}\nfile://{str(img).replace(' ', '%20')}\n"
    assert clipboard.image_file_from_uris(uris) == img
    assert clipboard.image_file_from_uris(f"file://{tmp_path}/нет.png") is None


@pytest.fixture
def fake_clip(monkeypatch):
    """Буфер обмена без wl-paste: {mime: данные}."""
    data: dict[str, bytes] = {}

    async def run(*cmd):
        if cmd[-1] == "--list-types":
            return "\n".join(data).encode()
        return data.get(cmd[-1], b"")

    monkeypatch.setattr(clipboard, "_backend", lambda: (["x", "--list-types"], ["x", "--type"]))
    monkeypatch.setattr(clipboard, "_run", run)
    return data


async def test_read_image_prefers_png(fake_clip, tmp_path):
    fake_clip.update({"text/plain": b"hi", "image/jpeg": b"J", "image/png": b"P"})
    content = await clipboard.read_clipboard(tmp_path)
    assert content.image.suffix == ".png" and content.image.read_bytes() == b"P"


async def test_read_uri_list_and_text(fake_clip, tmp_path):
    img = tmp_path / "a.jpg"
    img.write_bytes(b"J")
    fake_clip.update({"text/uri-list": f"file://{img}".encode(), "text/plain": b"x"})
    assert (await clipboard.read_clipboard(tmp_path / "out")).image == img

    fake_clip.clear()
    fake_clip["text/plain;charset=utf-8"] = "привет".encode()
    content = await clipboard.read_clipboard(tmp_path)
    assert content == clipboard.ClipboardContent(text="привет")

    fake_clip.clear()
    assert await clipboard.read_clipboard(tmp_path) == clipboard.ClipboardContent()
