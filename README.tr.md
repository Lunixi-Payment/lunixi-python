<p align="center"><img src=".github/assets/lunixi-logo.svg" alt="Lunixi" width="220"></p>

# Lunixi Python SDK

**0.2.0**, mevcut fraud API'sini koruyarak ödeme API'leri ve kalıcı checkout akışı ekler. SDK senkron çalışır, istemci başına thread güvenlidir ve `py.typed` içerir. Python 3.9+; gerçek Django 6.1.2, FastAPI 0.162.0, Flask 3.1.3 örnekleri/testleri Python 3.12+ gerektirir. Kriptografi `cryptography`, JavaScript sayı yazımı `rfc8785`, HTTP/SQLite standart kütüphane üzerinden sağlanır.

[English](README.md) · [Framework rehberi](docs/FRAMEWORKS.tr.md) · [Django](docs/DJANGO.tr.md) · [FastAPI](docs/FASTAPI.tr.md) · [Flask](docs/FLASK.tr.md)

## Kurulum ve ödeme

GitHub kaynak etiketi, PyPI yayını yapıldığı anlamına gelmez:

```sh
pip install "lunixi-sdk @ git+https://github.com/Lunixi-Payment/lunixi-python.git@v0.2.0"
```

```python
import os
from lunixi import LunixiClient, CreateIntent
client = LunixiClient(
    base_url="https://api-gateway.lunixi.com",
    key_id=os.environ["LUNIXI_KEY_ID"],
    private_key=os.environ["LUNIXI_PRIVATE_KEY"],
    max_retries=0,
)
intent = client.payments().create_intent(
    CreateIntent(1990, "TRY", "kalici-siparis-123",
                 callback_url="https://magaza.example/return/123"),
    idempotency_key=veritabaninda_saklanan_deneme_anahtari,
)
# Önce kullanıcı/sipariş sahipliği doğrulanmalıdır:
form_config = intent.browser_config()
yonlendirme = intent.hosted_url
```

Tutarlar tam sayı küçük birimdir; float, bool, sıfır ve eski üst düzey tutar alanları ağdan önce reddedilir. `minor_units('19.90','TRY')` tam ondalık dönüşüm yapar; JPY 0, KWD 3, desteklenen diğer para birimleri2 basamaklıdır. `preauth=True` yalnız ön provizyon açar; sipariş ödenmiş sayılmaz. Taksit, uygun yemek kartı/alışveriş kredisi, sigorta ve çoklu kart Lunixi panel/form ayarlarıyla yönetilir. Örnekler kart numarası/CVV toplamaz.

`payments()` yardımcıları: `create_intent`, `get`, `list`, `capture`, `refund`, `void`, `methods`, `get_split`, `list_splits`, `refund_split`. Finansal işlemler kalıcı `idempotency_key` ister. Intent dışındaki yanıtlar tüm gateway zarfını korur; `details`, `pageInfo`, request ID kaybolmaz. API'de intent yanıtı `paymentId`/`token`, ödeme sorgusu `data.id`, webhook `data.intentId` kullanır. Yalnız HTTP 2xx finansal kesinlik değildir.

## Kalıcı sipariş akışı

`lunixi.commerce.CheckoutService`, merchant/sipariş/tutar/para birimi izini ve sabit deneme anahtarını ağ çağrısından **önce** kaydeder. Tarayıcı token'ını bağımsız32 bayt anahtarla şifreler. Native callback, güncel sipariş tutarını/teslim blokesini denetleyip **aynı bağlantı ve transaction** içinde sipariş, stok ve bildirim kuyruğunu güncellemelidir. [Çalışan framework örnekleri](docs/FRAMEWORKS.tr.md) bunu gerçek veritabanlarıyla uygular.

`service.webhook(raw, headers, secret, apply_native)` ham gövde v2 HMAC, zaman ve imzalı id/type kontrolünden sonra kimlik doğrulamalı ödeme/çoklu kart sorgusunu değerlendirir. Kalıcı olay tüketimi ile sipariş değişikliği birlikte commit/rollback olur; eşzamanlı/tekrarlanan olay stoktan iki kez düşmez. Tarayıcı dönüşü/query parametresi/form olayı ödeme kanıtı değildir. Kayıp intent yanıtı yalnız imzalı webhook ve özgün rezervasyon izini doğrulayan GET ile toparlanır; bağlı ödeme kimliği değiştirilmez.

Kısmi tahsilat veya eksik çoklu kart üst ödemesi teslimi başlatmaz. Vade farkı sipariş iziyle kanıtlanıp sepetten ayrı tutulur. Yerel fraud/manual teslim blokesi korunur. Sonradan tutarı/para birimi değişen sipariş eski ödeme ile tamamlanamaz. `FAILED` sonucu kesinlik kanıtı taşımıyorsa incelemede kalır; belirsiz deneme otomatik sıfırlanmaz.

`service.mutate(order_key, kalici_islem_id, action, amount, apply_native)` ile tahsilat/iade/iptal yürütülür. `operation_status(...)` sonucundaki `pending`/`uncertain` başarı değildir; istenen bakiye hareketi GET ile doğrulanınca `confirmed` olur. Önceki işlem çözülmeden farklı kimlik açılamaz. İade gerçekten tahsil edileni aşamaz.23 saati aşan teyitsiz create/mutation tekrarları gateway anahtar saklama süresi nedeniyle engellenir; GET uzlaştırma açık kalır. Zaman aşımında aynı kimlik ve tutarı kullanın.

## Güvenlik ve mevcut fraud yüzeyi

İstemciyi origin/merchant key başına bir kez kurup paylaşın. Varsayılan cache eşzamanlı token yenilemeyi birleştirir; özel `TokenStore` origin/key'e göre ayrılmalıdır. PKCS8 PEM/DER, base64/hex seed ve doğrulanan64 bayt seed/public anahtar biçimleri desteklenir. Özel anahtar config çıktısına yazılmaz. HTTPS zorunludur; origin kullanıcı bilgisi/path/query/fragment içeremez, API yolları kaçamaz, yönlendirmeler takip edilmez. Yanıt boyutu/süre/tekrar sınırları vardır; yalnız sabit anahtarlı finansal istek yeniden gönderilebilir. Gövde JavaScript anahtar/sayı yazımıyla imzalanır.

`fraud().evaluate`, decision log liste/get ve event record/batch yöntemleri korunur. Karar/log Bearer, olay alımı istek başına Ed25519 imzası kullanır.500 olay sınırı ve kısmi batch hataları korunur; hata kayıtlarını aynı event ID ile tekrar gönderin. Generic `client.api().request(..., step_up=True)` diğer belgelenmiş merchant servislerine erişebilir; bu sürüm KYC/identity/sanction/wallet/insurance/bank-connect/subscription/direct-card/split-initiation için tipli akış iddiasında bulunmaz.

Hatalarda sınıf, kod, HTTP durum, request ID ve kota bilgisi kullanılır; uzak hata gövdesi/mesajı ve transport metni saklanır. Ham başarılı yanıtlarda da token/müşteri verisi bulunabilir, loglamayın. Düşük seviye webhook doğrulayıcısı tek başına replay tüketmez; native transaction gerekir. Eski imzasız header alanı fallback'i yalnız açık `allow_legacy_header_fields=True` ile finansal olmayan eski kullanım içindir; sipariş akışında kabul edilmez. `tolerance_seconds=None` yalnız çevrimdışı test seçeneğidir. Secret listesi rotasyona izin verir.

## Test ve dağıtım

```sh
pip install -r requirements-dev.lock
pip install --no-deps -e .
ruff check src integrations tests
ruff format --check src integrations tests
mypy src/lunixi
bandit -r src/lunixi integrations -q
pip-audit
pytest -q
python -m build
```

Kilitli ortam Python 3.12 içindir. Testler gerçek framework kullanıcı/CSRF/ORM/istemcilerini ve veritabanını kullanır; dış gateway sentetiktir. HTTPS testi yalnız loopback üzerinde dinler. Canlı tahsilat, dış e-posta veya otomatik sevkiyat yapılmaz. Wheel SDK'yı; sdist/kaynak çalışan uygulamaları, testleri, özgün logoları ve EN/TR belgeleri içerir. [Güvenlik](SECURITY.md), [katkı](CONTRIBUTING.md) ve [değişiklikler](CHANGELOG.md). MIT.
