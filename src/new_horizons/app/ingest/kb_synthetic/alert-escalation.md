---
synthetic: true
source: alert-escalation.md
lang: en+ar
title: "Alert Escalation — تصعيد التنبيهات"
---

# Alert Escalation — تصعيد التنبيهات

**SYNTHETIC demo document.** Who acts on what, how fast, and who decides when
the first person cannot. The same chain applies to the controller's alerts and
to the findings the analytics agent raises; the application's approval bar
records each decision in it.

## 1. Scope and roles — النطاق والأدوار

- **Technician on duty** — answers alerts on site, day or night, and fixes what
  can be fixed — الفني المناوب يستجيب للتنبيهات في الموقع ليلاً ونهاراً.
- **Farm Manager** — decides on findings, approves exceptions and owns the
  procedures — مدير المزرعة يقرر في النتائج ويعتمد الاستثناءات.
- **Owner** — decides what the Farm Manager escalates and is informed of every
  live-stock incident — المالك يقرر فيما يصعّده مدير المزرعة ويُبلَّغ بكل حادث يمس الكائنات الحية.

## 2. Who acts on what — من يتصرف في ماذا

- Live-stock risk alerts — low water level, low dissolved oxygen, high water
  temperature — go to the **technician on duty**, who answers on site within 2
  hours; unresolved at 4 hours they go to the **Farm Manager**, and from there to
  the **owner** — تنبيهات الخطر على الكائنات الحية تذهب إلى الفني المناوب ثم إلى
  مدير المزرعة ثم إلى المالك.
- pH and air-temperature alerts go to the technician on duty, who checks the
  probe before dosing or shading — تنبيهات الحموضة وحرارة الهواء تذهب إلى الفني
  المناوب الذي يفحص المجس أولاً.
- Reconciliation exceptions, document discrepancies and drift findings go to the
  **Farm Manager**, who decides; what the Farm Manager does not decide goes to the
  **owner** — استثناءات المطابقة وتباينات المستندات ونتائج الانحراف تذهب إلى مدير
  المزرعة، وما لا يقرر فيه يذهب إلى المالك.
- Suspected false records (for example a harvest that never shipped) go straight
  to the owner — الاشتباه بسجلات غير صحيحة يذهب مباشرة إلى المالك.

| Finding — النتيجة | First | Then | Last |
|---|---|---|---|
| Low water level, low DO, high water temp | Technician on duty (2 hours) | Farm Manager (4 hours) | Owner |
| pH, air temperature | Technician on duty | Farm Manager | — |
| Reconciliation exception | Farm Manager | Owner | — |
| Supplier invoice discrepancy | Farm Manager | Owner | — |
| Drift in water chemistry or equipment duty | Farm Manager | Owner | — |
| Suspected false records | Owner | — | — |

## 3. Timing — التوقيت

- A live-stock risk alert that is not resolved within **4 hours** is escalated,
  day or night, and is never closed inside the analytics application — أي تنبيه
  خطر على الكائنات الحية لا يُحل خلال 4 ساعات يُصعَّد ليلاً أو نهاراً.
- Any other finding that is not decided within **one working day** is escalated
  to the owner — أي نتيجة أخرى لا يُبت فيها خلال يوم عمل واحد تُصعَّد إلى المالك.
- An alert that nobody acknowledged is itself a finding: the escalation clock
  runs from the moment the alert opened, not from the acknowledgement — التنبيه
  الذي لم يقرّ به أحد نتيجة بحد ذاته، ويبدأ احتساب الوقت من لحظة فتحه.

## 4. Recording decisions — تسجيل القرارات

- Every decision is one of **Approve**, **Escalate to the owner** or **Reject** —
  كل قرار إما اعتماد أو تصعيد للمالك أو رفض.
- It is written to the Farm's hash-chained audit log with the person, the time
  and the knowledge-base section it rests on — يُكتب القرار في سجل التدقيق المتسلسل
  بالتجزئة مع الشخص والوقت وقسم قاعدة المعرفة الذي يستند إليه.
- A rejection carries a reason; a finding is never deleted, only decided — يحمل
  الرفض سبباً، ولا تُحذف النتيجة أبداً بل يُبت فيها.
- Pausing the analytics agent (the kill switch) is recorded the same way, with
  who paused it and when — يُسجَّل إيقاف الوكيل بالطريقة نفسها.

## 5. Out-of-hours rota — جدول المناوبة خارج الدوام

- One technician is on duty outside working hours every day of the year; the
  rota is set a month ahead by the Farm Manager — فني واحد مناوب خارج الدوام كل يوم.
- Alerts reach the on-duty phone; an alert that is not acknowledged within 15
  minutes is sent again to the senior technician — التنبيه الذي لا يُقرّ به خلال
  15 دقيقة يُرسل مجدداً إلى الفني الأقدم.
- A technician on leave hands the duty phone over in person — يسلّم الفني المجاز
  هاتف المناوبة شخصياً.
