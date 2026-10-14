---
synthetic: true
source: water-quality-sop.md
lang: en+ar
title: "Water Quality SOP — إجراء التشغيل القياسي لجودة المياه"
---

# Water Quality SOP — إجراء التشغيل القياسي لجودة المياه

**SYNTHETIC demo document.** The operating bands for water in the Farm's four
grow units, what the controller does on its own, and when a person must act.
Every band below is the threshold the controller and the analytics read; the
data in the five systems is measured against exactly these numbers.

## 1. Scope and units — النطاق والوحدات

- The Farm runs four grow units. Each unit is one fish tank feeding one plant
  bed through the same water loop — تدير المزرعة أربع وحدات زراعة، كل وحدة حوض
  سمك واحد يغذي حوض زراعة واحداً عبر دورة المياه نفسها.
- The fish in every unit are European perch; the bands in this document are set
  for perch first, then for the plants — الأسماك في كل الوحدات من سمك الفرخ
  الأوروبي، والحدود هنا مضبوطة للأسماك أولاً ثم للنباتات.
- One controller reads every unit's sensors every 15 minutes and drives the
  water pump, the air pump, the dosing pump and the feeder — وحدة تحكم واحدة
  تقرأ حساسات كل وحدة كل 15 دقيقة وتشغّل مضخة المياه ومضخة الهواء ومضخة الجرعات
  والمغذّي.

| Unit — الوحدة | Plant — النبات | Location — الموقع | Grow bed m² | Fish |
|---|---|---|---|---|
| AQ-01 | pepper — فلفل | greenhouse-A | 29.0 | 34 |
| AQ-02 | lettuce — خس | greenhouse-A | 18.0 | 21 |
| AQ-03 | tomato — طماطم | greenhouse-B | 24.0 | 28 |
| AQ-04 | basil — ريحان | rooftop | 12.0 | 14 |

## 2. pH band — نطاق الحموضة

- The operating pH band for every unit is **6.6 to 7.2**: the compromise
  between the fish, the plants and the nitrifying bacteria that turn fish waste
  into plant food — نطاق الحموضة التشغيلي لكل وحدة هو **من 6.6 إلى 7.2**، وهو
  الحل الوسط بين الأسماك والنباتات وبكتيريا النترجة.
- The controller raises an alert when pH falls **below 6.4** or rises **above
  7.4** — تطلق وحدة التحكم تنبيهاً إذا انخفضت الحموضة عن 6.4 أو ارتفعت فوق 7.4.
- pH is never corrected by more than **0.3 in one day**; a faster swing
  stresses the fish more than the deviation it corrects — لا تُصحَّح الحموضة
  بأكثر من 0.3 في اليوم الواحد، لأن التغيير الأسرع يجهد الأسماك أكثر من الانحراف نفسه.
- A reading outside the band that the weekly dosing (section 5) does not
  explain is checked against a handheld meter before anything is dosed
  (sensor calibration procedure, section 3) — أي قراءة خارج النطاق لا تفسّرها
  الجرعة الأسبوعية تُقارن بجهاز قياس يدوي قبل إضافة أي جرعة.

## 3. Dissolved oxygen — الأكسجين المذاب

- Perch need at least **6.0 mg/L** of dissolved oxygen; below that they stop
  feeding and become vulnerable to disease — يحتاج سمك الفرخ إلى 6.0 ملغ/لتر على
  الأقل من الأكسجين المذاب.
- The controller switches a unit's air pump **on below 6.5 mg/L** and **off
  at 7.0 mg/L**. The gap between the two is deliberate: it stops the pump
  flickering on and off — تشغّل وحدة التحكم مضخة الهواء عند انخفاض الأكسجين عن 6.5
  وتوقفها عند 7.0.
- An alert is raised when dissolved oxygen falls **below 6.0 mg/L**; it is a
  live-stock risk and follows the escalation in the alert escalation procedure,
  section 2 — يُطلق تنبيه عند انخفاض الأكسجين عن 6.0، وهو خطر على الكائنات الحية.
- Warm water holds less oxygen. An air pump that runs **more than 50% of a
  day** is investigated: heat, a blocked air stone or too many fish — أي مضخة
  هواء تعمل أكثر من 50% من اليوم يُبحث في سببها: الحرارة أو انسداد حجر التهوية أو كثافة الأسماك.

## 4. Water and air temperature — حرارة المياه والهواء

- The water temperature band for perch is **18 to 23 °C** — نطاق حرارة المياه
  المناسب لسمك الفرخ من 18 إلى 23 درجة مئوية.
- The controller raises an alert when the water passes **23.5 °C**; above it
  oxygen falls and feeding is cut back (feeding schedule, section 4) — تُطلق
  وحدة التحكم تنبيهاً عندما تتجاوز حرارة المياه 23.5 درجة.
- An air temperature **above 30 °C** in a growing space raises an alert: the
  plants wilt and the rooftop unit needs shade — تُطلق حرارة هواء تزيد على 30
  درجة تنبيهاً، وتحتاج الوحدة على السطح إلى تظليل.
- The rooftop unit (AQ-04) runs about 2.5 °C warmer than the greenhouses and is
  checked first in a heatwave — تعمل الوحدة على السطح أدفأ من البيوت المحمية بنحو
  2.5 درجة وتُفحص أولاً في موجات الحر.

## 5. Weekly pH dosing — الجرعة الأسبوعية لرفع الحموضة

- Nitrification lowers pH slowly every day. Every **Monday at 08:00** the
  controller doses potassium hydroxide (pH up, item NUT-01) into each unit and
  raises pH by **0.3**, capped at **7.1** — كل يوم اثنين الساعة 08:00 تضيف وحدة
  التحكم هيدروكسيد البوتاسيوم إلى كل وحدة فترفع الحموضة بمقدار 0.3 بحد أقصى 7.1.
- The weekly sawtooth this produces — a slow decline, then a step up on Monday —
  is the normal shape of a healthy unit, **not drift**. Analyses compare like
  weeks with like weeks and never flag it — نمط المنشار الأسبوعي الناتج انخفاض
  بطيء ثم ارتفاع يوم الاثنين، وهو الشكل الطبيعي للوحدة السليمة وليس انحرافاً.
- Each dose is a controller command (`dosing_pump`, `dose_ph_up`, trigger
  `weekly_dosing`) and a consumption line for NUT-01 — كل جرعة أمر في وحدة التحكم
  وسطر استهلاك للصنف NUT-01.
- An extra dose outside Monday needs the Farm Manager's approval and is logged
  as a manual command with the technician's code — أي جرعة إضافية خارج يوم الاثنين
  تحتاج إلى موافقة مدير المزرعة.

## 6. Water level — مستوى المياه

- The normal water level in a tank is **21 to 24 cm** — المستوى الطبيعي للمياه في
  الحوض من 21 إلى 24 سم.
- Evaporation and plant uptake lower the level all day. When it falls **below
  21 cm** the controller runs the refill (water) pump for 90 to 150 seconds,
  which raises the level by about 3 cm — عندما ينخفض المستوى عن 21 سم تشغّل وحدة
  التحكم مضخة المياه من 90 إلى 150 ثانية فيرتفع المستوى نحو 3 سم.
- An alert is raised when the level falls **below 18 cm**. A level that keeps
  falling while the pump is commanded means the pump has failed (pump
  maintenance SOP, sections 3 and 4) — يُطلق تنبيه عند انخفاض المستوى عن 18 سم.
- At low level the plant roots dry out and the fish crowd; harvests in the
  following week fall — عند انخفاض المستوى تجف جذور النباتات ويتكدّس السمك،
  وينخفض حصاد الأسبوع التالي.

## 7. Records — السجلات

- Every reading is kept in `telemetry.readings`; a sensor that stops reporting
  leaves a gap, never a zero (sensor calibration procedure, section 4) — تُحفظ كل
  قراءة، والحساس المتوقف يترك فجوة وليس صفراً.
- Alerts are kept in `controller.alerts` with the reading that opened them, the
  threshold, who acknowledged them and when they were resolved — تُحفظ التنبيهات
  مع القراءة التي فتحتها والحد ومن استجاب لها ومتى أُغلقت.

## 8. Nutrients and lab values — المغذيات وقيم المختبر

- A water sample from every unit goes to the Farm's contract laboratory once a
  month; the lab report is read by the document intake and checked against these
  bands — تُرسل عينة مياه من كل وحدة إلى المختبر المتعاقد معه مرة في الشهر.
- **Ammonia** (total ammonia nitrogen) stays **below 0.5 mg/L**; above it the
  fish are being poisoned by their own waste — تبقى الأمونيا دون 0.5 ملغ/لتر.
- **Nitrite** stays **below 0.5 mg/L**; a rise means the nitrifying bacteria are
  struggling — يبقى النتريت دون 0.5 ملغ/لتر.
- **Nitrate** is the plants' food and sits between **5 and 150 mg/L**; below 5 the
  plants starve, above 150 the stocking is too high for the beds — تتراوح النترات
  بين 5 و150 ملغ/لتر.
- **Iron** is kept at **2 to 3 mg/L** with chelated iron (NUT-02); the plants
  yellow below it — يُحافظ على الحديد بين 2 و3 ملغ/لتر.
- The lab's pH is compared with the probe's reading at the sample time; a
  difference over 0.2 means the probe is recalibrated (sensor calibration
  procedure, section 3) — تُقارن حموضة المختبر بقراءة المجس وقت أخذ العينة.

| Measure — القياس | Band — النطاق |
|---|---|
| pH | 6.6–7.2 |
| Ammonia (TAN) | < 0.5 mg/L |
| Nitrite | < 0.5 mg/L |
| Nitrate | 5–150 mg/L |
| Iron | 2–3 mg/L |
| Dissolved oxygen | ≥ 6.0 mg/L |
