<p align="center"><img src=".github/assets/lunixi-logo.svg" alt="Lunixi" width="220"></p>

# Lunixi Python SDK

**1.0.2**, mevcut fraud ve kalıcı checkout akışlarını koruyarak para alanlarını kanonik küçük birim string sözleşmesine geçirir. [Geçiş rehberini](MIGRATION-1.0.md) uygulayın. SDK senkron çalışır, istemci başına thread güvenlidir ve `py.typed` içerir. Python 3.9+; gerçek Django 6.1.2, FastAPI 0.162.0, Flask 3.1.3 örnekleri/testleri Python 3.12+ gerektirir. Kriptografi `cryptography`, JavaScript sayı yazımı `rfc8785`, HTTP/SQLite standart kütüphane üzerinden sağlanır.

[English](README.md) · [Framework rehberi](docs/FRAMEWORKS.tr.md) · [Django](docs/DJANGO.tr.md) · [FastAPI](docs/FASTAPI.tr.md) · [Flask](docs/FLASK.tr.md)

## Kurulum ve ödeme

PyPI üzerinde yayımlanan 1.0.2 sürümünü aşağıdaki komutla kurun. 0.x paketleri önceki para sözleşmesini kullanır:

```sh
pip install lunixi-sdk==1.0.2
```

Alternatif olarak aynı kaynak etiketini GitHub’dan kurabilirsiniz:

```sh
pip install "lunixi-sdk @ git+https://github.com/Lunixi-Payment/lunixi-python.git@v1.0.2"
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
    CreateIntent("1990", "TRY", "kalici-siparis-123",
                 callback_url="https://magaza.example/return/123",
                 enabled_installments=[1, 2, 3]),  # isteğe bağlı: en fazla 3 taksit
    idempotency_key=veritabaninda_saklanan_deneme_anahtari,
)
# Önce kullanıcı/sipariş sahipliği doğrulanmalıdır:
form_config = intent.browser_config()
yonlendirme = intent.hosted_url
```

Tutarlar kanonik küçük birim string değerleridir (`"1990"` = 19,90 TRY); sayısal JSON, float, bool, sıfır ve eski üst düzey tutar alanları ağdan önce reddedilir. `minor_units('19.90','TRY')` ondalık metni para biriminin basamak sayısıyla tam olarak dönüştürür; JPY 0, TRY 2, KWD 3 basamak kullanır. Fiat tutar üst sınırı `"9223372036854775807"` değeridir; sağlayıcı sınırı daha düşük olabilir. `preauth=True` yalnız ön provizyon açar; sipariş ödenmiş sayılmaz. Taksit, uygun yemek kartı/alışveriş kredisi, sigorta ve çoklu kart Lunixi panel/form ayarlarıyla yönetilir. `enabled_installments` bir ödeme için formun sunacağı taksit sayılarını yalnızca daraltır (`[1]` = yalnız tek çekim); form, panel ayarlarınızın, kartın ve platform üst sınırının da izin verdiği sayıları gösterir, `None` kısıt yok demektir. Sayılar 1–36 arası tamsayı, tekrarsız olmalı ve 1'i içermelidir; aksi hâlde istekten önce `ConfigurationError` oluşur. Liste `enabledInstallments` olarak artan sırada gönderilir. Örnekler kart numarası/CVV toplamaz.

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

## Varsayılan gömülü form ve isteğe bağlı backend ödeme sayfası

Framework örneklerinde varsayılan `LUNIXI_CHECKOUT_MODE=embedded` değeridir. Mevcut form yalnız `https://cdn.lunixi.com/lunixi-checkout.min.js` ve resmi object/token/mount API'siyle mağaza içinde açılır. Açıkça seçilen `hosted` modu da korunur. `IntentResult.payment_page_url`, backend'in isteğe bağlı `paymentPageUrl` alanını alır; `hosted_url` doğrulayıp bu adresi birebir döndürür. Sayfanın opak token'ı gömülü form token'ından farklı olabilir. Eksik/geçersiz adreste yönlendirme durur; tarayıcı token'ından adres üretilmez.

İki mod aynı formu kullanır; açık yöntemler, çoklu kart, taksit ve sigorta yönlendirme gerektirmez. Token ve sayfa adresi ayrı authenticated bağlamlarla şifrelenir. Kayıtlı dönüş adresi/mod/gövde/hash/anahtar değişmez; ayar değişikliği yeni tahsilat başlatamaz. Eski yönlendirmeli denemede backend adresi yoksa mutabakat gerekir. Ham webhook, sahiplik/oturum/CSRF, doğrulanmış tahsilat ve bilgilendirici 3DS/çoklu kart dönüşleri korunur.

Geçmiş 0.2.1 kaynak sürümü için 27 odaklı SDK/native Django/FastAPI/Flask kontrolü geçti; önceki tam 0.2.0 doğrulaması temel kanıt olarak korunur. Canlı tahsilat veya yeni geniş merchant kabulü yapılmadı.
