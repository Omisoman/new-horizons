---
synthetic: true
source: supplier-invoice-controls.md
lang: en+ar
title: "Supplier Invoice Controls — ضوابط فواتير الموردين"
---

# Supplier Invoice Controls — ضوابط فواتير الموردين

**SYNTHETIC demo document.** How the Farm buys feed, nutrients and parts, how
a supplier's invoice is matched before it is paid, and how what was used is
reconciled with what was bought.

## 1. Scope — النطاق

- Every purchase starts as a purchase order (PO-YYYY-NNNN) with the supplier,
  the item, the quantity and the agreed unit price — تبدأ كل عملية شراء بأمر شراء
  يحدد المورد والصنف والكمية وسعر الوحدة المتفق عليه.
- Goods are received against the order; the supplier's invoice is matched to the
  order and the goods received before it is paid — تُستلم البضاعة مقابل الأمر،
  وتُطابق الفاتورة مع الأمر والبضاعة المستلمة قبل الدفع.
- Invoices arrive as paper or scanned PDFs and are read by the document intake
  in the analytics application — تصل الفواتير ورقية أو ممسوحة ضوئياً.

## 2. Price and quantity — السعر والكمية

- The invoice unit price must be **within 5% of the purchase-order price**, and
  the quantity must equal the goods received — يجب أن يكون سعر الوحدة في الفاتورة
  ضمن 5% من سعر أمر الشراء، وأن تساوي الكمية البضاعة المستلمة.
- An invoice above that tolerance is put on **hold**: it is not paid until the
  Farm Manager decides — الفاتورة التي تتجاوز هذا الهامش تُعلَّق ولا تُدفع حتى يقرر
  مدير المزرعة.
- If the Farm Manager accepts the goods at the agreed price, the supplier issues
  a **credit note** for the difference before payment — إذا قبل مدير المزرعة
  البضاعة بالسعر المتفق عليه يصدر المورد إشعاراً دائناً بالفرق قبل الدفع.
- A price rise is agreed on a new purchase order, never on an invoice — أي رفع
  للسعر يُتفق عليه في أمر شراء جديد وليس في الفاتورة.

## 3. Supplier master — سجل الموردين

- The supplier reference on the invoice must match the purchase order's supplier
  and be on the **approved supplier list** — يجب أن يطابق رمز المورد في الفاتورة
  مورد أمر الشراء وأن يكون في قائمة الموردين المعتمدين.
- A mismatch puts the invoice on hold. It is verified by calling the **phone
  number on file** in the supplier master — never a number, e-mail or contact
  printed on the invoice itself — أي عدم تطابق يعلّق الفاتورة، ويُتحقق منه بالاتصال
  على رقم الهاتف المسجل لدينا فقط، وليس على أي رقم مطبوع على الفاتورة.
- A supplier is added to the approved list only by the Farm Manager, after a
  biosecurity check of its products (biosecurity rules, section 3) — لا يُضاف مورد
  إلى القائمة المعتمدة إلا بقرار من مدير المزرعة.

## 4. Stock reconciliation — مطابقة المخزون

- A **stock count** of feed, nutrients and spare parts is taken every **Friday**
  and compared with purchases received minus consumption recorded — يُجرى جرد
  المخزون كل جمعة ويُقارن بالمشتريات المستلمة ناقص الاستهلاك المسجل.
- Consumption of an item with no purchase or no stock on hand is unmetered — أي
  استهلاك لصنف لم يُشترَ أو لا رصيد له في المخزون استهلاك غير مقيس. Investigate it
  within 2 working days and correct the stock count.
- Unmetered feed is also a biosecurity question: where did the feed come from?
  (biosecurity rules, section 3) — العلف غير المقيس مسألة أمن حيوي أيضاً.
- The reconciliation prices unmetered consumption at the item's list price —
  تُسعَّر الكميات غير المقيسة بسعر القائمة للصنف.

## 5. Payment terms — شروط الدفع

- A matched invoice is paid **30 days** after it is matched — تُدفع الفاتورة
  المطابقة بعد 30 يوماً من مطابقتها.
- A held invoice is paid only after the Farm Manager's decision is recorded in
  the audit log — لا تُدفع الفاتورة المعلّقة إلا بعد تسجيل قرار مدير المزرعة.
- The purchase order then moves from `awaiting_invoice` to `invoiced` with the
  supplier's invoice number — ينتقل أمر الشراء عندها إلى حالة "مفوتر" مع رقم الفاتورة.

## 6. Invoices read by the document intake — الفواتير المقروءة آلياً

- The document intake reads an invoice on the Farm's own hardware, extracts its
  fields and checks every figure against the text it read — تقرأ وحدة استلام
  المستندات الفاتورة على أجهزة المزرعة وتستخرج حقولها.
- It then reconciles the invoice with its purchase order, the supplier master
  and the approved supplier list, and raises a hold with the governing section
  when a check fails — ثم تطابق الفاتورة مع أمر الشراء وسجل الموردين.
- The intake recommends; the Farm Manager decides, and the decision is recorded
  in the audit log — يوصي الاستلام الآلي، ويقرر مدير المزرعة.
