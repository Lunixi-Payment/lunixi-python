# Django entegrasyonu

Önce [sunucu kurulumu ve temel kurallar](FRAMEWORKS.tr.md) okunmalıdır. Bu, gerçek native testleri olan çalışan kaynak uygulamadır; ayrı paket kaydı iddiası yoktur. `LUNIXI_PUBLIC_ORIGIN` aşağıdaki HTTPS origin/port ile eşleşmelidir. TLS dosyaları operatör tarafından sağlanır; repoda sertifika/özel anahtar yoktur.

```sh
python -m integrations.django_app.manage migrate
python -m integrations.django_app.manage createsuperuser
python -m integrations.django_app.manage seed_checkout --username YOUR_USER --amount 19.90 --currency TRY
uvicorn integrations.django_app.asgi:application --host 127.0.0.1 --port 8000 --ssl-keyfile /secure/tls/key.pem --ssl-certfile /secure/tls/cert.pem
```

Üretilen sipariş adresini açıp yerel Django giriş formuyla oturum açın. Sipariş gerçek auth kullanıcısına aittir; checkout native CSRF middleware ile korunur. Yalnız bilgilendirici dönüş ve imzalı webhook uçları CSRF dışında tutulur.

Sunucu uzlaştırma görevi her dakika çalıştırılır. Finansal operatör komutu mevcut kalıcı işlem kimliğini kullanır; pending/uncertain başarı değildir, aynı kimlik/tutarla takip edilir.

```sh
python -m integrations.django_app.manage lunixi_reconcile
python -m integrations.django_app.manage lunixi_operation refund --order-id ORDER_ID --operation-id PERSISTED_REFUND_ID --amount 1.00
```

`/webhook` ham gövdeyi, v2 HMAC/imzalı kimliği ve GET ödeme kanıtını doğrulayıp native sipariş/stok/olay/bildirim kuyruğunu atomik günceller. Tarayıcı dönüşü ödeme kesinleştirmez. Native teslim blokesi ve değişmiş sipariş izi korunur.23 saati aşan teyitsiz finansal POST tekrarı engellenir; GET açıktır. Bildirim kuyruğu mevcut uygulamanın commit sonrası gönderim işçisine aittir; örnek dış e-posta/sevkiyat başlatmaz.

Test: `pytest -q tests/frameworks`; tüm SDK/güvenlik: `pytest -q`. [English](DJANGO.md), [SDK](../README.tr.md), [güvenlik](../SECURITY.md).

## Sağlayıcı tarayıcı dönüşü

Lunixi yönlendirmeli, çoklu kart ve 3DS akışları `/return/<sipariş-anahtarı>` adresine POST gönderir. Siteler arası POST, SameSite=Lax çerezini taşımayabilir. Bu bilgilendirici uç gövdenin tamamını yok sayıp oturum, sipariş, veritabanı veya gateway'e erişmeden aynı göreli `/return/<sipariş-anahtarı>` GET adresine **303** döner. Sonraki GET, normal müşteri sahipliğini ve kimlik doğrulamalı ödeme sorgusunu uygulayıp korumalı checkout sayfasına geçer. Gönderilen durum, ödeme kimliği ve yönlendirme URL'si yetki sağlamaz.

Dönüş POST'u bildirilen gövdede **64 KiB** sınırı uygular; HTTPS proxy'de chunked istekler dahil aynı ağ sınırını koyun. İmzalı webhook'un ayrı 1 MiB sınırı korunur. Yalnız bilgilendirici dönüş ve imzalı webhook checkout CSRF kontrolü dışındadır; finansal müşteri istekleri CSRF ve sahiplik ister. Gerçek WSGI/Uvicorn HTTP testleri oturumsuz303, sahte alanların yok sayılması ve bu aşamada sıfır veritabanı/gateway erişimini doğrular.

Checkout sayfasının CSP’si form POST’u için yalnız `'self'` ve yapılandırılan gateway origin’ine (varsayılan `https://api-gateway.lunixi.com`) izin verir. Böylece tarayıcı SDK’sının desteklediği cüzdan/sağlayıcı ve eski POST geçişleri korunur. İncelenmiş başka bir sağlayıcı gerekiyorsa yalnız sunucuda `LUNIXI_FORM_ACTION_ORIGINS` tanımlayın: virgülle ayrılmış tam HTTPS origin’leri; boşluk, yol, sondaki slash, kullanıcı bilgisi, sorgu, fragment ve wildcard kabul edilmez. Geçersiz ayar reddedilir; gateway yanıtı veya tarayıcı alanı listeyi genişletemez. Script nonce, frame/connect sınırları ve bilgilendirici dönüş güvenliği korunur.
