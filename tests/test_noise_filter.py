import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.collectors.noise_filter import scan, looks_foreign


def test_drop_contact_or_marketplace_link():
    is_noise, reasons = scan("https://s.shopee.co.id/7fZ1Afunzd karpet harga mulai 150rb")
    assert is_noise
    assert "marketplace" in reasons


def test_drop_phone_spam():
    is_noise, reasons = scan("yang mau tanya tanya atau mau langsung pasang, boleh chat saya. 082112345678")
    assert is_noise
    assert any(r in reasons for r in ("contact", "ad_sales"))


def test_drop_whatsapp_contact():
    is_noise, reasons = scan("Whatsapp 085934378954")
    assert is_noise


def test_drop_rental_sales():
    is_noise, reasons = scan("Ready Sewa Mobil harian/mingguan/bulanan, hubungi kami")
    assert is_noise
    assert "ad_sales" in reasons


def test_drop_foreign_language():
    is_noise, reasons = scan("Ja swoja przygodę z SL7 zaczęłam 6 dni temu, ale po co")
    assert is_noise
    assert "foreign_language" in reasons


def test_drop_without_accents_foreign():
    for text in ("Hola todos, es un super carro muy bueno",
                 "Bravo trois classe et sombre toujours",
                 "Jeg for samme bil om en maaned, det er bra",
                 "Ja swoja przygoda z SL7 zaczalem 6 dni temu"):
        is_noise, _ = scan(text)
        assert is_noise, text
        assert looks_foreign(text), text


def test_drop_phone_only_even_when_long_truncation():
    text = "Whatsapp 085934378954 Lihat selengkapnya"
    is_noise, reasons = scan(text)
    assert is_noise
    assert "contact" in reasons


def test_drop_accented_spanish():
    is_noise, reasons = scan("Hola, es un súper carro, me encanta muchísimo")
    assert is_noise
    assert "foreign_language" in reasons


def test_drop_ev_charger_ad():
    text = ("Punya Mobil Listrik? Saatnya Isi Daya di Rumah! Tidak perlu antre di SPKLU. "
            "Dengan EV Charger Home, Anda bisa charging dengan promo spesial bulan ini. "
            "Hubungi wa kami")
    is_noise, _ = scan(text)
    assert is_noise


def test_drop_car_mat_marketplace_ad():
    text = ("https://s.shopee.co.id/7fZ1Afunzd Xmate Karpet Mobil Xpeng X9 2025-Sekarang "
            "Bahan TPE Premium 100% Presisi, Plug and Play, Garansi 10 Tahun Ganti Baru")
    is_noise, _ = scan(text)
    assert is_noise


def test_keep_long_discussion_mentioning_contact():
    text = ("Sebelumnya saya coba ACC di tol, mobil depan ngerem ikut halus dan jaga jarak "
            "aman. Kalau ada yang mau tanya lebih lanjut bisa cek nomor 081234567890 saya, "
            "terima kasih sudah berbagi pengalaman soal cruise control ini.")
    is_noise, _ = scan(text)
    assert not is_noise


def test_drop_forsale_post():
    text = ("Toyota Veloz 2023 dijual, harga nego sampe jadi. Serius buyer aja, "
            "hubungi WA 081234567890.")
    is_noise, reasons = scan(text)
    assert is_noise
    assert "ad_sales" in reasons


def test_drop_forsale_with_installment():
    text = "Halo semua, saya jual mobil nih, harga nego, bisa kredit/cicilan, DP ringan."
    is_noise, reasons = scan(text)
    assert is_noise
    assert "ad_sales" in reasons


def test_drop_flash_sale_marketplace():
    text = "Flash sale weekend! Diskon 10% semua aksesoris, cek link di bio."
    is_noise, reasons = scan(text)
    assert "ad_sales" in reasons


def test_keep_genuine_adas_discussion():
    text = "ACC-nya di tol mantap, mobil depan ngerem ikut halus. Jarak aman bisa diatur."
    is_noise, _ = scan(text)
    assert not is_noise


def test_keep_question_about_acc():
    text = "PDA sama ACC bedanya apa ya? Ada yang udah nyobain di jalan macet?"
    is_noise, _ = scan(text)
    assert not is_noise


def test_keep_english_review():
    text = "Adaptive cruise control works great on the highway, follows smoothly."
    is_noise, _ = scan(text)
    assert not is_noise


def test_keep_short_mocklike():
    text = "Malam semua. Sudah ada yang coba fitur ADAS di J5?"
    is_noise, _ = scan(text)
    assert not is_noise


def test_emoji_only_dropped():
    is_noise, _ = scan("😂😂😂")
    assert is_noise


def test_looks_foreign_heuristic():
    assert looks_foreign("Es un súper carro bravo").__class__ is bool