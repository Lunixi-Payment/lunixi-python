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
# Her ödemenin zorunlu sipariş bilgileri (kendi checkout'unuzdan alın, yer tutucu değil).
order = dict(
    buyer={"name": "Ada", "surname": "Yilmaz", "identityNumber": "11111111111",
           "email": "ada@example.com", "gsmNumber": "+905350000000",
           "city": "Istanbul", "country": "Turkey", "zipCode": "34000"},
    billing_address={"contactName": "Ada Yilmaz", "address": "Example Street 1",
                     "city": "Istanbul", "country": "Turkey", "zipCode": "34000"},
    basket_items=[{"id": "SKU-1", "name": "Hediye kartı", "category1": "Dijital",
                   "itemType": "VIRTUAL", "price": "1990"}],
)
intent = client.payments().create_intent(
    CreateIntent("1990", "TRY", "kalici-siparis-123",
                 callback_url="https://magaza.example/return/123",
                 enabled_installments=[1, 2, 3],  # isteğe bağlı: en fazla 3 taksit
                 **order),
    idempotency_key=veritabaninda_saklanan_deneme_anahtari,
)
# Önce kullanıcı/sipariş sahipliği doğrulanmalıdır:
form_config = intent.browser_config()
yonlendirme = intent.hosted_url
```

Tutarlar kanonik küçük birim string değerleridir (`"1990"` = 19,90 TRY); sayısal JSON, float, bool, sıfır ve eski üst düzey tutar alanları ağdan önce reddedilir. `minor_units('19.90','TRY')` ondalık metni para biriminin basamak sayısıyla tam olarak dönüştürür; JPY 0, TRY 2, KWD 3 basamak kullanır. Fiat tutar üst sınırı `"9223372036854775807"` değeridir; sağlayıcı sınırı daha düşük olabilir. `preauth=True` yalnız ön provizyon açar; sipariş ödenmiş sayılmaz. Taksit, uygun yemek kartı/alışveriş kredisi, sigorta ve çoklu kart Lunixi panel/form ayarlarıyla yönetilir. `enabled_installments` bir ödeme için formun sunacağı taksit sayılarını yalnızca daraltır (`[1]` = yalnız tek çekim); form, panel ayarlarınızın, kartın ve platform üst sınırının da izin verdiği sayıları gösterir, `None` kısıt yok demektir. Sayılar 1–36 arası tamsayı, tekrarsız olmalı ve 1'i içermelidir; aksi hâlde istekten önce `ConfigurationError` oluşur. Liste `enabledInstallments` olarak artan sırada gönderilir. Örnekler kart numarası/CVV toplamaz.

Her ödeme gövdesi sipariş bilgilerini taşır (`lunixi.payments.order_details`): `buyer` (`name`, `surname`, `identityNumber` — T.C. kimlik ya da pasaport numarası, `email` — ASCII, `gsmNumber`, `city`, `country`, `zipCode`, `ip` — alıcının tarayıcı IP'si), `billingAddress` (`contactName`, `address`, `city`, `country`, `zipCode`) ve en az bir `basketItems` kalemi (`id`, `name`, `category1`, `itemType`, `price`; fiyatların toplamı tutara eşittir); `PHYSICAL` kalemde `shippingAddress` de gerekir. `CreateIntent` ve pazaryeri intent'lerinde `ip` gönderilmeyebilir: Lunixi formu IP'yi alıcının tarayıcısından alır. `create_intent`, `create_marketplace_intent`, `direct_method_payment`, `create_split_payment`, pazaryeri kart çekimleri, `store_card` (yalnız alıcı ve fatura adresi) ve cüzdan kartlı yükleme eksik alanların yollarını sayan `ConfigurationError` ile göndermeden durur (`missing_order_details(body)` aynı listeyi döner). Gateway eksik alana 400 `payment.order.field_required`, geçersiz değere `payment.order.field_invalid` döner (`OrderFieldErrorCode`, `OrderFieldReason`).

Sepet kalemleri her satırda isteğe bağlı `productCategory` alanını taşıyabilir: Lunixi ürün kategorisi kodu; yasal taksit sınırı olan ödeme yöntemleri (ör. alışveriş kredisi) ve diğer platform özellikleri tarafından kullanılır. Alanı göndermezseniz mevcut davranış korunur; gateway bilinmeyen kodu 400 ile reddeder. Kodlar `ProductCategory` sabitleri olarak hazırdır (`from lunixi import ProductCategory`; `ProductCategory.MOBILE_PHONE`, 40 kodun tamamı `ProductCategory.ALL` içinde). Liste yalnız sona ekleme ile büyüdüğünden değer düz string olarak kalır ve SDK göndermeden önce denetlemez.

`payments()` yardımcıları: `create_intent`, `get`, `list`, `capture`, `refund`, `void`, `list_payment_methods` / `methods`, `direct_method_payment`, `confirm_payment_action` / `resend_payment_action`, `get_promissory_notes`, `cancel_promissory_notes`, `download_promissory_note_document`, `list_bank_transfer_exceptions`, `accept_bank_transfer_exception`, `mark_bank_transfer_exception_refunded`, `create_split_payment`, `get_split`, `list_splits`, `refund_split`, `create_marketplace_intent`, `bin_info`, `installment_options`, `card_taxonomy`, `store_card`, `deactivate_stored_card`, `list_stored_cards`, `get_stored_card`, `failover_recovery_analytics`, `provider_credential_analytics`. Adres sözlüğü `client.reference()` altındadır: `list_provinces()`, `list_districts(province_code)`, `list_neighborhoods(district_code)`. Finansal işlemler kalıcı `idempotency_key` ister. Intent dışındaki yanıtlar tüm gateway zarfını korur; `details`, `pageInfo`, request ID kaybolmaz. API'de intent yanıtı `paymentId`/`token`, ödeme sorgusu `data.id`, webhook `data.intentId` kullanır. Yalnız HTTP 2xx finansal kesinlik değildir.

## Sunucunuzdan ödeme yöntemleri

`list_payment_methods()` hesabınıza açık yöntemleri, sağlayıcı başına `providerCode` ve gönderilecek `inputFields` alanlarıyla listeler. Sağlayıcı kodunu her zaman bu yanıttan okuyun; kodda sabitlemeyin. `list_payment_methods("MOBILE_BILLING")` listeyi tek yönteme daraltır (`QR`, `QR_CODE` olarak gönderilir; `[A-Z][A-Z0-9_]{0,31}` biçiminde olmayan kod `ConfigurationError` oluşturur).

```python
from lunixi import DirectMethodPaymentRequest, PaymentActionType, PaymentMethod

request = (
    DirectMethodPaymentRequest("15000", "TRY", "persisted-order-123")
    .with_method_fields(PaymentMethod.MOBILE_BILLING, provider_code, {"gsmNumber": "+905321234567"})
    .with_callback_url("https://shop.example/return/123")
)
response = client.payments().direct_method_payment(request, idempotency_key=persisted_attempt_key)
action = response["data"].get("action")
if action and action["type"] == PaymentActionType.OTP:
    client.payments().confirm_payment_action(
        response["data"]["paymentId"], action["id"], otp=code_from_buyer
    )
```

Gövde, yöntemin adını taşıyan tam olarak bir yöntem bloğu içerir (`MOBILE_BILLING` → `mobileBilling`; `METHOD_BLOCK_FIELDS` blokları listeler). SDK hiçbir şey göndermeden önce şunları reddeder: bilinmeyen alan, `price`/`paidPrice`, başka bir yöntemin bloğu, eksik blok, kart dışı yöntemde kart alanları (`CARD_ONLY_FIELDS`), bloğu olmayan yöntem, 1–100 kalem dışındaki alışveriş kredisi sepeti ve gateway'in reddedeceği biçimde bir blok (adları `[A-Za-z][A-Za-z0-9]{0,63}` olan en fazla 32 alan; değerler en fazla 1024 karakterlik string, sayı, boolean, en fazla 16 alanlı `ADDRESS` nesnesi veya en fazla 10 nesnelik `GROUP` listesi olabilir). Builder yerine verilen ham gövde mapping'i aynı kurallarla denetlenir. `idempotency_key` zorunludur. Kart türevi `with_card(card)` ile birlikte `with_force3d(True)` ve `with_installment(count, quote_token)` kullanır.

`confirm_payment_action()` yalnız `otp` (rakamlar, en fazla 16), `consent_accepted` (boolean) ve `fields` gönderir; başka bir anahtar kelime `ConfigurationError` oluşturur. `resend_payment_action()` adımı kapatır ve yenisini açar.

### Para Transferi

`BANK_TRANSFER` sağlayıcı kodu almaz: `None` ve alıcının bankasını `{"bankCode": ...}` olarak verin; listede olmayan bir banka için `BANK_TRANSFER_OTHER_BANKS_CODE` (`"9999"`) kullanın. Yanıt, alıcıya gösterilecek transfer talimatını taşıyan bir `DISPLAY` adımıdır:

```python
from lunixi import BankTransferInstruction

request = DirectMethodPaymentRequest("15000", "TRY", "persisted-order-123").with_method_fields(
    PaymentMethod.BANK_TRANSFER, None, {"bankCode": buyer_bank_code}
)
response = client.payments().direct_method_payment(request, idempotency_key=persisted_attempt_key)
instruction = BankTransferInstruction.from_response(response)  # None without a DISPLAY action
if instruction:
    show(instruction.iban, instruction.holder_name, instruction.amount_minor, instruction.payment_code)
```

Para sizin banka hesabınıza gider ve ödeme koduyla eşleştirilir. Geç, eksik ve fazla gelen transferleri `list_bank_transfer_exceptions(environment="LIVE", status="PENDING_DECISION", limit=50)` ile listeleyin (`limit` 1–200); `accept_bank_transfer_exception(id)` veya `mark_bank_transfer_exception_refunded(id)` ile karara bağlayın (id bir UUID'dir). Sabitler: `PaymentBankTransferExceptionKind`, `PaymentBankTransferExceptionStatus` ve webhook olayları `PaymentBankTransferEvents` (`payment.bank_transfer.*`).

### Senetle Ödeme

Bir `PROMISSORY_NOTE` ödemesi plan taşır: `with_promissory_note_schedule([{"amount": "10000", "dueDate": "2027-01-15"}, ...])` (1–24 satır, toplamı `amount` değerine eşit kanonik küçük birim tutarlar, artan sırada gerçek `YYYY-MM-DD` tarihler) ya da `with_promissory_note_count(6)` (1–24); ikisi birden olmaz. `get_promissory_notes(payment_id)` senetleri döndürür, `cancel_promissory_notes(payment_id, serial_numbers=None)` açık senetlerin tümünü ya da listelenenleri iptal eder, `download_promissory_note_document(payment_id, locale="tr-TR")` ise `content` alanı PDF baytlarını taşıyan bir `BinaryResponse` döndürür (`PromissoryNoteDocumentLocale`: `tr-TR`, `en-GB`). Durum, sonuç ve olay sabitleri: `PromissoryNoteStatus`, `PromissoryNoteCancelResult`, `PromissoryNoteCancelErrorCode`, `PromissoryNoteEvents`. `ADDRESS` alanının kodları `client.reference()` çağrılarından gelir (iller, ilçeler, mahalleler).

### Parçalı ödeme

```python
from lunixi import SplitPaymentRequest

request = (
    SplitPaymentRequest("30000", "TRY", customer_ref)
    .with_order_id("persisted-order-123")
    .add_card_leg(stored_card_token, "20000")
    .add_method_leg(PaymentMethod.WALLET, provider_code, "10000", {})
)
response = client.payments().create_split_payment(request, idempotency_key=persisted_split_key)
```

Idempotency anahtarı (en fazla 200 karakter) parçalı ödemenin kimliğidir: bir adımdan sonra aynı isteği aynı anahtarla gönderin, ödeme sürer. Ödeme sürerken gateway, durumu `code` olarak (`SPLIT_PAYMENT_IN_PROGRESS_STATUSES`) ve `data.splitPaymentId` ile HTTP 400 döndürür; bu yanıt hata olarak fırlatılmaz, döndürülür. Kart dışı bir parça yalnız sağlayıcı koduyla birlikte bir `mobileBilling`, `wallet` veya `promissoryNote` bloğu taşır (`SPLIT_LEG_BLOCK_FIELDS`); yemek kartı, açık bankacılık, alışveriş kredisi ve Para Transferi parça olamaz. `list_splits()` filtrelerini denetler (`status`, `currency`, `createdFrom`, `createdTo`, `orderId`, `ownerRef`, 1–100 arası `limit`, `after`). Webhook sabitleri: `SplitPaymentEvents` ve parça aboneliği anahtarı `SPLIT_LEG_EVENTS_SUBSCRIPTION`.

### Kartlar, taksitler ve pazaryeri intent'leri

`bin_info("54000000")` bir BIN için kart, banka ve taksit uygunluğunu döndürür; `installment_options(InstallmentOptionsRequest("10050", "TRY", bin_or_pan=bin, installment=3, enabled_installments=[1, 2, 3]))` taksit tablosunu ve `installment` > 1 olan bir BIN için `DirectMethodPaymentRequest.with_installment(count, quote_token)` çağrısında kullanılacak bağlayıcı `quoteToken` değerini döndürür. `enabled_installments`, `CreateIntent` ile aynı kuralı izler (1–36 arası, tekrarsız, 1'i içeren tamsayılar). BIN veya kart numarası yalnız rakamlardan oluşur ve hiçbir hata mesajına konmaz. `store_card(StoreCardRequest(card, card_user_key, callback_url), idempotency_key=...)` ve `deactivate_stored_card(token, idempotency_key=...)` imzalıdır ve anahtar ister.

```python
from lunixi import CreateIntent, MultiSellerPolicy

response = client.payments().create_marketplace_intent(
    CreateIntent("10050", "TRY", "persisted-order-123", **order),  # sipariş bilgileri yukarıdaki gibi
    sellers=[
        {"subDealerId": "d_alice", "amountMinor": "6000"},
        {"subDealerId": "d_bob", "amountMinor": "4050"},
    ],
    multi_seller_policy=MultiSellerPolicy.ALL_OR_NOTHING,
    idempotency_key=persisted_attempt_key,
)
```

Satıcıların `amountMinor` değerlerinin (kanonik küçük birim string) toplamı `amount` değerine eşit olmalıdır; başka bir toplam göndermeden önce `ConfigurationError` oluşturur.

## Ödeme linkleri

`client.payment_links()` paylaşılabilir ödeme sayfaları oluşturur ve yönetir. Okumalar dahil her çağrı anahtarınızla imzalanır; TEST veya LIVE linkleri görmenizi anahtarın ortamı belirler.

```python
from lunixi import CreatePaymentLinkRequest, PaymentLinkDeliveryChannel, PaymentLinkUsage

links = client.payment_links()
created = links.create(
    CreatePaymentLinkRequest.fixed(PaymentLinkUsage.SINGLE_USE, "150000", "TRY", "Invoice 2026-0042")
    .with_recipient({"name": "Test Buyer", "email": "buyer@example.com"}),
    idempotency_key=persisted_link_key,
)
links.send(created["id"], channel=PaymentLinkDeliveryChannel.EMAIL, idempotency_key=persisted_send_key)
page = links.list(state=["ACTIVE", "PAUSED"], limit=20)
```

`create()` ve `send()` 8–200 yazdırılabilir ASCII karakterli bir idempotency anahtarı ister; anahtarı tekrarlamak kayıtlı sonucu `replayed: True` ile döndürür. `update(link_id, expected_row_version, changes)` yalnız verilen alanları değiştirir (`None` bir alanı temizler) ve `usage`, `amountMode` ile `currency` değişikliğini reddeder; `pause()`, `resume()` ve `deactivate()` durumu değiştirir. `qr(link_id, format="png", size=512)` görseli `BinaryResponse` olarak döndürür. `list()`, `list_attempts()` ve `list_payments()` bir `Page` döndürür; `iterate…()` imleçleri izler. Bilinmeyen gövde alanları ve filtreler `ConfigurationError` oluşturur.

Link görseli üç adımda ya da tek çağrıyla yüklenir:

```python
image = links.upload_image(file_name="cover.png", content_type="image/png", content=png_bytes)
request = CreatePaymentLinkRequest.fixed(
    PaymentLinkUsage.MULTI_USE, "25000", "TRY", "Concert ticket"
).with_image_asset_id(image["assetId"])
```

`upload_image()`, `create_image_upload()` çağrısını, baytların önceden imzalanmış `uploadUrl` adresine PUT ile gönderilmesini ve `confirm_image_upload(asset_id)` çağrısını çalıştırır. PUT isteği yapılandırdığınız transport üzerinden doğrudan depolama sunucusuna, yalnız dönen `uploadHeaders` başlıklarıyla gider: erişim token'ınızı veya istek imzasını asla taşımaz. PNG, JPEG ve WebP kabul edilir (SVG edilmez); en fazla 2 MiB ve 4096×4096 px. Özel bir `HttpTransport` bu tek istekte gövdeyi `bytes` olarak alır.

## Cüzdan

`client.wallet()` kapalı devre cüzdanı kapsar: son kullanıcılar, cüzdanlar ve hesaplar, para yatırma, kurumsal hesaplar, ücretler, transferler, para çekme, bakiye yükleme, üye işyeri ödemeleri, QR kodlar ve toplu ödemeler. Her çağrı imzalıdır. Alanları mapping ya da anahtar kelime argümanı olarak, camelCase veya snake_case biçiminde verebilirsiniz.

```python
wallet = client.wallet()
user = wallet.end_users.create(
    program_id=program_id, account_type="PERSONAL", phone="+905550000000",
    idempotency_key=persisted_user_key,
)
started = wallet.transfers.initiate_w2w(
    end_user_id=user["endUserId"], source_wallet_account_id=account_id,
    destination_wallet_no="W123456", amount="12550", currency="TRY",
    idempotency_key=persisted_transfer_key,
)
wallet.transfers.complete_w2w(
    started["operationId"], end_user_id=user["endUserId"],
    integrity_hash=started["integrityHash"], nonce=started["nonce"], otp_code=otp,
    idempotency_key=persisted_complete_key,
)
```

Her çağrı tek bir rota tablosu, `WALLET_ROUTES`, ile denetlenir: bilinmeyen alan veya filtre, eksik zorunlu alan, küçük birim rakam string'i olmayan tutar (`"12550"`; asla `125.5` veya `12550` değil) ya da anahtar isteyen bir rotada eksik `Idempotency-Key` hiçbir şey gönderilmeden önce `ConfigurationError` oluşturur. `complete_*` çağrıları `operationId` değerini gövdeye kendileri ekler. Listeler bir `Page` döndürür; `iterate()` imleci izler. `qr.image(qr_id, format="png", scale=4)` görseli `BinaryResponse` olarak döndürür. Toplu ödemeler dört göz ilkesini izler: onaylayan anahtar, oluşturan anahtardan farklı olmalıdır.

## Banka hesapları, transferler ve döviz

`client.bank_connect()` bağlı banka hesaplarınızı okur (bağlantılar panelden kurulur). Her çağrı imzalıdır; TEST veya LIVE hesapların okunmasını anahtarın ortamı belirler.

```python
from datetime import datetime, timezone

bank = client.bank_connect()
page = bank.list_transactions(
    account_id=[account_id], booked_from=datetime(2026, 11, 1, tzinfo=timezone.utc),
    direction="CREDIT", min_amount_minor="10000", limit=50,
)
for transaction in bank.iterate_transactions(account_id=account_id):
    ...
```

Filtreler yerelde denetlenir: yalnız bilinen adlar, değer kümeleri (`BankConnectionStatus`, `BankTransactionDirection`, `BankTransactionType` …), 1–100 arası `limit`, en fazla 100 hesap kimliği, `min_amount_minor` ≤ `max_amount_minor` koşuluyla kanonik küçük birim tutar string'leri, yalnız `booked_from` ile birlikte `booked_to` ve en fazla 92 günlük aralık. `request_sync(account_id)` yeni bir okuma ister; yeni hareketler `bank_account.transaction.received` webhook'u ile gelir.

Giden transferler ve döviz işlemleri `bank-connect:transfer` kapsamını ve IP izin listesi olan bir anahtarı ister:

```python
transfer = bank.transfers.create(
    account_id=account_id, receiver_iban="TR330006100519786457841326",
    receiver_name="Test Receiver", amount_minor="150075",
    idempotency_key=persisted_payout_id,
)
quote = bank.fx.create_quote(
    source_account_id=try_account_id, target_account_id=usd_account_id,
    target_amount_minor="10000",
)
order = bank.fx.create_order(quote_id=quote["id"], idempotency_key=persisted_fx_key)
```

`create()` ve `create_order()` verdiğiniz `idempotency_key` değerini denetler (8–200 yazdırılabilir ASCII) ya da vermediğinizde bir UUID v4 üretir; ağ hatası veya 5xx aynı anahtar ve gövdeyle yeniden denenir. Süreçler arasında güvenle yeniden denemek için kendi anahtarınızı saklayın. Webhook'lar: `BankConnectEvents` ve `BankTransferEvents` (`bank_transfer.*`; ödemenin `payment.bank_transfer.*` olayları değildir); doğrulanmış olayı `BankAccountTransactionReceived.from_event(event)` veya `BankTransferWebhookData.from_event(event)` ile okuyun.

## Yaptırım taraması

`client.sanction()` isimleri, cüzdanları, hesapları ve işlemleri tarar; varlık istihbaratı ve sürekli izleme çalıştırır. Bu çağrılar erişim token'ını kullanır (istek imzası yoktur).

```python
from lunixi import is_clear_screening

result = client.sanction().screen_name(
    name="Test Person", subject_type="person", mode="sanctions_pep",
    customer_reference="customer-42",
)
if not is_clear_screening(result):
    hold_for_review()
```

Tarama karar değil eşleşme döndürür. `is_clear_screening()` yalnız eşleşme veya isabet, engelleyici işaret veya karar yoksa ve kapsam bildirildiği yerde `coverageStatus` değeri `COMPLETE` ise doğrudur; `PARTIAL` veya `DEGRADED` bir tarama hiçbir zaman temiz sayılmaz. Çalıştırılamayan tarama hata oluşturur (HTTP 503 ya da `status` değeri `success` olmayan 2xx yanıt); hiçbir zaman boş sonuç olarak dönmez. Gövdeler ve filtreler `SANCTION_ROUTES` ile denetlenir: bilinmeyen veya eksik alanlar, boş bir "en az biri" grubu, iç içe satır alanları ve `SANCTION_VALUE_SETS` dışındaki değerler `ConfigurationError` oluşturur.

## Sigorta

`client.insurance()` sepet kalemleri için sigorta sunar, teklifi siparişe çevirir, poliçelerini ve belgelerini izler, yalnız talep üzerine satılan türler için potansiyel müşteri kaydı gönderir. Her çağrı imzalıdır.

```python
from datetime import datetime, timezone

from lunixi import InsuranceClient

insurance = client.insurance()
quote = insurance.create_quote(
    insurance_type="TICKET_CANCELLATION", currency="TRY", context={"items": basket_items},
)
option = quote["options"][0]
order = insurance.create_order(
    quote_id=option["quoteId"],
    consent=InsuranceClient.consent_from_quote(option, datetime.now(timezone.utc)),
    idempotency_key=persisted_order_key,
)
premium_item = InsuranceClient.premium_basket_item(order, name="Insurance", category1="Insurance")
```

Teklifin sepeti ya bir ödemenin kayıtlı sepetidir (`payment_intent_id`) ya da ödemede göndereceğiniz kalemlerdir (`context`), ikisi birden olmaz; sepet kalemi olmadan satılan bir tür için ikisini de göndermeyin. `create_order`, `confirm_payment`, `issue_policy`, `cancel_order`, `refund_premium` ve `create_lead` 8–200 yazdırılabilir ASCII karakterli bir `idempotency_key` ister; `create_quote` ve `bind_payment` isteğe bağlı anahtar alır. Tür nesneleri (`insured`, `tickets` …) verildiği gibi gönderilir: gateway bunları doğrular ve bütün alan hatalarını tek seferde 422 `insurance.validation.invalid` ile döndürür. Poliçe belgeleri, makbuzlar ve sertifikalar `BinaryResponse` (PDF) olarak döner; `export_reconciliation(from_=..., to=...)` CSV'yi `truncated`, `next_cursor` ve `aborted` ile döndürür. Doğrulanmış webhook'ları `InsuranceWebhookData.from_event(event)` (sipariş olayları) ve `InsuranceLeadWebhookData.from_event(event)` (potansiyel müşteri olayları) ile okuyun.

## Abonelik

`client.subscriptions()` `/api/v1/subscriptions/*` rotalarını kapsar: abonelikler ile `plans`, `customers`, `cards`, `invoices`, `portal`, `products`, `features`, `addons` ve `usage` alt istemcileri. Çağrılar erişim token'ını taşır (istek imzası yoktur). Alanları mapping ya da anahtar kelime argümanı olarak, camelCase veya snake_case biçiminde verebilirsiniz.

```python
from lunixi import SubscriptionCollectionMethod, is_subscription_active

subscriptions = client.subscriptions()
customer = subscriptions.customers.upsert(external_id="user-42", email="ada@example.com")
plan = subscriptions.plans.create(
    product_id="prod_1", code="pro-monthly", name="Pro", price="9900", currency="TRY",
    billing={"frequency": "MONTHLY", "interval": 1}, trial_period_days=14,
)
# The card comes from the checkout SDK's token; a card number is never sent.
card = subscriptions.cards.add(
    customer_id=customer["id"], payment_method_token="pm_tok_1", is_default=True,
)
subscription = subscriptions.create(
    customer_id=customer["id"], plan_id=plan["id"], payment_card_id=card["id"],
    collection_method=SubscriptionCollectionMethod.AUTO_CHARGE,
    idempotency_key="sub-user-42-pro",  # required: reuse it when retrying
)
if is_subscription_active(subscription):  # TRIALING, ACTIVE or PAST_DUE
    ...
subscriptions.change_plan(
    subscription["id"], new_plan_id="plan_team", behavior="NEXT_PERIOD",
    idempotency_key="chg-42-team",
)
subscriptions.cancel(subscription["id"], at_period_end=True, reason="customer request")
```

- `create()` bir `idempotency_key` ister (ya da isteğin `idempotencyKey` alanını; ikisi birden verilirse aynı olmalıdır); anahtar başlıkta ve gövdede gönderilir. `plans.create`, `customers.upsert`, `cards.add`, `change_plan` ve `invoices.retry_charge` isteğe bağlı anahtar kabul eder.
- Tutarlar (`price`, `priceSnapshotAmount`, `totalAmount`, `amountMinor` …) küçük birim string değerleridir; gövdelerde, filtrelerde ve yanıtlarda denetlenir (`"0"` ücretsiz plandır).
- Abonelik, plan, müşteri, kart ve fatura listeleri bir `SubscriptionPage` döndürür (`next_page_token`, `page_size`); token'ı `page_token` olarak geri gönderin ya da `iterate()` kullanın. Katalog, özellik, ek paket ve portal linki listeleri bir `Page` döndürür.
- Müşteri portalı: `portal.create_sdk_session(customer_id, origin, sdk_mode=...)` tarayıcı portal SDK'sı için `portalToken`, `sessionProof`, `proofNonce` ve `proofExpiresAt` döndürür (`origin` izin listesinde olmalıdır). `portal.create_portal_link()` barındırılan bir link döndürür; `subscription_portal_url(link)` müşterinin açacağı adrestir. Link rotaları `/api/panel/v1/subscriptions/portal` altındadır; istemcinin kabul ettiği tek panel yolları bunlardır.
- Webhook'lar: `SubscriptionEvents` (`subscription.*`, `invoice.*`, `card.*`); ödeme olayları gibi `WebhookVerifier` ile doğrulanır.
- Her çağrı göndermeden önce `SUBSCRIPTION_ROUTES` ile denetlenir: bilinmeyen alan veya filtre, eksik alan ya da bilinmeyen değer `ConfigurationError` oluşturur.

## KYC ve kimlik

`client.kyc()` KYC, KYB ve kanıt oturumları oluşturur ve okur (`/api/v1/kyc/*`); `client.identity()` cihaz ve hesap ilişkilendirme sinyallerini okur (`/api/v1/identity/*`). İkisi de erişim token'ını kullanır. Tarayıcı SDK'ları yayınlanabilir anahtarınızla başlar; bu istemciler sunucu tarafıdır.

```python
from lunixi import KycAssuranceDomain, KycSessionType, is_identity_device_shared, kyc_assurance_meets

created = client.kyc().create_session(
    subject_id="user-42", session_type=KycSessionType.KYC,
    external_customer_id="user-42",  # echoed on every kyc.* webhook
    jurisdiction="TR", idempotency_key="kyc-user-42-1",
)
# Hand created["session"]["sessionId"] to the browser SDK; the kyc.* webhook carries the result.

result = client.kyc().get_session(created["session"]["sessionId"])
achieved = (result.get("session") or {}).get("decision", {}).get("assuranceSnapshot", {}).get("achieved", {})
if kyc_assurance_meets(achieved.get(KycAssuranceDomain.IDENTITY), "SUBSTANTIAL"):
    ...  # identity gate passed

links = client.identity().account_links(trace_id_from_browser)
if is_identity_device_shared(links):
    ...  # a second account on this device: review
```

- `kyc().list_sessions()` yalnız `limit` ve `cursor` alır (`page_size` / `page_token` aynı alanlar olarak okunur); başka bir filtre, sessizce bütün oturumları döndürmek yerine hata oluşturur. `iterate_sessions()` imleci izler.
- `person` / `company`, `customerType` ile birlikte `customer` olarak; `metadata` ise `evidenceContextJson` olarak gönderilir. `ttl_minutes` 1 ile 1440 arasındadır. `upload_document()` çağrısına verilen belge görseli hiçbir hata mesajında görünmez.
- Kişisel veri geri dönmez: durum, karar, risk seviyesi ve alan başına ulaşılan güvence seviyesi (`KycAssuranceDomain`). `kyc_assurance_meets(achieved, required)` karşılaştırmayı `NONE` / `NOT_PERFORMED` < `LOW` < `SUBSTANTIAL` < `HIGH` sıralamasına göre yapar.
- `KycEvents`, `kyc.*`, `kyb.*`, `screening.*` ve izleme olaylarını listeler. Onaylanmış bir oturumda yeniden tarama veya tarama eşleşmesi erişimi geri almalıdır.
- Kimlik yanıtları izin ver / incele / engelle kararı değil, sinyaldir (`riskFlags`, `reasonCodes`, olasılıklar, `identitySnapshot`); karar fraud tarafındadır.

## Pazaryeri (alt bayiler)

`client.marketplace()` alt bayiler arasında bölünmüş tahsilat yapar; alt bayileri, komisyonları, hakediş ödemelerini ve denetim kaydını yönetir. Bölünmüş tahsilatlar (`/api/v1/payments/marketplace/*`) istek başına imzalanır; diğer rotalar (`/api/v1/marketplace/*`) erişim token'ını kullanır.

```python
from lunixi import CreateIntent, MarketplaceMultiSellerPolicy, marketplace_onboarding_url

marketplace = client.marketplace()
dealer = marketplace.create_dealer(
    legal_name="Kurgu Ltd.", tax_id="1234567890", external_ref="vendor-7",
)
link = marketplace.onboarding_token(dealer["id"])
# Send the dealer to marketplace_onboarding_url(link): KYC, IBAN and contract, then ACTIVE.

intent = marketplace.create_checkout_intent(
    CreateIntent("100000", "TRY", "ORD-7", **order),  # sipariş bilgileri yukarıdaki gibi
    [
        {"subDealerId": "d_alice", "amountMinor": "60000"},
        {"subDealerId": "d_bob", "amountMinor": "40000"},
    ],
    MarketplaceMultiSellerPolicy.ALL_OR_NOTHING,
    idempotency_key="mp-ORD-7",
)
```

- Satıcı parçaları alt bayi başına toplamdır (`{"subDealerId", "amountMinor", "scenario"?}`, pozitif küçük birim string'ler) ve toplamları `amount` değerine eşit olmalıdır; istemci toplamı göndermeden önce denetler. Yanıt token veya form taşımıyorsa (örneğin `ALL_OR_NOTHING` altında uygun olmayan bir satıcı) `create_checkout_intent()` `ApiError` oluşturur. `payments().create_marketplace_intent()` ile aynı rotayı kullanır.
- Doğrudan bölünmüş kart tahsilatları (`charge_marketplace_card2d` / `charge_marketplace_card3d`) kart, alıcı, fatura adresi ve sepet kalemleri ister; PCI DSS SAQ-D kapsamındadır. Kart verisi verildiği gibi gönderilir; hiçbir zaman loglanmaz veya hata mesajına konmaz.
- Yalnız `ACTIVE` bayiler bölünmüş ödeme alır (`MarketplaceDealerStatus`). Bayi listeleri, hakediş defteri, işlemler, komisyon kuralları ve denetim kaydı bir `Page` döndürür.
- `resolve_commission(sub_dealer_id, category_code=..., mtd_volume_minor=...)` ve `preview_commission_rule(rule)` geçerli komisyonu okur; hakediş tutarları (`amountMinor`) küçük birim string değerleridir ve gövdelerde, filtrelerde ve yanıtlarda denetlenir.

## Kalıcı sipariş akışı

`lunixi.commerce.CheckoutService`, merchant/sipariş/tutar/para birimi izini ve sabit deneme anahtarını ağ çağrısından **önce** kaydeder. Tarayıcı token'ını bağımsız32 bayt anahtarla şifreler. Native callback, güncel sipariş tutarını/teslim blokesini denetleyip **aynı bağlantı ve transaction** içinde sipariş, stok ve bildirim kuyruğunu güncellemelidir. [Çalışan framework örnekleri](docs/FRAMEWORKS.tr.md) bunu gerçek veritabanlarıyla uygular.

`service.webhook(raw, headers, secret, apply_native)` ham gövde v2 HMAC, zaman ve imzalı id/type kontrolünden sonra kimlik doğrulamalı ödeme/çoklu kart sorgusunu değerlendirir. Kalıcı olay tüketimi ile sipariş değişikliği birlikte commit/rollback olur; eşzamanlı/tekrarlanan olay stoktan iki kez düşmez. Tarayıcı dönüşü/query parametresi/form olayı ödeme kanıtı değildir. Kayıp intent yanıtı yalnız imzalı webhook ve özgün rezervasyon izini doğrulayan GET ile toparlanır; bağlı ödeme kimliği değiştirilmez.

Kısmi tahsilat veya eksik çoklu kart üst ödemesi teslimi başlatmaz. Vade farkı sipariş iziyle kanıtlanıp sepetten ayrı tutulur. Yerel fraud/manual teslim blokesi korunur. Sonradan tutarı/para birimi değişen sipariş eski ödeme ile tamamlanamaz. `FAILED` sonucu kesinlik kanıtı taşımıyorsa incelemede kalır; belirsiz deneme otomatik sıfırlanmaz.

`service.mutate(order_key, kalici_islem_id, action, amount, apply_native)` ile tahsilat/iade/iptal yürütülür. `operation_status(...)` sonucundaki `pending`/`uncertain` başarı değildir; istenen bakiye hareketi GET ile doğrulanınca `confirmed` olur. Önceki işlem çözülmeden farklı kimlik açılamaz. İade gerçekten tahsil edileni aşamaz.23 saati aşan teyitsiz create/mutation tekrarları gateway anahtar saklama süresi nedeniyle engellenir; GET uzlaştırma açık kalır. Zaman aşımında aynı kimlik ve tutarı kullanın.

## Güvenlik ve mevcut fraud yüzeyi

İstemciyi origin/merchant key başına bir kez kurup paylaşın. Varsayılan cache eşzamanlı token yenilemeyi birleştirir; özel `TokenStore` origin/key'e göre ayrılmalıdır. PKCS8 PEM/DER, base64/hex seed ve doğrulanan64 bayt seed/public anahtar biçimleri desteklenir. Özel anahtar config çıktısına yazılmaz. HTTPS zorunludur; origin kullanıcı bilgisi/path/query/fragment içeremez, API yolları kaçamaz, yönlendirmeler takip edilmez. Yanıt boyutu/süre/tekrar sınırları vardır; yalnız sabit anahtarlı finansal istek yeniden gönderilebilir. Gövde JavaScript anahtar/sayı yazımıyla imzalanır.

`fraud().evaluate`, decision log liste/get ve event record/batch yöntemleri korunur. Karar/log Bearer, olay alımı istek başına Ed25519 imzası kullanır.500 olay sınırı ve kısmi batch hataları korunur; hata kayıtlarını aynı event ID ile tekrar gönderin. Generic `client.api().request(..., step_up=True)` diğer belgelenmiş merchant servislerine erişebilir; `client.api().request_binary("GET", path, step_up=True)` dosya yanıtını `BinaryResponse` olarak döndürür.

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
