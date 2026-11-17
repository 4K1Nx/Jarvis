import io

from PIL import Image

from viv.tools import images


def picture(width=2400, height=1200) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (40, 90, 160)).save(out, "PNG")
    return out.getvalue()


def result(n, license_="by", url=None):
    return {"id": f"id{n}", "title": f"Foto {n}", "creator": "Ana", "license": license_, "license_version": "4.0",
            "url": url or f"https://img.example/{n}.jpg", "foreign_landing_url": f"https://site.example/{n}"}


def test_good_result_is_saved_small_with_its_credit(tmp_path):
    found = images.find("solar panel", tmp_path, fetch_json=lambda q: {"results": [result(1)]}, fetch_bytes=lambda url: picture())
    saved = Image.open(found["path"])
    assert saved.width == images.MAX_WIDTH and saved.format == "JPEG"
    assert found["autor"] == "Ana" and found["licenca"] == "CC BY 4.0" and found["origem"] == "https://site.example/1"
    assert images.credit(found) == "Imagem: Foto 1, Ana, CC BY 4.0, https://site.example/1"


def test_bad_results_are_skipped_until_a_real_image(tmp_path):
    payloads = {"https://img.example/1.jpg": b"<html>nao sou imagem</html>", "https://img.example/3.jpg": picture(800, 400)}
    listed = {"results": [result(1), result(2, license_="by-nc"), result(9, url="http://inseguro.example/9.jpg"), result(3)]}
    found = images.find("x", tmp_path, fetch_json=lambda q: listed, fetch_bytes=lambda url: payloads[url])
    assert found["titulo"] == "Foto 3"


def test_nothing_usable_means_no_image(tmp_path):
    def broken(*a):
        raise OSError("sem rede")
    assert images.find("x", tmp_path, fetch_json=broken) is None
    assert images.find("x", tmp_path, fetch_json=lambda q: {"results": [result(1)]}, fetch_bytes=broken) is None
    assert images.find("x", tmp_path, fetch_json=lambda q: {"results": []}) is None
    assert images.find("  ", tmp_path, fetch_json=broken) is None
    big = b"x" * (images.MAX_BYTES + 1)
    assert images.find("x", tmp_path, fetch_json=lambda q: {"results": [result(1)]}, fetch_bytes=lambda url: big) is None


def test_user_image_is_found_by_name(tmp_path):
    photo = tmp_path / "usina.png"
    photo.write_bytes(picture(100, 50))
    found = images.local("usina", [str(tmp_path / "notas.txt"), str(photo)])
    assert found["path"] == str(photo) and "arquivo do usuário" in images.credit(found)
    assert images.local("outra", [str(photo)]) is None
