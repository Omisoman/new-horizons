---
synthetic: true
source: feeding-schedule.md
lang: en+ar
title: "Feeding Schedule — جدول التغذية"
---

# Feeding Schedule — جدول التغذية

**SYNTHETIC demo document.** How much the Farm's fish are fed, when, with
which feed, and how every gram is recorded. Feed is the largest running cost
of the Farm and the only input that reaches the plants through the fish.

## 1. Scope — النطاق

- This schedule covers the four grow units (AQ-01 to AQ-04) and their perch
  stock — يغطي هذا الجدول الوحدات الأربع ومخزونها من سمك الفرخ.
- The feeder in each unit is driven by the controller; a technician fills its
  hopper from a recorded stock of feed and never from an unrecorded bag — يدير
  المغذّي في كل وحدة وحدةُ التحكم، ويملأ الفني خزانه من مخزون علف مسجّل فقط.

## 2. Rations — الحصص الغذائية

- Fish are fed **three times a day**, at 07:00, 12:00 and 17:00 — تُطعم الأسماك
  ثلاث مرات يومياً في الساعة 07:00 و12:00 و17:00.
- The daily ration is **12 g per fish per day**, split evenly across the three
  feeds — الحصة اليومية 12 غراماً لكل سمكة في اليوم، موزعة بالتساوي على الوجبات الثلاث.
- On a day the water passes **23 °C**, the ration is reduced by **25%**: warm
  water holds less oxygen and uneaten feed fouls the tank — في اليوم الذي تتجاوز
  فيه حرارة المياه 23 درجة تُخفض الحصة بنسبة 25%.
- A unit whose fish leave feed uneaten for two days running is reported to the
  Farm Manager — أي وحدة تترك أسماكها العلف يومين متتاليين يُبلَّغ عنها مدير المزرعة.

| Unit | Fish | Daily ration (kg) |
|---|---|---|
| AQ-01 | 34 | 0.408 |
| AQ-02 | 21 | 0.252 |
| AQ-03 | 28 | 0.336 |
| AQ-04 | 14 | 0.168 |

## 3. Feed types and changes — أنواع العلف وتغييرها

- The standard feed for every unit is **FEED-01, floating pellets 3 mm**,
  bought from a supplier on the approved supplier list — العلف القياسي لكل
  الوحدات هو FEED-01 حبيبات طافية 3 ملم، يُشترى من مورد في قائمة الموردين المعتمدين.
- Changing a unit's feed type needs the **Farm Manager's approval** and a
  recorded purchase from an **approved supplier** before the first feed. A feed
  that was never bought is never fed — تغيير نوع العلف لأي وحدة يحتاج إلى موافقة
  مدير المزرعة وعملية شراء مسجلة من مورد معتمد قبل أول وجبة.
- Feed of unknown origin is a biosecurity incident (biosecurity rules,
  section 3) — العلف مجهول المصدر حادث أمن حيوي.

## 4. Heat and stress — الحرارة والإجهاد

- In a heatwave, feeding is cut back before oxygen falls, not after; the 25%
  cut in section 2 applies from the first day the water passes 23 °C — في موجات
  الحر تُخفض التغذية قبل انخفاض الأكسجين لا بعده.
- After a pump failure or any low-level event, feeding resumes at half ration
  for one day once the level is back in band — بعد تعطل المضخة أو انخفاض المستوى
  تُستأنف التغذية بنصف الحصة يوماً واحداً بعد عودة المستوى إلى نطاقه.

## 5. Recording — التسجيل

- Every feeder dispense is a **controller command** (`feeder`, `feed`, trigger
  `feeding_schedule`) with the kilograms dispensed in `qty` — كل عملية تغذية أمر
  في وحدة التحكم مع الكمية المصروفة بالكيلوغرام.
- The day's dispenses are posted as one line per unit and feed item to
  `supplies.consumption` (source `feeder`) — تُرحَّل كميات اليوم سطراً واحداً لكل
  وحدة وصنف في سجل الاستهلاك.
- Consumption is reconciled against purchases at the weekly stock count
  (supplier invoice controls, section 4) — يُطابق الاستهلاك مع المشتريات في الجرد
  الأسبوعي.

## 6. Feed storage — تخزين العلف

- Feed is stored sealed, off the floor, in the dry store next to the cold room,
  below 25 °C — يُخزن العلف مغلقاً بعيداً عن الأرض في المخزن الجاف تحت 25 درجة.
- Bags are used first in, first out; an opened bag is finished within 30 days —
  تُستخدم الأكياس بترتيب وصولها، والكيس المفتوح يُستهلك خلال 30 يوماً.
- Every bag carries its purchase-order number on a label; a bag without one is
  not fed (biosecurity rules, section 3) — يحمل كل كيس رقم أمر الشراء على ملصق.
