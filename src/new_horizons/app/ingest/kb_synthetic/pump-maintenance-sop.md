---
synthetic: true
source: pump-maintenance-sop.md
lang: en+ar
title: "Pump and Aeration Maintenance SOP — إجراء صيانة المضخات والتهوية"
---

# Pump and Aeration Maintenance SOP — إجراء صيانة المضخات والتهوية

**SYNTHETIC demo document.** How the Farm keeps its water and air pumps
running, how fast a failure is answered, and how the controller's own records
prove a pump works. A pump that stops is the fastest way to lose fish and a
week's harvest.

## 1. Scope — النطاق

- Each grow unit has one **water pump** (circulation and refill) and one **air
  pump** feeding air stones in the fish tank — لكل وحدة مضخة مياه واحدة ومضخة هواء
  واحدة تغذي أحجار التهوية في حوض السمك.
- Pumps are started and stopped by the controller; a technician never runs a
  pump by hand except during a repair — تشغّل وحدة التحكم المضخات وتوقفها، ولا
  يشغّلها الفني يدوياً إلا أثناء الإصلاح.

## 2. Preventive service — الصيانة الوقائية

- Every pump is serviced **monthly** per unit: impeller and intake checked,
  hoses inspected, the run log read — تُصان كل مضخة شهرياً لكل وحدة.
- Air stones are replaced **quarterly**, or sooner when the air pump's duty
  rises (section 5) — تُستبدل أحجار التهوية كل ثلاثة أشهر أو قبل ذلك عند ارتفاع
  تشغيل مضخة الهواء.
- Every service is a work order (`pump_service`) with the technician, the unit
  and the outcome; a part fitted is recorded by its item code — كل صيانة أمر عمل
  يُسجَّل فيه الفني والوحدة والنتيجة ورمز القطعة المركّبة.

## 3. Pump failure response — الاستجابة لتعطل المضخة

- A water-pump failure alert is answered on site within 2 hours. This applies
  to a low-water-level alert and to a pump that does not respond to its
  commands, **day or night** — يُستجاب لتنبيه تعطل مضخة المياه في الموقع خلال
  ساعتين، ليلاً أو نهاراً.
- The on-duty technician **acknowledges the alert in the controller within 15
  minutes**, so everyone can see it is being handled — يقرّ الفني المناوب بالتنبيه
  في وحدة التحكم خلال 15 دقيقة.
- While the pump is down the technician tops the tank up by hand and runs the
  emergency aeration; the fish come first, the plants second — أثناء التعطل يملأ
  الفني الحوض يدوياً ويشغّل التهوية الاحتياطية.
- A pump that is **not fixed within 4 hours** is escalated to the Farm Manager,
  who decides on moving the fish (alert escalation, section 2) — المضخة التي لا
  تُصلح خلال 4 ساعات تُصعَّد إلى مدير المزرعة.
- The repair is a work order (`pump_repair`) linked to the alert by its
  `alert_no`; the time from the alert to the work order is the response time
  this section measures — الإصلاح أمر عمل مرتبط بالتنبيه، والزمن بين التنبيه وأمر
  العمل هو زمن الاستجابة.

## 4. Commanded vs observed — المأمور به مقابل المرصود

- The controller's commands and the level sensor are two independent records.
  Every water-pump run must raise the tank level by **at least 1.5 cm within
  30 minutes** — كل تشغيل لمضخة المياه يجب أن يرفع مستوى الحوض 1.5 سم على الأقل
  خلال 30 دقيقة.
- A run with no rise is a **failed command**: the controller asked, the water
  did not come — التشغيل الذي لا يرفع المستوى أمر فاشل.
- **Two consecutive failed commands are a pump failure** and are answered under
  section 3, whether or not the low-level alert has opened yet — أمران فاشلان
  متتاليان يعنيان تعطل المضخة ويُستجاب لهما وفق القسم 3.
- The nightly reconciliation lists every run of failed commands with its unit,
  first and last command, the level it ended at and the harvest that followed —
  تسرد المطابقة الليلية كل سلسلة أوامر فاشلة مع الوحدة وأول أمر وآخره.

## 5. Aeration duty — تشغيل التهوية

- The air pump's duty is the share of the day it runs. In normal weather it
  stays well below half — نسبة تشغيل مضخة الهواء هي الجزء من اليوم الذي تعمل فيه.
- A sustained duty **above 50%** means the fish are short of oxygen: service the
  air stones, check the water temperature and the stocking — تشغيل يزيد على 50%
  باستمرار يعني نقص الأكسجين: تُصان أحجار التهوية وتُفحص الحرارة وكثافة الأسماك.
- In a heatwave the duty rises in every unit; the unit with the warmest water
  rises first and is checked first — في موجات الحر يرتفع التشغيل في كل الوحدات.

## 6. Spare parts — قطع الغيار

- The Farm keeps one spare water-pump impeller (PART-01), air stones (PART-02)
  and filter socks (PART-04) in stock; a part used is re-ordered the same week —
  تحتفظ المزرعة بقطع احتياطية، وتُطلب القطعة المستخدمة في الأسبوع نفسه.
- A part fitted on a job is recorded on the work order and as a consumption line
  (source `work_order`) — القطعة المركّبة تُسجَّل في أمر العمل وفي سجل الاستهلاك.

## 7. Records and review — السجلات والمراجعة

- The Farm Manager reviews every pump failure within one working day: when the
  alert opened, when it was acknowledged, when the work order opened and what
  the unit lost — يراجع مدير المزرعة كل تعطل للمضخة خلال يوم عمل واحد.
- A response slower than section 3 allows is recorded as a finding in the
  audit log with the reason given — الاستجابة الأبطأ مما يسمح به القسم 3 تُسجَّل نتيجةً.
- The on-duty rota and the phone number that receives pump alerts are checked
  every Monday — يُراجع جدول المناوبة ورقم الهاتف الذي يستقبل التنبيهات كل اثنين.
