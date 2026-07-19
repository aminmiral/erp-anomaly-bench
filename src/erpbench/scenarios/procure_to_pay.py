"""Procure-to-pay scenario: PO -> confirm -> receive -> vendor bill -> payment.

Each case runs the real flow against Odoo (so traces respect the actual ERP
state machine) while the driver records events and labels on its own virtual
clock. Anomaly modes deviate from the normal flow in controlled, labeled ways.

v0 simplification: all RPC calls run as admin; actors/roles are simulated in
the log. A later milestone runs real per-role Odoo users so role anomalies
are enforced (or blocked) by Odoo itself.
"""

from __future__ import annotations

import random

from ..eventlog import Event, EventLog, SimClock

# Anomaly typology (trace-level label values)
SKIPPED_RECEIPT = "skipped_receipt"      # 3-way match violation: billed & paid, never received
PRICE_OVERBILL = "price_overbill"        # bill price inflated 15-60% vs PO price
DUPLICATE_INVOICE = "duplicate_invoice"  # same PO billed and paid twice
SELF_APPROVAL = "self_approval"          # requester approves their own PO

# Hard typology: no single document is wrong; the signal is subtle or spans
# traces, so document-level audit rules are structurally blind to these.
SPLIT_PURCHASE = "split_purchase"        # one buy split into POs just under threshold
SUBTLE_OVERBILL = "subtle_overbill"      # 1-3% skim, overlapping legitimate variation
AFTER_HOURS = "after_hours"              # approval/billing at 1-5 AM

EASY_MODES = [SKIPPED_RECEIPT, PRICE_OVERBILL, DUPLICATE_INVOICE, SELF_APPROVAL]
HARD_MODES = [SPLIT_PURCHASE, SUBTLE_OVERBILL, AFTER_HOURS]
ANOMALY_MODES = EASY_MODES + HARD_MODES

APPROVAL_THRESHOLD = 5000.0  # POs above this need senior sign-off (simulated policy)

REQUESTERS = ["mia.patel", "leo.fernandez", "sara.khan", "tom.novak"]
MANAGERS = ["nadia.rahman", "victor.osei"]


class ProcureToPayCase:
    def __init__(self, client, log: EventLog, clock: SimClock, rng: random.Random,
                 vendors: dict[str, int], products: dict[str, int]):
        self.c = client
        self.log = log
        self.clock = clock
        self.rng = rng
        self.vendors = vendors
        self.products = products

    def run(self, case_id: str, mode: str = "normal") -> None:
        rng = self.rng
        requester = rng.choice(REQUESTERS)
        approver = requester if mode == SELF_APPROVAL else rng.choice(MANAGERS)
        vendor_name, vendor_id = rng.choice(list(self.vendors.items()))
        off = mode == AFTER_HOURS

        po_id, po_total = self._create_po(case_id, requester, vendor_id,
                                          vendor_name=vendor_name)
        self._confirm_po(case_id, po_id, approver, off_hours=off,
                         anomaly=SELF_APPROVAL if mode == SELF_APPROVAL
                         else AFTER_HOURS if off else "normal")

        if mode == SKIPPED_RECEIPT:
            self.log.mark_trace(case_id, SKIPPED_RECEIPT)  # the anomaly is a missing event
        else:
            self._receive(case_id, po_id, requester)

        # Normal bills carry legitimate variation (corrections, rounding):
        # 70% match the PO exactly, the rest land within +/-2%. The subtle
        # overbill (1-3%) deliberately overlaps that band.
        if mode == PRICE_OVERBILL:
            factor, bill_anomaly = 1.0 + rng.uniform(0.15, 0.6), PRICE_OVERBILL
        elif mode == SUBTLE_OVERBILL:
            factor, bill_anomaly = 1.0 + rng.uniform(0.01, 0.03), SUBTLE_OVERBILL
        elif off:
            factor, bill_anomaly = 1.0, AFTER_HOURS
        else:
            factor = 1.0 if rng.random() < 0.7 else 1.0 + rng.uniform(-0.02, 0.02)
            bill_anomaly = "normal"
        bill_id, billed = self._create_and_post_bill(
            case_id, po_id, factor, off_hours=off, anomaly=bill_anomaly)
        self._pay(case_id, bill_id, billed, off_hours=off,
                  anomaly=AFTER_HOURS if off else "normal")

        if mode == DUPLICATE_INVOICE:
            dup_id, dup_amount = self._create_and_post_bill(
                case_id, po_id, 1.0, anomaly=DUPLICATE_INVOICE)
            self._pay(case_id, dup_id, dup_amount, anomaly=DUPLICATE_INVOICE)

    def run_split(self, base_id: str) -> None:
        """One purchase worth 1.8-2.8x the approval threshold, split into
        2-3 POs each just under it: same requester, same vendor, days apart.
        Every individual trace is a perfectly normal flow — the anomaly only
        exists across the group."""
        rng = self.rng
        requester = rng.choice(REQUESTERS)
        approver = rng.choice(MANAGERS)
        vendor_name, vendor_id = rng.choice(list(self.vendors.items()))
        for part in range(rng.randint(2, 3)):
            case_id = f"{base_id}-S{part + 1}"
            target = rng.uniform(0.88, 0.99) * APPROVAL_THRESHOLD
            po_id, _ = self._create_po(case_id, requester, vendor_id,
                                       target_amount=target,
                                       vendor_name=vendor_name)
            self._confirm_po(case_id, po_id, approver)
            self._receive(case_id, po_id, requester)
            bill_id, billed = self._create_and_post_bill(case_id, po_id, 1.0)
            self._pay(case_id, bill_id, billed)
            self.log.mark_trace(case_id, SPLIT_PURCHASE)

    # ---- individual activities ---------------------------------------

    def _create_po(self, case_id, requester, vendor_id, target_amount=None,
                   vendor_name=None):
        lines = []
        if target_amount is not None:
            # target_amount is the tax-INCLUSIVE total (approval thresholds
            # apply to what the approver sees). Created at the pre-tax guess,
            # then rescaled below once Odoo has applied its taxes.
            name, (pid, cost) = self.rng.choice(list(self.products.items()))
            qty = max(1, round(target_amount / cost))
            lines.append((0, 0, {
                "product_id": pid,
                "product_qty": qty,
                "price_unit": round(target_amount / qty, 2),
            }))
        else:
            for _ in range(self.rng.randint(1, 3)):
                name, (pid, cost) = self.rng.choice(list(self.products.items()))
                lines.append((0, 0, {
                    "product_id": pid,
                    "product_qty": self.rng.randint(1, 20),
                    "price_unit": round(cost * self.rng.uniform(0.95, 1.1), 2),
                }))
        po_id = self.c.env["purchase.order"].create(
            {"partner_id": vendor_id, "order_line": lines})
        po = self.c.env["purchase.order"].browse(po_id)
        total = po.amount_total
        if target_amount is not None and total > 0:
            for line in po.order_line:
                line.write({"price_unit":
                            round(line.price_unit * target_amount / total, 2)})
            total = self.c.env["purchase.order"].browse(po_id).amount_total
        self.log.record(Event(case_id, "Create PO", self.clock.step(), requester,
                              "requester", amount=total, doc_ref=f"PO/{po_id}",
                              vendor=vendor_name))
        return po_id, total

    def _confirm_po(self, case_id, po_id, approver, off_hours=False, anomaly="normal"):
        self.c.env["purchase.order"].browse(po_id).button_confirm()
        role = "requester" if anomaly == SELF_APPROVAL else "manager"
        self.log.record(Event(case_id, "Approve PO",
                              self.clock.step(off_hours=off_hours), approver,
                              role, doc_ref=f"PO/{po_id}", anomaly_type=anomaly))

    def _receive(self, case_id, po_id, actor):
        po = self.c.env["purchase.order"].browse(po_id)
        for picking_id in po.picking_ids.ids:
            picking = self.c.env["stock.picking"].browse(picking_id)
            for move in picking.move_ids:
                move.write({"quantity": move.product_uom_qty, "picked": True})
            picking.button_validate()
        self.log.record(Event(case_id, "Receive Goods", self.clock.step(), actor,
                              "requester", doc_ref=f"PO/{po_id}"))

    def _create_and_post_bill(self, case_id, po_id, price_factor,
                              off_hours=False, anomaly="normal"):
        # Bill created directly as an account.move linked to the PO lines
        # (avoids the frozendict-serialization bug in Odoo 17's
        # action_create_invoice over JSON-RPC, and models an accountant
        # keying in a bill — which is how duplicate/overbilled invoices
        # happen in practice).
        po = self.c.env["purchase.order"].browse(po_id)
        lines = [(0, 0, {
            "product_id": pl.product_id.id,
            "quantity": pl.product_qty,
            "price_unit": round(pl.price_unit * price_factor, 2),
            "purchase_line_id": pl.id,
        }) for pl in po.order_line]
        # account.move is never browse()d: odoorpc's browse reads all fields,
        # and Odoo 17's tax_totals field contains frozendicts that fail
        # JSON-RPC serialization. Targeted execute_kw calls avoid that.
        bill_id = self.c.odoo.execute_kw("account.move", "create", [{
            "move_type": "in_invoice",
            "partner_id": po.partner_id.id,
            "invoice_date": self.clock.now.date().isoformat(),
            "ref": po.name,
            "invoice_line_ids": lines,
        }], {})
        self.c.odoo.execute_kw("account.move", "action_post", [[bill_id]], {})
        amount = self.c.odoo.execute_kw(
            "account.move", "read", [[bill_id], ["amount_total"]], {})[0]["amount_total"]
        self.log.record(Event(case_id, "Post Vendor Bill",
                              self.clock.step(off_hours=off_hours),
                              "erin.accounts", "accountant", amount=amount,
                              doc_ref=f"BILL/{bill_id}", anomaly_type=anomaly))
        return bill_id, amount

    def _pay(self, case_id, bill_id, amount, off_hours=False, anomaly="normal"):
        ctx = {"active_model": "account.move", "active_ids": [bill_id]}
        wizard_id = self.c.odoo.execute_kw(
            "account.payment.register", "create", [{}], {"context": ctx})
        self.c.odoo.execute_kw(
            "account.payment.register", "action_create_payments",
            [[wizard_id]], {"context": ctx})
        self.log.record(Event(case_id, "Pay Vendor Bill",
                              self.clock.step(off_hours=off_hours),
                              "erin.accounts", "accountant", amount=amount,
                              doc_ref=f"BILL/{bill_id}", anomaly_type=anomaly))
