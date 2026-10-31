# Çalışan framework entegrasyonları

Bunlar ayrı paket kayıtları değil, aynı SDK/Commerce çekirdeğini kullanan tam kaynak uygulamalardır. Doğrulanan hedefler Python 3.12 üzerinde Django 6.1.2, FastAPI 0.162.0 ve Flask 3.1.3'tür. Gerçek kullanıcı/sipariş/stok/olay tabloları kullanılır. Mevcut mağazada kendi auth/sipariş/teslim modellerine aynı transaction sözleşmesi uygulanmalıdır.

```sh
python 3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.lock
.venv/bin/pip install --no-deps -e .
```

Sunucuda korunan ortam/secret manager üzerinden `LUNIXI_PUBLIC_ORIGIN` (HTTPS uygulama origin'i), `LUNIXI_MERCHANT_ID`, `LUNIXI_KEY_ID`, `LUNIXI_PRIVATE_KEY`, ayrı `LUNIXI_WEBHOOK_SECRET` (16+ karakter), ayrı `LUNIXI_SESSION_SECRET` (32+ karakter), `LUNIXI_ENCRYPTION_KEY` (bağımsız rastgele 32 baytın base64'ü) ve `LUNIXI_DATABASE` (web kökü dışında kalıcı SQLite dosyası) tanımlanır. Veritabanı üst klasörünü operatör oluşturur. Gerçek değerleri Git'e koymayın.

`LUNIXI_CHECKOUT_MODE=hosted|embedded`, `LUNIXI_PREAUTH=true|false`, `LUNIXI_LOCALE=en|tr` seçenekleri vardır. Varsayılan gateway `https://api-gateway.lunixi.com`; alternatif yalnız güvenilen operatör ayarıdır. Bağımsız anahtarlar `secrets.token_urlsafe(48)` ve `base64.b64encode(os.urandom(32)).decode()` ile yerelde üretilebilir. Bir anahtardan diğerini türetmeyin; ayrı yedek alın.

HTTPS/TLS, izinli Host, Secure/HttpOnly/SameSite oturum çerezleri, body/süre sınırları ve korunan loglar gerekir. Lunixi webhook adresi **`<LUNIXI_PUBLIC_ORIGIN>/webhook`** şeklindedir; proxy ham baytları/başlıkları korur.2xx yalnız native commit sonrasında, hatada tekrar edilebilir 503 döner. Tarayıcı token'ı öncesinde oturum/müşteri/sipariş sahipliği ve CSRF doğrulanır. Dönüş POST'u yalnız sahiplik denetimli GET'e yönlendirir; ödeme kanıtı değildir.

SQLite kalıcı dosyada WAL/FULL/BEGIN IMMEDIATE, Django gerçek auth/CSRF/migration ve `transaction.atomic(durable=True)` kullanır. Django SQLite `transaction_mode=IMMEDIATE` ayarı eşzamanlılık garantisi için korunmalıdır. Olay kutusu ve sipariş/stok/bildirim kuyruğu aynı bağlantı/transaction içindedir.

Tahsilat/iade/iptal yalnız sunucu operatörü CLI'sinden kalıcı işlem kimliğiyle yapılır; müşteri HTTP uçlarından yapamaz. Bekleyen/belirsiz sonuç başarı değildir; aynı kimlik/tutar izlenir, yeni işlem engellenir.23 saati aşan teyitsiz tekrar engellenir, GET uzlaştırma kalır. Kesinliği belirsiz FAILED, eksik çoklu kart, kısmi tahsilat ve native teslim blokesi otomatik sevkiyata dönüşmez. Sonradan değişen sipariş eski ödeme ile tamamlanamaz.

Native outbox commit sonrası bildirim kuyruğudur; mevcut uygulamanın gönderim işçisi bu kuyruğa bağlanmalıdır. Örnekler dış e-posta/sevkiyat sağlayıcısı çağırmaz. Veritabanı, olay/işlem kimlikleri, sunucu anahtarı ve eski credential'lar iade/uzlaştırma süresince saklanır; silme/reset HTTP ucu yoktur. Arayüz en/tr, özgün logo ve CSP nonce kullanır; ödeme yöntemleri Lunixi panelinden gelir. Kart numarası/CVV sunucuda toplanmaz.

`pytest -q tests/frameworks` gerçek framework kullanıcı/CSRF/cookie/ORM/istemci ve veritabanlarını sınar; gateway sentetiktir. Tüm testler için `pytest -q`, kalite/güvenlik için Ruff, Mypy, Bandit ve pip-audit çalıştırılır. Canlı tahsilat, Marketplace veya bütün tema uyumu iddiası yoktur. [Django](DJANGO.tr.md), [FastAPI](FASTAPI.tr.md), [Flask](FLASK.tr.md), [English](FRAMEWORKS.md).

## Sağlayıcı tarayıcı dönüşü

Lunixi yönlendirmeli, çoklu kart ve 3DS akışları `/return/<sipariş-anahtarı>` adresine POST gönderir. Siteler arası POST, SameSite=Lax çerezini taşımayabilir. Bu bilgilendirici uç gövdenin tamamını yok sayıp oturum, sipariş, veritabanı veya gateway'e erişmeden aynı göreli `/return/<sipariş-anahtarı>` GET adresine **303** döner. Sonraki GET, normal müşteri sahipliğini ve kimlik doğrulamalı ödeme sorgusunu uygulayıp korumalı checkout sayfasına geçer. Gönderilen durum, ödeme kimliği ve yönlendirme URL'si yetki sağlamaz.

Dönüş POST'u bildirilen gövdede **64 KiB** sınırı uygular; HTTPS proxy'de chunked istekler dahil aynı ağ sınırını koyun. İmzalı webhook'un ayrı 1 MiB sınırı korunur. Yalnız bilgilendirici dönüş ve imzalı webhook checkout CSRF kontrolü dışındadır; finansal müşteri istekleri CSRF ve sahiplik ister. Gerçek WSGI/Uvicorn HTTP testleri oturumsuz303, sahte alanların yok sayılması ve bu aşamada sıfır veritabanı/gateway erişimini doğrular.
