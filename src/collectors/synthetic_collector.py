"""Synthetic/local data source used for pilot mode and unit tests.

Produces realistic (anonymised, fictional) Jaecoo J5 community threads so the
full pipeline can be validated WITHOUT requiring Facebook access.
"""
import hashlib
import random
from typing import Dict, Iterable, List, Optional
from datetime import datetime, timedelta

from src.collectors.base import BaseCollector

TEMPLATES = [
    {
        "post": (
            "Malam semua. Sudah ada yang coba fitur ADAS di J5? ACC-nya kalau di jalan "
            "tol mantap, mobil depan berhenti ikut berhenti dengan halus."
        ),
        "comments": [
            "Iya gan, kemarin coba ACC di tol, pas mobil depan pindah jalur langsung akselerasinya terasa cepat. Agak kaget.",
            "Punya saya waktu stop and go kadang ngeremnya jedug, terutama pas macet. Tapi jalanan mengalir mah enak.",
            "ACC-nya bisa stop and go nggak? Rencana mau dipakai buat macet tiap hari.",
            "Katanya sih versi terbaru udah lebih halus pas ngerem. Belum sempat nyoba sih.",
            "J5 punya 17 fitur ADAS katanya, termasuk PDA. Ada yang udah nyobain PDA-nya pas di tikungan?",
            "Setirnya juga bisa ngikut sendiri di jalan tol, lumayan bantu. Tapi kadang agak maksa kalau jalan bergelombang.",
        ],
    },
    {
        "post": (
            "Review singkat J5 setelah 2 minggu. Ekspektasi saya PDA-nya bakal ngerem otomatis "
            "pas ada motor mendadak di depan, ternyata responnya agak telat."
        ),
        "comments": [
            "Saya kira pas mobil depan pindah jalur dia langsung ngerem, ternyata malah akselerasi. Sempat deg-degan.",
            "Untuk kondisi kota memang masih perlahan, tapi di jalan lurus ACC mantap.",
            "Menurut saya sih ACC Toyota lebih bagus dibanding J5, tapi J5 lebih smooth pas akselerasi.",
            "Bisa kasih tau setting jarak amannya gimana? Punya saya kok jaraknya kebanyakan.",
            "Halo, penasaran nih, PDA sama ACC bedanya apa ya?",
        ],
    },
    {
        "post": (
            "Test drive J5 kemarin. Fitur adaptive cruise control-nya oke untuk jalan santai. "
            "Mobil depan ngerem rem juga ikut halus."
        ),
        "comments": [
            "Jaga jarak di ACC bisa diatur 3 level kan? Ada yang pernah nemu bedanya di jalan macet?",
            "Pernah ngalamin cut-in dari motor, langsung dideteksi dan ngerem sendiri. Cukup responsif.",
            "Di tanjakan kadang ngikut kecepatan agak berat, terasa dipaksa.",
        ],
    },
    {
        "post": (
            "Ada yang tau cara setel PDA J5? Di manual cuma kebaca speed reduction sama curve assist, "
            "jarang dapet penjelasan detail."
        ),
        "comments": [
            "Pas di tikungan tajam dia otomatis ngurangin kecepatan, menurut saya itu kerja PDA.",
            "Saya jarang nyalain, takut terlalu sensitif pas ada pejalan kaki.",
            "Sudah pakai 3 bulan, jarang sekali sistem aktif kecuali di tol.",
        ],
    },
    {
        "post": (
            "Kemarin hampir nabrak pejalan kaki gara-gara PDA-nya nggak bereaksi. "
            "Atau memang belum ada fitur pedestrian detection di unit saya?"
        ),
        "comments": [
            "Waduh, saya juga sempat was-was. Pas ada pengendara motor tiba-tiba nyalip, responnya lambat.",
            "Katanya kalau speed-nya di bawah 30 km/jam sistemnya kurang agresif. Bener nggak?",
            "Saya malah ngerasa PDA kerjanya bagus pas ada kendaraan masuk jalur dari samping.",
        ],
    },
]

NON_RELEVANT_TEMPLATES = [
    {"post": "J5 harganya turun gak ya bulan ini? Ada promo besar-besaran katanya.", "comments": [
        "Mau nyicil J5, DP-nya berapa ya sekarang?",
        "Kemarin lihat di dealer warna putih stoknya banyak.",
    ]},
    {"post": "Aksesoris J5: ada rekomendasi tempat jual mat atau spoiler?", "comments": [
        "Di shopee banyak gan, cek aja.",
        "Saya beli karpet lantai di toko deket rumah, murah.",
    ]},
]


class SyntheticCollector(BaseCollector):
    """Generates deterministic synthetic community threads for pipeline testing."""

    data_source = "mock"

    def __init__(self, config: Dict, seed: Optional[int] = 42):
        super().__init__(config)
        self.rnd = random.Random(seed)
        self.max_posts = int(config.get("max_posts", 50))
        self.max_comments = int(config.get("max_comments_per_post", 40))
        self.max_replies = int(config.get("max_replies_per_comment", 25))
        self._posts = []

    def _load_posts(self):
        templates = list(TEMPLATES) + list(NON_RELEVANT_TEMPLATES)
        n = min(self.max_posts, len(templates))
        chosen = templates[:n]
        # pad with non-relevant if needed
        idx = 0
        while len(chosen) < self.max_posts:
            chosen.append(NON_RELEVANT_TEMPLATES[idx % len(NON_RELEVANT_TEMPLATES)])
            idx += 1
        self._posts = chosen[: self.max_posts]

    def iter_posts(self, community: Dict) -> Iterable[Dict]:
        self._load_posts()
        base_date = datetime.now() - timedelta(days=60)
        for i, tpl in enumerate(self._posts):
            post_id = f"mock_j5_{i:03d}"
            pd = tpl["post"]
            h = hashlib.md5(pd.encode("utf-8")).hexdigest()
            yield {
                "vehicle": "Jaecoo J5",
                "community": community.get("community_name", "Mock Community"),
                "community_url": community.get("url", "https://mock.local/j5"),
                "post_id": post_id,
                "comment_id": None,
                "parent_id": None,
                "source_type": "post",
                "text": pd,
                "url": f"https://mock.local/j5/posts/{post_id}",
                "date": (base_date + timedelta(days=i)).date().isoformat(),
                "author_pseudonym": f"USER_{hashlib.md5(f'{post_id}_author'.encode()).hexdigest()[:8]}",
                "content_hash": h,
            }

    def iter_comments(self, post: Dict) -> Iterable[Dict]:
        post_id = post.get("post_id", "")
        idx = int(post_id.split("_")[-1]) if "_" in post_id else 0
        templates = list(TEMPLATES) + list(NON_RELEVANT_TEMPLATES)
        comments = (templates[idx]["comments"] if idx < len(templates)
                    else NON_RELEVANT_TEMPLATES[0]["comments"])
        base = (post.get("date") or datetime.now().isoformat())[:10]
        for j, c in enumerate(comments[: self.max_comments]):
            cid = f"mock_j5_{idx}_c{j:02d}"
            yield {
                "vehicle": post.get("vehicle", "Jaecoo J5"),
                "community": post.get("community", "Mock Community"),
                "community_url": post.get("community_url", ""),
                "post_id": post_id,
                "comment_id": cid,
                "parent_id": post_id,
                "source_type": "comment",
                "text": c,
                "url": f"https://mock.local/j5/posts/{post_id}?comment={j}",
                "date": base,
                "author_pseudonym": f"USER_{hashlib.md5(f'{cid}_author'.encode()).hexdigest()[:8]}",
                "content_hash": hashlib.md5(c.encode("utf-8")).hexdigest(),
            }

    def iter_replies(self, comment: Dict) -> Iterable[Dict]:
        yield from []

    def check_access(self) -> None:
        return None

    def close(self) -> None:
        pass