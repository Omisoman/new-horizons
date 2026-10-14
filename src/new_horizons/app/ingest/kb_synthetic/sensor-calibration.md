---
synthetic: true
source: sensor-calibration.md
lang: en+ar
title: "Sensor Calibration Procedure — إجراء معايرة الحساسات"
---

# Sensor Calibration Procedure — إجراء معايرة الحساسات

**SYNTHETIC demo document.** How the Farm keeps its probes honest, how to tell
a probe that drifts from water that changes, and how a missing reading is
treated. Every analysis of the Farm's water rests on these sensors.

## 1. Scope — النطاق

- Each grow unit carries probes for **pH**, **dissolved oxygen**, **water
  temperature** and **water level**, plus an air temperature and humidity
  sensor — تحمل كل وحدة مجسات للحموضة والأكسجين المذاب وحرارة المياه ومستواها.
- The controller reads every probe every 15 minutes and stores the readings in
  `telemetry.readings` — تقرأ وحدة التحكم كل مجس كل 15 دقيقة.

## 2. Calibration interval — فترات المعايرة

- pH and dissolved-oxygen probes are calibrated **monthly**. pH uses a two-point
  calibration with buffers **7.0 and 4.0** — تُعاير مجسات الحموضة والأكسجين شهرياً،
  والحموضة بمعايرة من نقطتين بمحلولين 7.0 و4.0.
- Level sensors are calibrated **quarterly** against a dip stick — تُعاير حساسات
  المستوى كل ثلاثة أشهر.
- Every calibration is a work order (`sensor_calibration`) with the technician
  and the unit — كل معايرة أمر عمل يُسجَّل فيه الفني والوحدة.
- A reading may **step** at a calibration: the step is the size of the error
  the probe had been carrying, and analyses read it as a correction, not a
  change in the water — قد تقفز القراءة عند المعايرة بمقدار الخطأ الذي كان المجس يحمله.

## 3. Sensor drift or chemistry drift — انحراف المجس أم انحراف الكيمياء

- When a unit's pH moves away from its usual range, first ask whether the
  **water** changed or the **probe** did — عندما تبتعد حموضة الوحدة عن نطاقها المعتاد
  يُسأل أولاً: هل تغيّرت المياه أم المجس؟
- If the pH moves but the **decline between doses** and the dosing needed are
  unchanged, suspect the probe: the water behaves as it always did, only the
  reading moved — إذا تحركت الحموضة دون أن يتغير الانخفاض بين الجرعات أو الجرعات
  اللازمة فالمشكلة في المجس.
- Check a suspected probe with a handheld meter or a lab sample; a difference
  **over 0.2** between the probe and the check means recalibrate — يُفحص المجس
  المشتبه به بجهاز يدوي أو عينة مختبر، والفرق الذي يزيد على 0.2 يعني إعادة المعايرة.
- If the decline between doses is steeper, or more dosing is needed to hold the
  band, the **chemistry** changed: nitrification, stocking or feed. That is a
  water problem and goes to the Farm Manager — إذا صار الانخفاض بين الجرعات أشد أو
  احتاجت الوحدة إلى جرعات أكثر فالكيمياء هي التي تغيرت، وتُرفع المسألة إلى مدير المزرعة.
- Never dose to correct a reading that a handheld meter does not confirm — لا تُضاف
  أي جرعة لتصحيح قراءة لا يؤكدها الجهاز اليدوي.

## 4. Dropouts and gaps — الانقطاعات والفجوات

- A sensor that stops reporting leaves a **gap** in the readings — الحساس الذي يتوقف
  عن الإرسال يترك فجوة في القراءات.
- Gaps are **never** filled with zeros or with carried-forward values; a zero
  pH or a zero water level is a reading the water never had — لا تُملأ الفجوات
  أبداً بأصفار أو بقيم منقولة من قبل.
- Analyses — drift, averages, uptime — exclude the missing intervals and report
  how many there were — تستبعد التحليلات الفترات الناقصة وتذكر عددها.
- A dropout **longer than 4 hours** gets a work order to check the probe and its
  cable — الانقطاع الذي يزيد على 4 ساعات يستوجب أمر عمل لفحص المجس وكابله.
- Sensor uptime is the share of expected 15-minute readings that arrived — نسبة
  تشغيل الحساس هي حصة القراءات المتوقعة التي وصلت فعلاً.

## 5. Handheld meters and lab samples — الأجهزة اليدوية وعينات المختبر

- Each technician carries a handheld pH and DO meter, itself calibrated weekly —
  يحمل كل فني جهازاً يدوياً لقياس الحموضة والأكسجين يُعاير أسبوعياً.
- A lab report gives the water's true values at the sample time; it is the
  reference a probe is judged against — يعطي تقرير المختبر القيم الحقيقية للمياه
  وقت أخذ العينة، وهو المرجع الذي يُحكم به على المجس.
- When a lab value and the probe's reading at the same time differ by more than
  0.2 pH, the probe is recalibrated and the work order cites the lab report —
  عندما يختلف المختبر والمجس بأكثر من 0.2 تُعاد معايرة المجس.
