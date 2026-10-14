---
synthetic: true
source: harvest-shipping-procedure.md
lang: en+ar
title: "Harvest and Shipping Procedure — إجراء الحصاد والشحن"
---

# Harvest and Shipping Procedure — إجراء الحصاد والشحن

**SYNTHETIC demo document.** How a harvest is cut, weighed, recorded and
shipped, and the checks that keep the harvest records honest. A harvest record
is money on paper until a shipment proves it left the building.

## 1. Scope — النطاق

- Each grow unit is harvested **weekly, on Mondays**; the plant beds are picked
  by section so the unit keeps producing — تُحصد كل وحدة أسبوعياً يوم الاثنين.
- The harvest is weighed at the cold room and recorded in `harvest.harvests`
  with its unit, plant and kilograms — يُوزن الحصاد في غرفة التبريد ويُسجَّل.

## 2. Logging and countersignature — التسجيل والتوقيع الثاني

- Each harvest record is logged by the technician who harvested it, under their
  technician code — يُسجَّل كل حصاد باسم من قام بالحصاد ورمزه.
- Before it can ship, the record is **countersigned** by a second person at the
  cold room, who checks the weight on the scale — قبل الشحن يوقّع شخص ثانٍ على
  السجل في غرفة التبريد بعد التحقق من الوزن على الميزان.
- A technician never countersigns their own harvest; a record with one
  signature is not complete and cannot be shipped or counted as yield — لا يوقّع
  أحد على حصاده بنفسه، والسجل الذي يحمل توقيعاً واحداً غير مكتمل ولا يُشحن.
- The Farm Manager reviews the week's harvest records every Monday and asks
  about any record without a countersignature — يراجع مدير المزرعة سجلات الأسبوع
  كل اثنين ويسأل عن أي سجل بلا توقيع ثانٍ.

## 3. From harvest to shipment — من الحصاد إلى الشحن

- Every harvest batch is **shipped or written off, with a reason, within 48
  hours**. Fresh produce does not wait — كل دفعة حصاد تُشحن أو تُشطب مع ذكر السبب
  خلال 48 ساعة.
- The shipment carries the harvest number it came from; the kilograms shipped
  are **within 5% of the kilograms harvested** — that is the trim loss at the
  cold room — تحمل الشحنة رقم الحصاد، وتكون الكمية المشحونة ضمن 5% من الكمية
  المحصودة، وهو فاقد التقليم.
- A harvest with **no shipment and no write-off after 48 hours** is an exception
  reported to the Farm Manager; the nightly reconciliation lists it with its
  kilograms and their value at the price list — الحصاد الذي لا شحنة له ولا شطب
  بعد 48 ساعة استثناء يُبلَّغ إلى مدير المزرعة.
- Several such exceptions logged by the same person are treated as a records
  problem, not a logistics one, and go to the owner — تكرار هذه الاستثناءات من
  الشخص نفسه مسألة سجلات وتُرفع إلى المالك.

## 4. Cold chain — سلسلة التبريد

- Harvested produce goes into the cold room at **2 to 4 °C** within 30 minutes
  of picking — يدخل الحصاد غرفة التبريد بحرارة من 2 إلى 4 درجات خلال 30 دقيقة.
- Basil is the exception: it is kept at 10 to 12 °C, because cold blackens its
  leaves — الريحان استثناء ويُحفظ بين 10 و12 درجة.
- A shipment leaves in a cooled van with its harvest numbers on the delivery
  note — تخرج الشحنة في مركبة مبرّدة مع أرقام الحصاد على مذكرة التسليم.

## 5. Customers and prices — العملاء والأسعار

- The Farm sells to restaurants, grocers and a weekly market; each customer has
  a reference (CUS-NN) — تبيع المزرعة للمطاعم ومحلات البقالة وسوق أسبوعي.
- The price list ({{currency}} per kg) is: pepper **4.20**, lettuce **3.10**,
  tomato **3.60**, basil **18.00** — قائمة الأسعار بالـ{{currency}} لكل كيلوغرام: فلفل
  4.20، خس 3.10، طماطم 3.60، ريحان 18.00.
- The value of a shipment is its kilograms at the price list, less any agreed
  customer discount; the reconciliation prices exceptions at the list — قيمة
  الشحنة هي كميتها بسعر القائمة ناقص أي خصم متفق عليه.

| Plant | {{currency}} / kg |
|---|---|
| pepper | 4.20 |
| lettuce | 3.10 |
| tomato | 3.60 |
| basil | 18.00 |

## 6. Write-offs — الشطب

- A harvest that cannot ship — bruised, wilted, below grade — is written off by
  the Farm Manager with a reason, the same day — الحصاد الذي لا يصلح للشحن يشطبه
  مدير المزرعة مع ذكر السبب في اليوم نفسه.
- Written-off produce goes to compost; it is weighed and recorded so the yield
  figures stay true — يُوزن المشطوب ويُسجَّل لتبقى أرقام الإنتاج صحيحة.
- A write-off is never used to close a harvest that was never picked — لا يُستخدم
  الشطب لإغلاق حصاد لم يُقطف أصلاً.
