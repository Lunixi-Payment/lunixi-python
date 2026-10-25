# Lunixi Python SDK

Lunixi platformu için Python istemcisi. Paylaşılan çekirdeği — Ed25519 istek
imzalama, jeton alışverişi, yanıt zarfının çözümü, imleçli sayfalama ve tipli
hata ailesi — ve bunun üzerinde fraud karar ve olay API'sini taşır.

English: [README.md](README.md)

- **Gereksinim:** Python 3.9 veya üzeri
- **Bağımlılık:** Ed25519 için
  [`cryptography`](https://pypi.org/project/cryptography/). HTTP standart
  kütüphaneyle yapılır, başka bir paket gelmez.
- **Tipli:** `py.typed` içerir; tüm açık arayüz tip ipuçlarıyla gelir.
- **Lisans:** MIT

```bash
pip install lunixi-sdk
```

## Hızlı başlangıç

```python
from lunixi import Channel, Decision, LunixiClient

client = LunixiClient(
    base_url="https://api.lunixi.com",
    key_id="kid_...",                     # panelden alırsınız
    private_key=private_key_pem,          # sır kasanızdan okuyun
)

decision = client.fraud().evaluate(
    channel=Channel.STANDALONE_API,
    transaction_ref="order-2026-0001",
    payment={"amount": "149.90", "currency": "TRY"},
    customer={"id": "cus_88", "email": "alici@example.com"},
)

if decision.blocked:
    siparisi_reddet(decision.reasons)
elif decision.requires_three_d:
    uc_d_ile_tekrar_dene()
elif decision.requires_review:
    incelemeye_al(decision.trace_id)
else:
    yetkilendir()
```

İstemciyi uygulama açılışında bir kez kurup paylaşın: erişim jetonu önbelleği
bu nesnede durur, dolayısıyla her istek için yeni bir istemci kurmak her istek
için yeni bir jeton alışverişi anlamına gelir.

## Kimlik doğrulama

İki düzey vardır ve birbirinin yerine geçmezler.

**Jeton alışverişi.** `POST /api/v1/auth/token` Ed25519 özel anahtarınızla
imzalanır ve kısa ömürlü bir erişim jetonu döndürür. SDK bunu sizin yerinize
yapar, jetonu önbelleğe alır ve gateway jetonun süresi dolduğunu bildirdiğinde
bir kez yeniler.

**İstek başına imza.** Olay alım uçları her çağrıda imza ister: olayı
hesabınıza bağlayan şey imzadır, bu yüzden gövdedeki bir değer başka bir
hesabı iddia edemez. SDK imzayı gereken yerde ekler.

İmzalanan kanonik dizge şudur:

```text
<METHOD>\n<URL>\nX-Date:<değer>\nX-Nonce:<değer>[\nDigest:<değer>]
```

`<URL>`, gönderildiği hâliyle yoldur: **`/api/v1` öneki ve varsa sorgu dizgesi
dahil**. `Digest` satırı yalnız gövde varken eklenir.

### Anahtar yönetimi

Anahtar çiftini kendiniz üretip yalnız açık anahtarı yükleyebilirsiniz; böylece
özel anahtar sizin sistemlerinizin dışına hiç çıkmaz:

```python
from lunixi import generate_key_pair

private_pem, public_pem = generate_key_pair()
# private_pem'i sır kasanıza koyun; public_pem'i panelden yükleyin
```

Kabul edilen özel anahtar biçimleri: PKCS#8 PEM bloğu (önerilen), base64 veya
hex PKCS#8 DER, ya da çıplak 32 baytlık tohum. Anahtarı sır kasanızdan okuyun;
kaynak koda ve depodaki bir dosyaya koymayın.

## Fraud

Müşteriye açık yüzey **beş uçtan** oluşur:

| Çağrı | Uç |
|---|---|
| `fraud().evaluate(...)` | `POST /api/v1/fraud/decisions/evaluate` |
| `fraud().decisions.list(...)` | `GET /api/v1/fraud/decision-logs` |
| `fraud().decisions.get(trace_id)` | `GET /api/v1/fraud/decision-logs/{traceId}` |
| `fraud().events.record(event)` | `POST /api/v1/fraud/events/transactions` |
| `fraud().events.record_batch(events)` | `POST .../events/transactions/batch` |

Panelin kendi uçları bu yüzeyin parçası değildir. Kararlılık güvencesi
taşımadıkları için burada yayımlanmazlar.

### Karar sonuçları

`allow`, `review`, `block`, `force_3d`. Dikkat: `allowed`, `blocked`'ın tersi
**değildir**. `review` ve `force_3d` ikisi de değildir; `force_3d` ödemeyi
reddetmez, 3-D Secure ile yeniden denemenizi ister.

Alan adları Python'un `snake_case` biçimindedir; API referansındaki
`camelCase` yazım da takma ad olarak kabul edilir. Tanınmayan bir alan yerelde
hata verir ve hangi anahtarın yanlış olduğunu söyler; bunu öğrenmek için bir
gidiş-dönüş harcamanız gerekmez.

`tenant_id` bilinçli olarak yoktur: kiracı erişim jetonunuzdan damgalanır ve
gövdedeki değer yok sayılır.

### Olay alımı

Olaylar, sayma kurallarının okuduğu geçmişi oluşturur.

```python
result = client.fraud().events.record(
    {
        "eventId": "evt-0001",          # sizin kimliğiniz; aynı kimlikle tekrar güvenlidir
        "eventType": "card_sale",
        "subjectType": "customer",
        "occurredAt": "2026-10-11T08:29:00Z",
    },
    idempotency_key="evt-0001",
)
if result.deduplicated:
    ...  # bu olay zaten kaydedilmişti
```

Bir parti en çok **500** olay taşır; SDK daha büyüğünü ağa çıkmadan reddeder,
çünkü gateway partinin tamamını geri çevirir.

**Parti kısmen başarılı olabilir.** Bir olay doğrulamadan geçmediğinde uç
`200` yanıtlar ve kalan olayları işlemeye devam eder; yani durum kodu tek
başına partinin yerine oturduğunu kanıtlamaz:

```python
result = client.fraud().events.record_batch(events, idempotency_key="feed-2026-10-11-01")
for failure in result.failures():
    log.warning("olay %s reddedildi: %s", failure.event_id, failure.error)
```

Gövdeyi düzeltip reddedilen olayı **aynı** `eventId` ile tekrar gönderin:
gateway tekrarı ayıkladığı için, yerine oturmuş bir olay ikinci kez sayılmaz.

## Yanıtı okumak

Başarılı her yanıt sarmalanır:

```json
{ "status": "success", "code": "SUCCESS", "data": {}, "pageInfo": {}, "requestId": "..." }
```

Zarfı kendiniz okuyacaksanız iki noktayı bilmeniz gerekir:

- **`success` alanı yoktur.** Sonuç `status` alanında, `"success"` dizgesi
  olarak gelir. `response["success"]` okuyan kod her yanıtta `None` görür.
  `lunixi.is_success(response)` kullanın.
- **`pageInfo`, `data`'nın kardeşidir**, içinde değil. Liste uçları `data`'yı
  çıplak dizi olarak döndürür, dolayısıyla sayfalama bilgisi onun içinde
  duramaz.

Özellik istemcileri bu ikisini sizin yerinize halleder.

## Sayfalama

```python
page = client.fraud().decisions.list(decision=Decision.REVIEW, limit=50)
while True:
    for row in page.items:
        isle(row)
    if not page.has_more or not page.next_cursor:
        break
    page = client.fraud().decisions.list(
        decision=Decision.REVIEW, limit=50, cursor=page.next_cursor
    )
```

Ya da imleçleri SDK'ya takip ettirin:

```python
for row in client.fraud().decisions.iterate(decision=Decision.REVIEW, limit=50):
    isle(row)
```

İmleç opaktır: aynen geri gönderin. Çözmeyin, üretmeyin, değiştirmeyin —
bozuk imleç `400` ile reddedilir, sessizce ilk sayfaya dönmez. `total_count`,
sunucu gerçekten saymadıkça `None`'dır; filtreli sayım pahalıdır.

## Hatalar

Tüm hatalar `LunixiError`'dan türer.

| Sınıf | Ne zaman |
|---|---|
| `ConfigurationError` | Yerel bir değer kullanılamaz; hiçbir şey gönderilmedi. |
| `SignatureError` | Özel anahtar yüklenemedi. |
| `ValidationError` | `400` — gateway gövdeyi reddetti. |
| `AuthenticationError` | `401` / `403` — imza, jeton veya yetki reddedildi. |
| `RateLimitError` | `429` — `retry_after` ve `quota` taşır. |
| `ServiceUnavailableError` | `503` — `retry_after` taşır. |
| `ApiError` | Diğer 2xx olmayan yanıtlar ya da hiç yanıt gelmemesi. |
| `WebhookVerificationError` | Gelen webhook doğrulanmadı. |

Gateway başlığı göndermediğinde `retry_after` ve kota alanları `None` olur.
Gateway tahmin etmek yerine başlığı atlar; bu SDK da öyle yapar — uydurulmuş
bir sayı yanlış hızda yeniden denemenize yol açardı.

```python
from lunixi import RateLimitError

try:
    client.fraud().events.record(event, idempotency_key=event["eventId"])
except RateLimitError as error:
    sleep(error.retry_after or 30)
```

### Yeniden denemeler

`GET` istekleri ve `idempotency_key` verdiğiniz her istek, taşıma hatası veya
`5xx` sonrası yeniden denenir. Diğerleri denenmez: SDK kayıp isteği kayıp
yanıttan ayırt edemez ve anahtarsız bir yazmayı tekrarlamak aynı olayı iki kez
kaydedebilir.

`evaluate` kendiliğinden yeniden denenmez. Ödeme akışınızın içinde koştuğu
için, zaman aşımına uğrayan bir kararın yeniden denenmesi mi, yumuşak geçiş
sayılması mı, yoksa bekletilmesi mi gerektiği sizin kararınızdır.

## Webhook'lar

```python
from lunixi import FraudEvents, WebhookVerifier, WebhookVerificationError

verifier = WebhookVerifier(endpoint_secret)

try:
    event = verifier.verify(raw_body, request.headers)
except WebhookVerificationError:
    return 400                     # doğrulanmamış yük üzerinde asla işlem yapmayın

if event.type == FraudEvents.FLOW_ASYNC_COMPLETED:
    ...
```

**Ham gövdeyi verin.** İmza, gelen baytların tam olarak kendisini kapsar;
JSON'u çözüp yeniden üretmek anahtar sırasını ve boşlukları değiştirir ve o
andan sonra her webhook doğrulamadan geçemez. Ham gövdeyi, herhangi bir JSON
ara katmanı ona dokunmadan önce yakalayın.

Doğrulama fail-closed çalışır ve varsayılan olarak 300 saniyelik pencerede
zaman damgası tazeliğini de denetler. Sır değişimi sırasında gateway iki imza
öğesi gönderir; birinin doğrulanması yeterlidir, böylece sırları değiştirirken
ucunuz çalışmaya devam eder.

Yedi fraud olay tipi `FraudEvents` içindedir; `FRAUD_EVENT_TYPES` hepsini
tutar.

## Genişletme

Bu sürümün sarmaladığı uçların dışındaki her gateway ucuna, imzalama,
yeniden deneme ve hata işleme hazırken erişebilirsiniz:

```python
envelope = client.api().request(
    "GET", "/api/v1/some/other/route", query={"limit": 25}
)
rows = lunixi.items_of(envelope)
```

Kendi HTTP yığınınızı (bağlantı havuzu, vekil sunucu veya izleme için)
`HttpTransport` arayüzünü uygulayıp `transport=` ile verebilirsiniz. Çok
süreçli bir kurulumda `TokenStore` arayüzünü paylaşılan bir önbellek üzerinde
uygulayıp `token_store=` ile verin; böylece süreçler tek jetonu paylaşır.

## Geliştirme

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

Süit tamamen çevrimdışı koşar: enjekte edilen bir taşıma katmanı üzerinden
SDK'nın tele ne koyduğunu ölçer, imzalama ve webhook mantığını depodaki
vektörlere karşı doğrular. İçindeki her anahtar sentetiktir ve hiçbir yere
erişim vermez.

## Örnekler

Koşturulabilir örnekler [`samples/`](samples/) altındadır. Her biri
ayarlarını ortam değişkenlerinden okur; böylece hiçbir kimlik bilgisi dosyaya
yazılmaz.
