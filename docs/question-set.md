# Demo question set — expected answers

26 questions, 13 English and 13 Arabic, shuffled. Generated from `docs/question-set.yaml`; edit the YAML, then run `uv run python scripts/question-bank.py --render-md docs/question-set.yaml`.

**An Arabic question is answered in Arabic only, an English question in English only.** Identifiers (AQ-03, WO-2026-0042, INV-2026-0418), citations (pump-maintenance-sop.md §3), code spans and EUR are language-neutral. Currency: EUR in English, يورو in Arabic.

Every figure is ground truth. The metric resolvers (`src/new_horizons/app/analytics/metrics.py`) read the same artifacts as the screens, and `tests/test_validation.py` pins them. **Intent** is the known question it should match in `agents/analytics/intents.yaml`; — means off-script (the free agent answers). **Follows** means it is asked on that question's thread.

Run it: `uv run python scripts/question-bank.py --set docs/question-set.yaml [--model llama3.1:8b] [--only S04 S09]`

| # | Lang | Screen | Intent | Question | Expected answer | Must include | Must cite | Follows |
|---|---|---|---|---|---|---|---|---|
| S01 | EN | Overview | farm_overview | How many grow units and fish does the farm run? | 4 grow units (AQ-01 pepper, AQ-02 lettuce, AQ-03 tomato, AQ-04 basil), 97 European perch, 83.0 m² of grow beds. | 4, 97, 83.0 | data-dictionary.md §1 | — |
| S02 | AR | Reconcile | pump_failure_loss | كم كيلوغراماً خسرت الوحدة AQ-03 في الأسبوع التالي لتعطل المضخة، وماذا تقول إجراءات الصيانة عن زمن الاستجابة المطلوب؟ | خسرت الوحدة AQ-03 مقدار 9.80 كغ (حصاد 20 تموز 6.31 كغ مقابل 16.11 كغ في العادة)؛ تنص الإجراءات على الاستجابة خلال ساعتين، وانتظر التنبيه 113.2 ساعة. | 9.80, 113.2 | pump-maintenance-sop.md §3 | — |
| S03 | EN | Reconcile | pump_failure | Which unit had the pump failure, and when? | AQ-03, 12–17 July — 555 water-pump runs commanded with no level rise; alert AL-2026-0001, repair work order 113.2 hours later. | 555, 113.2 | pump-maintenance-sop.md §4 | — |
| S04 | EN | Reconcile | pump_failure_loss | And how many kilograms did that cost us? | 9.80 kg of tomato in the week after (6.31 kg against 16.11 kg usual), 35.28 EUR; the SOP's response time is 2 hours. | 9.80 | pump-maintenance-sop.md §3 | S03 |
| S05 | AR | Overview | open_alerts | في إنذارات مفتوحة هلّق بالمزرعة؟ | لا يوجد أي تنبيه مفتوح الآن (0)؛ صدر 16 تنبيهاً في الفترة، وتأخرت الاستجابة لتنبيه واحد (AL-2026-0001، 113.2 ساعة). | 16 | alert-escalation.md §2 | — |
| S06 | EN | Reconcile | recon_exposure | How much money is sitting in unresolved reconciliation right now? | 220.89 EUR and 48.63 kg across 8 exceptions — harvests never shipped 171.72, pump commanded with no level rise 35.28, feed consumed but never bought 13.89. | 220.89 | data-dictionary.md §7 | — |
| S07 | AR | Patterns | ghost_harvests | أي عمليات حصاد لم تُشحن أبداً ومن سجّلها؟ | 6 عمليات حصاد (31.52 كغ، 171.72 يورو) سجّلها كلها الفني TEC-06 دون توقيع ثانٍ ولم تُشحن. | 6, 31.52 | harvest-shipping-procedure.md §2 | — |
| S08 | EN | Reconcile | unmetered_feed | Was any feed used that we never bought? | Yes — AQ-02 was fed 7.308 kg of FEED-03 on 29 days in August with no purchase behind it, 13.89 EUR at list price. | 7.308, 13.89 | supplier-invoice-controls.md §4 | — |
| S09 | EN | Reconcile | feed_biosecurity | Is that a biosecurity problem? | Yes — only feed from an approved supplier through a recorded purchase may enter a unit; quarantine the bag, stop feeding it, inform the owner. | — | biosecurity-rules.md §3 | S08 |
| S10 | AR | Drift | heatwave_aeration | قديش اشتغلت مضخة الهوا بوحدة الطماطم وقت موجة الحر؟ | عملت مضخة الهواء في AQ-03 بنسبة 60.4% من اليوم خلال موجة الحر مقابل 26.6% في حزيران، فوق حد 50% في 5 أيام. | 60.4, 26.6 | pump-maintenance-sop.md §5 | — |
| S11 | EN | Drift | ph_drift_cause | Is the pH drift on AQ-04 a sensor problem or a chemistry problem? | A sensor problem — the lab measured pH 6.89 while the probe read 7.28; the decline between doses was unchanged; calibration on 21 August stepped it back. | 6.89, 7.28 | sensor-calibration.md §3 | — |
| S12 | AR | Patterns | sensor_dropouts | هل حدثت انقطاعات في الحساسات وهل تغيّر نتائج الانحراف؟ | انقطاعان (AQ-02 في 13 حزيران 9 ساعات، AQ-04 في 6 آب 5 ساعات)؛ فجوات لا أصفار، فلم يرفع أي منهما إنذار انحراف. | 9, 5 | sensor-calibration.md §4 | — |
| S13 | EN | Overview | harvest_and_sales | How much did the farm harvest and ship in August, and for how much? | 229.02 kg logged in 19 harvests, 210.17 kg shipped in 16 shipments for 1,008.49 EUR. | 229.02, 210.17, 1,008.49 | harvest-shipping-procedure.md §5 | — |
| S14 | AR | Patterns | technician_workload | أي فني أغلق أكبر عدد من أوامر العمل؟ | الفني TEC-07 أغلق 30 أمر عمل من أصل 147. | 30, 147 | pump-maintenance-sop.md §2 | — |
| S15 | EN | Drift | dosing_schedule | Why does the pH jump every Monday? | The controller doses pH up every Monday at 08:00, +0.3 and never above 7.1 — a normal weekly sawtooth, not drift. | 0.3, 7.1 | water-quality-sop.md §5 | — |
| S16 | AR | Documents | held_invoice | لماذا أُوقفت الفاتورة INV-2026-0418؟ | سعرها 2.95 يورو/كغ مقابل 2.40 في أمر الشراء (+22.9%، خارج هامش 5%)، وهي من المورد SUP-007 غير المعتمد بدلاً من SUP-001. | 2.95, 2.40 | supplier-invoice-controls.md §2 | — |
| S17 | EN | Reconcile | pump_failure_loss | How many kilograms did AQ-03 lose in the week after the pump failure, and what does the maintenance SOP say the response time should have been? | 9.80 kg (6.31 kg harvested on 20 July against 16.11 kg usual); the SOP says on site within 2 hours — the alert waited 113.2 hours. | 9.80, 2, 113.2 | pump-maintenance-sop.md §3 | — |
| S18 | AR | Reconcile | pump_failure | أي وحدة تعطلت مضختها ومتى؟ | الوحدة AQ-03 من 12 إلى 17 تموز — أُمرت المضخة 555 مرة ولم يرتفع المستوى، وجاء أمر الإصلاح بعد 113.2 ساعة. | 555 | pump-maintenance-sop.md §4 | — |
| S19 | AR | Reconcile | pump_failure_loss | وكم كيلوغراماً كلّفنا ذلك؟ | 9.80 كغ من الطماطم في الأسبوع التالي، أي 35.28 يورو. | 9.80 | pump-maintenance-sop.md §3 | S18 |
| S20 | EN | Patterns | ghost_harvests | Who's been logging harvests that never leave the building? | TEC-06 — 6 harvests, 31.52 kg, none countersigned, none shipped. | 6 | harvest-shipping-procedure.md §2 | — |
| S21 | AR | Overview | open_alerts | هل جرت الاستجابة لكل التنبيهات في الوقت المحدد؟ | لا — تنبيه واحد تأخرت الاستجابة له (AL-2026-0001 على AQ-03، 113.2 ساعة مقابل ساعتين)؛ صدر 16 تنبيهاً ولا يوجد مفتوح الآن. | 113.2 | alert-escalation.md §2 | — |
| S22 | AR | Reconcile | recon_exposure | كم المبلغ المعرّض للخطر في استثناءات المطابقة؟ | 220.89 يورو و48.63 كغ عبر 8 استثناءات. | 220.89 | data-dictionary.md §7 | — |
| S23 | EN | Admin center | decision_on_finding | Who approved that hold, and under which rule? | The audit log's latest human decision — who, when and the KB section it rests on — or that none is recorded yet. | — | alert-escalation.md §4 | — |
| S24 | AR | Overview | farm_overview | قديش عنا سمك وقديش مساحة أحواض الزراعة؟ | 97 سمكة على 83.0 م² من أحواض الزراعة في 4 وحدات. | 97, 83.0 | data-dictionary.md §1 | — |
| S25 | EN | Drift | — | Which unit had the highest average water temperature in July? | AQ-03, 21.69 °C on average in July (telemetry.readings). | 21.69 | — | — |
| S26 | AR | Patterns | — | كم أمر عمل سُجّل على الوحدة AQ-02 خلال الفترة كلها؟ | 33 أمر عمل سُجّلت على الوحدة AQ-02 (maintenance.work_orders). | 33 | — | — |
