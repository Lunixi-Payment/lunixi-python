# FastAPI entegrasyonu

Önce [sunucu kurulumu ve temel kurallar](FRAMEWORKS.tr.md) okunmalıdır. Bu, gerçek native testleri olan çalışan kaynak uygulamadır; ayrı paket kaydı iddiası yoktur. `LUNIXI_PUBLIC_ORIGIN` aşağıdaki HTTPS origin/port ile eşleşmelidir. TLS dosyaları operatör tarafından sağlanır; repoda sertifika/özel anahtar yoktur.

**[SDK 0.2.1 PyPI’da yayımlandı](https://pypi.org/project/lunixi-sdk/0.2.1/)**; mevcut uygulamanıza `pip install lunixi-sdk==0.2.1` ile kurabilirsiniz. Bu örnek uygulama için [v0.2.1 kaynak etiketini](https://github.com/Lunixi-Payment/lunixi-python/tree/v0.2.1) ve ortak kurulumdaki kilitli ortamı kullanın; ayrı bir framework paketi yayımlanmamıştır.

```sh
python -m integrations.cli init
python -m integrations.cli seed --customer-id TRUSTED_CUSTOMER_ID --amount 19.90 --currency TRY
uvicorn --factory integrations.fastapi_app:create_app --host 127.0.0.1 --port 8000 --ssl-keyfile /secure/tls/key.pem --ssl-certfile /secure/tls/cert.pem
```

Sunucu CLI 15 dakikalık tek kullanımlık ödeme daveti üretir. Yalnız ilgili müşteriye verin; davet atomik tüketilip imzalı Secure/HttpOnly/SameSite oturumuna dönüştürülür. Kullanıcıya müşteri ID/tutar seçtiren HTTP ucu yoktur. Davet yollarını access loglarında maskeleyin. Checkout POST oturum CSRF başlığı ve kalıcı sahiplik kontrolü ister.

Sunucu uzlaştırma görevi her dakika çalıştırılır. Finansal operatör komutu mevcut kalıcı işlem kimliğini kullanır; pending/uncertain başarı değildir, aynı kimlik/tutarla takip edilir.

```sh
python -m integrations.cli reconcile --limit 100
python -m integrations.cli operation refund --order-id ORDER_ID --operation-id PERSISTED_REFUND_ID --amount 1.00
```

`/webhook` ham gövdeyi, v2 HMAC/imzalı kimliği ve GET ödeme kanıtını doğrulayıp native sipariş/stok/olay/bildirim kuyruğunu atomik günceller. Tarayıcı dönüşü ödeme kesinleştirmez. Native teslim blokesi ve değişmiş sipariş izi korunur.23 saati aşan teyitsiz finansal POST tekrarı engellenir; GET açıktır. Bildirim kuyruğu mevcut uygulamanın commit sonrası gönderim işçisine aittir; örnek dış e-posta/sevkiyat başlatmaz.

Test: `pytest -q tests/frameworks`; tüm SDK/güvenlik: `pytest -q`. [English](FASTAPI.md), [SDK](../README.tr.md), [güvenlik](../SECURITY.md).

## Sağlayıcı tarayıcı dönüşü

Lunixi yönlendirmeli, çoklu kart ve 3DS akışları `/return/<sipariş-anahtarı>` adresine POST gönderir. Siteler arası POST, SameSite=Lax çerezini taşımayabilir. Bu bilgilendirici uç gövdenin tamamını yok sayıp oturum, sipariş, veritabanı veya gateway'e erişmeden aynı göreli `/return/<sipariş-anahtarı>` GET adresine **303** döner. Sonraki GET, normal müşteri sahipliğini ve kimlik doğrulamalı ödeme sorgusunu uygulayıp korumalı checkout sayfasına geçer. Gönderilen durum, ödeme kimliği ve yönlendirme URL'si yetki sağlamaz.

Dönüş POST'u bildirilen gövdede **64 KiB** sınırı uygular; HTTPS proxy'de chunked istekler dahil aynı ağ sınırını koyun. İmzalı webhook'un ayrı 1 MiB sınırı korunur. Yalnız bilgilendirici dönüş ve imzalı webhook checkout CSRF kontrolü dışındadır; finansal müşteri istekleri CSRF ve sahiplik ister. Gerçek WSGI/Uvicorn HTTP testleri oturumsuz303, sahte alanların yok sayılması ve bu aşamada sıfır veritabanı/gateway erişimini doğrular.

Checkout sayfasının CSP’si form POST’u için yalnız `'self'` ve yapılandırılan gateway origin’ine (varsayılan `https://api-gateway.lunixi.com`) izin verir. Böylece tarayıcı SDK’sının desteklediği cüzdan/sağlayıcı ve eski POST geçişleri korunur. İncelenmiş başka bir sağlayıcı gerekiyorsa yalnız sunucuda `LUNIXI_FORM_ACTION_ORIGINS` tanımlayın: virgülle ayrılmış tam HTTPS origin’leri; boşluk, yol, sondaki slash, kullanıcı bilgisi, sorgu, fragment ve wildcard kabul edilmez. Geçersiz ayar reddedilir; gateway yanıtı veya tarayıcı alanı listeyi genişletemez. Script nonce, frame/connect sınırları ve bilgilendirici dönüş güvenliği korunur.
