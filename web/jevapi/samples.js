// SYNTHETIC sample documents and a SIMULATED extractor output for the no-key demo.
// The confidences imitate an overconfident model. None of this is a real model's output.
export const SAMPLES = [
  {
    id: "clean",
    label: "Clean invoice",
    text: "ACME SUPPLIES PVT LTD\nTax Invoice\nInvoice No: INV-2231\nDate: 2026-09-15\nDue date: 2026-10-15\nBill to: Kiran Traders, Pune\nItems: 40 x Steel brackets @ 1,205.00\nTotal amount: ₹48,200.00",
    extracted: [
      { field: "vendor_name", value: "Acme Supplies Pvt Ltd", confidence: 0.99 },
      { field: "invoice_number", value: "INV-2231", confidence: 0.99 },
      { field: "due_date", value: "2026-10-15", confidence: 0.98 },
      { field: "total_amount", value: "48200.00", confidence: 0.99 },
    ],
  },
  {
    id: "messy",
    label: "Messy scan",
    text: "N0rth Star Logistics\nlnvoice # NS-88l9\nlssued 03/09/2026   Payable within 30 days\nFreight Mumbai -> Delhi\nSub total 21,450\nGST 18% 3,861\nT0TAL 25,311",
    extracted: [
      { field: "vendor_name", value: "North Star Logistics", confidence: 0.96 },
      { field: "invoice_number", value: "NS-8819", confidence: 0.93 },
      { field: "due_date", value: "2026-10-03", confidence: 0.91 },
      { field: "total_amount", value: "21450", confidence: 0.97 },
    ],
  },
  {
    id: "missing",
    label: "Missing due date",
    text: "Blue Lotus Design Studio\nInvoice BL-104\nLogo and brand kit\nAmount payable: ₹15,000\nThank you!",
    extracted: [
      { field: "vendor_name", value: "Blue Lotus Design Studio", confidence: 0.98 },
      { field: "invoice_number", value: "BL-104", confidence: 0.97 },
      { field: "due_date", value: null, confidence: 0.6 },
      { field: "total_amount", value: "15000", confidence: 0.95 },
    ],
  },
];

export const DEFAULT_FIELDS = [
  { name: "vendor_name", label: "Vendor", description: "company that sent the invoice" },
  { name: "invoice_number", label: "Invoice number", description: "the invoice id" },
  { name: "due_date", label: "Due date", description: "payment due date as YYYY-MM-DD", type: "date" },
  { name: "total_amount", label: "Total amount", description: "final amount payable, number only", type: "number" },
];
