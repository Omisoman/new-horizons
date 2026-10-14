---
synthetic: true
source: glossary.md
lang: en+ar
title: "Aquaponics Glossary — مسرد مصطلحات الزراعة المائية السمكية"
---

# Aquaponics Glossary — مسرد مصطلحات الزراعة المائية السمكية

**SYNTHETIC demo document.** Terms used across the Farm's procedures, systems
and reports, in English and Arabic.

## 1. The farm — المزرعة

| Term | Arabic | Meaning |
|---|---|---|
| Aquaponics | الزراعة المائية السمكية | fish and plants in one water loop: fish waste feeds the plants, the plants clean the water |
| Grow unit | وحدة الزراعة | one fish tank and the plant bed it feeds, e.g. AQ-03 |
| Grow bed | حوض الزراعة | the planted area a unit's water flows through, in m² |
| European perch | سمك الفرخ الأوروبي | the fish kept in every unit |
| Controller | وحدة التحكم | the system that reads the sensors and drives pumps, dosing and feeder |
| Cold room | غرفة التبريد | where harvests are weighed and kept at 2–4 °C before shipping |

## 2. Water — المياه

| Term | Arabic | Meaning |
|---|---|---|
| Nitrification | النترجة | bacteria turning fish waste into nitrate for the plants; slowly lowers pH |
| Dissolved oxygen (DO) | الأكسجين المذاب | oxygen in the water, mg/L; perch need at least 6.0 |
| pH | الحموضة | acidity of the water; operating band 6.6–7.2 |
| pH up | رافع الحموضة | potassium hydroxide dosed every Monday (NUT-01) |
| Water level | مستوى المياه | depth in the tank, normal 21–24 cm |
| Duty cycle | نسبة التشغيل | share of a day a pump runs |
| Air stone | حجر التهوية | diffuser that breaks air into fine bubbles |

## 3. Work and records — العمل والسجلات

| Term | Arabic | Meaning |
|---|---|---|
| Work order | أمر عمل | one maintenance job on one unit, WO-2026-NNNN |
| Alert | تنبيه | a reading outside its band, AL-2026-NNNN |
| Acknowledge | الإقرار بالتنبيه | a technician marking an alert as being handled |
| Response time | زمن الاستجابة | from an alert opening to the work order that answers it |
| Commanded vs observed | المأمور به مقابل المرصود | what the controller asked for against what the sensors saw |
| Failed command | أمر فاشل | a pump run that changed nothing in the water |
| Audit chain | سلسلة التدقيق | the hash-chained, append-only log of every decision and agent action |
| Kill switch | مفتاح الإيقاف | pausing the analytics agent; recorded in the audit chain |

## 4. Harvest and sales — الحصاد والمبيعات

| Term | Arabic | Meaning |
|---|---|---|
| Harvest batch | دفعة حصاد | one weighed harvest of one unit, HV-2026-NNNN |
| Countersign | التوقيع الثاني | a second person confirming a harvest record at the cold room |
| Shipment | شحنة | produce leaving the Farm for a customer, SHP-2026-NNNN |
| Trim loss | فاقد التقليم | weight lost between harvest and shipment, up to 5% |
| Write-off | شطب | a harvest discarded with a recorded reason |
| Price list | قائمة الأسعار | the {{currency}} per kg the Farm charges for each crop |

## 5. Supplies — المستلزمات

| Term | Arabic | Meaning |
|---|---|---|
| Purchase order | أمر شراء | an order to a supplier, PO-2026-NNNN |
| Goods received | البضاعة المستلمة | the delivery booked against an order |
| Credit note | إشعار دائن | the supplier's refund of an overcharge |
| Approved supplier list | قائمة الموردين المعتمدين | suppliers the Farm may buy from |
| Stock count | جرد المخزون | the weekly count of feed, nutrients and parts |
| Unmetered consumption | استهلاك غير مقيس | use of an item with no purchase or no stock behind it |

## 6. Analytics — التحليلات

| Term | Arabic | Meaning |
|---|---|---|
| Dropout | انقطاع | a period when a sensor sent nothing; leaves a gap, never a zero |
| Uptime | نسبة التشغيل الفعلي | share of expected readings that arrived |
| Drift | انحراف | a lasting change in a reading's distribution against a reference month |
| PSI | مؤشر استقرار المجتمع | population stability index; 0.1 moderate, 0.2 major |
| KS test | اختبار كولموغوروف–سميرنوف | statistical test of whether two distributions differ |
| Sensor drift | انحراف المجس | the probe's reading moves while the water does not |
| Chemistry drift | انحراف الكيمياء | the water itself changes: steeper decline between doses, more dosing |
| Calibration | معايرة | resetting a probe against known buffers |
| At risk | معرّض للخطر | kilograms or {{currency}} an exception puts in doubt |
