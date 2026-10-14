---
synthetic: true
source: data-dictionary.md
lang: en+ar
title: "Farm Data Dictionary — قاموس بيانات المزرعة"
---

# Farm Data Dictionary — قاموس بيانات المزرعة

**SYNTHETIC demo document.** What every table and column in the Farm's five
systems means in the language of the farm, which business key joins it to the
others, and where each planted scenario lives. The agent reads this to know
that `harvest.harvests.kg` is what was picked and `harvest.shipments.kg` is what
left — and that a harvest with no shipment is a finding.

## 1. The five systems and how they join — الأنظمة الخمسة وكيف تترابط

| System — النظام | Schema | Business owner | What it records |
|---|---|---|---|
| Telemetry — القياسات | `telemetry` | Technicians | what actually happened in the water and air |
| Controller — وحدة التحكم | `controller` | Technicians | what the pumps, dosing and feeder were told to do, and the alerts |
| Maintenance — الصيانة | `maintenance` | Farm Manager | who touched which unit, when, and the outcome |
| Harvest — الحصاد | `harvest` | Farm Manager | what was picked and what left the building |
| Supplies — المستلزمات | `supplies` | Farm Manager | what was bought and what was used |

- Systems join **only on a business key**: `unit_id` (AQ-01 … AQ-04) in every
  system, `technician_code` (TEC-NN), `item_code`, `alert_no`, `harvest_no`,
  `po_no`, `invoice_no`, `supplier_ref`, `customer_ref` — الأنظمة تترابط بمفاتيح
  الأعمال فقط، ولا تترابط أبداً بالمعرّفات الرقمية الداخلية لنظام آخر.
- A technician code is also held in `controller.commands.issued_by`,
  `controller.alerts.acknowledged_by`, `harvest.harvests.logged_by` and
  `harvest.harvests.countersigned_by`; join those to
  `maintenance.technicians.technician_code` — رمز الفني موجود أيضاً في أعمدة
  أخرى ويُربط برمز الفني في جدول الفنيين.
- Numeric ids (`technician_id`, `work_order_id`, …) mean something only inside
  their own system — المعرّفات الرقمية لها معنى داخل نظامها فقط.
- All times are local farm time (`timestamp`, no time zone); dates are calendar
  days — كل الأوقات بالتوقيت المحلي للمزرعة.

## 2. Telemetry — القياسات

### 2.1 units — الوحدات

| Column | Meaning — المعنى |
|---|---|
| `unit_id` | the grow unit, AQ-01 … AQ-04 — الوحدة |
| `plant` | pepper, lettuce, tomato or basil — النبات |
| `location` | greenhouse-A, greenhouse-B or rooftop — الموقع |
| `grow_bed_m2` | planted area of the grow bed in m² — مساحة حوض الزراعة |
| `fish_species` | the fish in the tank (European perch) — نوع السمك |
| `fish_count` | fish in the tank — عدد الأسماك |
| `commissioned` | the day the unit started — تاريخ تشغيل الوحدة |

### 2.2 readings — القراءات

| Column | Meaning — المعنى |
|---|---|
| `reading_id` | row id — معرّف السطر |
| `ts` | time of the reading, every 15 minutes — وقت القراءة كل 15 دقيقة |
| `unit_id` | the unit — الوحدة |
| `air_temp_c` | air temperature in °C — حرارة الهواء |
| `humidity_pct` | relative humidity in % — الرطوبة النسبية |
| `water_temp_c` | tank water temperature in °C — حرارة المياه |
| `ph` | pH of the water — الحموضة |
| `dissolved_o2_mg_l` | dissolved oxygen in mg/L — الأكسجين المذاب |
| `water_level_cm` | tank water level in cm — مستوى المياه |

- One row per unit per 15 minutes; a sensor dropout is a **missing row**, never
  a row of zeros — سطر لكل وحدة كل 15 دقيقة، والانقطاع سطر مفقود وليس سطراً من الأصفار.

## 3. Controller — وحدة التحكم

### 3.1 commands — الأوامر

| Column | Meaning — المعنى |
|---|---|
| `command_id` | row id — معرّف السطر |
| `ts` | when the command was issued — وقت إصدار الأمر |
| `unit_id` | the unit — الوحدة |
| `actuator` | water_pump, air_pump, dosing_pump or feeder — المشغّل |
| `action` | on, off, dose_ph_up or feed — الإجراء |
| `duration_s` | how long it ran, in seconds; 0 for a state change — مدة التشغيل |
| `qty` | kilograms dispensed by the feeder or the dosing pump — الكمية المصروفة |
| `trigger` | low_level, low_do, do_recovered, weekly_dosing or feeding_schedule — سبب الأمر |
| `issued_by` | `controller`, or the technician code for a manual command — مصدر الأمر |

- A command says what the controller **asked**; `telemetry.readings` says what
  **happened**. A water-pump run that raises no level is a failed command (pump
  maintenance SOP, section 4) — الأمر يبيّن ما طُلب، والقراءات تبيّن ما حدث.

### 3.2 alerts — التنبيهات

| Column | Meaning — المعنى |
|---|---|
| `alert_id` | row id — معرّف السطر |
| `alert_no` | business key, AL-2026-NNNN — رقم التنبيه |
| `unit_id` | the unit — الوحدة |
| `type` | low_water_level, low_dissolved_o2, high_water_temp, high_air_temp, low_ph or high_ph — نوع التنبيه |
| `value` | the reading that opened it — القراءة التي فتحته |
| `threshold` | the band edge it crossed — الحد الذي تجاوزته |
| `opened_ts` | when it opened — وقت فتحه |
| `acknowledged_ts` | when a technician acknowledged it; empty if nobody did — وقت الإقرار به |
| `acknowledged_by` | technician code — رمز الفني |
| `resolved_ts` | when the reading went back inside the band — وقت إغلاقه |
| `status` | open or resolved — الحالة |

## 4. Maintenance — الصيانة

### 4.1 technicians — الفنيون

| Column | Meaning — المعنى |
|---|---|
| `technician_id` | row id inside maintenance — معرّف داخلي |
| `technician_code` | business key, TEC-NN — رمز الفني |
| `name` | the technician's name — الاسم |
| `role` | technician or senior technician — الدور |
| `started` | first day at the Farm — تاريخ البدء |

### 4.2 work_orders — أوامر العمل

| Column | Meaning — المعنى |
|---|---|
| `work_order_id` | row id — معرّف السطر |
| `work_order_no` | business key, WO-2026-NNNN — رقم أمر العمل |
| `opened_ts` | when the job was opened — وقت فتح الأمر |
| `unit_id` | the unit — الوحدة |
| `technician_id` | who did it (joins `technicians` inside maintenance) — الفني |
| `type` | filter_clean, pump_service, sensor_calibration, dosing_check, pump_repair, alert_response or sensor_check — نوع العمل |
| `alert_no` | the controller alert it answers, if any — التنبيه المرتبط |
| `closed_ts` | when the job was closed — وقت الإغلاق |
| `outcome` | done, fixed, part_replaced or no_fault_found — النتيجة |
| `part_item_code` | the supplies item fitted on the job — القطعة المركّبة |
| `notes` | free text — ملاحظات |

- The time between `controller.alerts.opened_ts` and the matching work order's
  `opened_ts` is the **response time** the pump SOP measures — الزمن بين فتح
  التنبيه وفتح أمر العمل المرتبط هو زمن الاستجابة.

## 5. Harvest — الحصاد

### 5.1 customers — العملاء

| Column | Meaning — المعنى |
|---|---|
| `customer_ref` | business key, CUS-NN — رمز العميل |
| `name` | customer name — الاسم |
| `segment` | restaurant, grocer or market — الفئة |

### 5.2 harvests — الحصاد

| Column | Meaning — المعنى |
|---|---|
| `harvest_id` | row id — معرّف السطر |
| `harvest_no` | business key, HV-2026-NNNN — رقم الحصاد |
| `date` | harvest day — يوم الحصاد |
| `unit_id` | the unit — الوحدة |
| `plant` | the crop — المحصول |
| `kg` | kilograms picked and weighed — الكمية المحصودة بالكيلوغرام |
| `logged_by` | technician code of who logged it — من سجّله |
| `countersigned_by` | technician code of the second signatory; empty if nobody countersigned — من وقّع ثانياً |
| `notes` | free text, e.g. a reduced harvest — ملاحظات |

### 5.3 shipments — الشحنات

| Column | Meaning — المعنى |
|---|---|
| `shipment_id` | row id — معرّف السطر |
| `shipment_ref` | business key, SHP-2026-NNNN — رقم الشحنة |
| `date` | shipping day — يوم الشحن |
| `unit_id` | the unit the produce came from — الوحدة |
| `harvest_no` | the harvest it ships — رقم الحصاد |
| `kg` | kilograms shipped — الكمية المشحونة |
| `customer_ref` | the customer — العميل |
| `eur` | value of the shipment in {{currency}} — قيمة الشحنة |

## 6. Supplies — المستلزمات

### 6.1 suppliers — الموردون

| Column | Meaning — المعنى |
|---|---|
| `supplier_ref` | business key, SUP-NNN — رمز المورد |
| `name` | supplier name — الاسم |
| `approved` | on the approved supplier list — معتمد |
| `phone` | the phone number on file, used for verification — رقم الهاتف المسجل |

### 6.2 items — الأصناف

| Column | Meaning — المعنى |
|---|---|
| `item_code` | business key: FEED-NN feed, NUT-NN nutrients and pH up, PART-NN spare parts — رمز الصنف |
| `name` | item name — الاسم |
| `category` | feed, nutrient or part — الفئة |
| `unit` | kg or pcs — وحدة القياس |
| `list_price_eur` | list price per unit in {{currency}} — سعر القائمة |

### 6.3 purchases — المشتريات

| Column | Meaning — المعنى |
|---|---|
| `purchase_id` | row id — معرّف السطر |
| `po_no` | business key, PO-2026-NNNN — رقم أمر الشراء |
| `ordered` | order date — تاريخ الطلب |
| `received` | goods-received date; empty until received — تاريخ الاستلام |
| `supplier_ref` | the supplier on the order — المورد |
| `item_code` | the item — الصنف |
| `qty` | quantity ordered — الكمية |
| `unit_price_eur` | the agreed price per unit — السعر المتفق عليه |
| `eur` | order value in {{currency}} — قيمة الأمر |
| `invoice_no` | the supplier's invoice once matched — رقم الفاتورة |
| `status` | invoiced or awaiting_invoice — الحالة |

### 6.4 consumption — الاستهلاك

| Column | Meaning — المعنى |
|---|---|
| `consumption_id` | row id — معرّف السطر |
| `date` | the day — اليوم |
| `unit_id` | the unit that used it — الوحدة |
| `item_code` | the item — الصنف |
| `qty` | quantity used — الكمية المستهلكة |
| `source` | feeder, dosing or work_order — المصدر |

## 7. How reconciliation figures are counted — كيف تُحتسب أرقام المطابقة

- The nightly reconciliation compares three pairs of systems: commanded vs
  observed (controller vs telemetry), harvested vs shipped (harvests vs
  shipments) and consumed vs purchased (consumption vs purchases) — تقارن المطابقة
  الليلية ثلاثة أزواج: المأمور به مقابل المرصود، والمحصود مقابل المشحون، والمستهلك مقابل المشترى.
- Every exception carries the kilograms and the {{currency}} **at risk**: for a
  pump failure, the harvest the unit lost against its usual week; for a harvest
  with no shipment, its kilograms at the price list; for unmetered consumption,
  the quantity at the item's list price — يحمل كل استثناء الكيلوغرامات والقيمة
  المعرّضة للخطر.
- Exceptions are ranked by money at risk, not by count; the totals per class are
  computed once and quoted, never re-added by hand — تُرتب الاستثناءات حسب المال
  المعرّض للخطر لا حسب العدد.
- A figure in an answer names the tool or query it came from, or the section of
  this knowledge base — كل رقم في الإجابة يذكر الأداة أو الاستعلام الذي جاء منه.

## 8. Planted scenarios — السيناريوهات المزروعة

- All data in the five systems is **synthetic** and seeded; these scenarios
  were planted on purpose so the analytics can be shown to find them — كل
  البيانات تركيبية، وهذه السيناريوهات زُرعت عمداً ليُثبت أن التحليلات تجدها.
- **Pump failure, AQ-03, 12–18 July:** water-pump commands with no level rise,
  the level falling towards 0 cm, a low_water_level alert left open, a late
  pump_repair work order, and a harvest collapse on 20 July — تعطل مضخة الوحدة
  AQ-03 من 12 إلى 18 تموز.
- **Heatwave, 26–30 July:** warmer water in every unit and an air-pump duty
  spike on AQ-03 — موجة حر من 26 إلى 30 تموز.
- **Harvests with no shipment:** six harvest records, all logged by one
  technician, none countersigned, none shipped — ستة سجلات حصاد بلا شحنات سجّلها
  شخص واحد ولم يوقّع عليها أحد.
- **Unmetered feed:** AQ-02 consumed FEED-03 in August with no purchase of
  FEED-03 behind it — استهلكت الوحدة AQ-02 الصنف FEED-03 في آب دون أي عملية شراء.
- **Sensor dropouts:** AQ-02 on 13 June (9 hours) and AQ-04 on 6 August
  (5 hours) — gaps in the readings, not zeros — انقطاع حساسات الوحدتين AQ-02 وAQ-04.
- **pH probe drift, AQ-04, August:** the probe's reading rose while the water
  did not; a sensor_calibration work order on 21 August stepped it back — انحراف
  مجس الحموضة في الوحدة AQ-04 في آب وتصحيحه بالمعايرة في 21 آب.
- **Weekly pH dosing:** the Monday 08:00 dose in every unit — a benign pattern,
  never a finding — الجرعة الأسبوعية يوم الاثنين نمط طبيعي وليست نتيجة.
